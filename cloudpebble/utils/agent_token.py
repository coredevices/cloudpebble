""" Scoped, short-lived tokens handed to the agent VM so it can call back into the
CloudPebble API on behalf of one user, for one project, for one session.

Same shape as ide.api.qemu.generate_phone_token: a random secret in redis with a TTL.
This is the security boundary of the whole agent feature, so the token is scoped to
(user, project, session), expires in 30 minutes, and is accepted by a hand-picked
handful of views only.
"""

import datetime
import hmac
import json
import logging
import secrets
import string
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt, csrf_protect

from utils.redis_helper import redis_client

logger = logging.getLogger(__name__)

# Must outlast the longest WHOLE turn, not the longest gap in one. Measured turns
# run to 1400s and the relay's own read timeout is 1800s, so a 30 minute token
# expired mid-turn: every remaining write_file and build came back "Invalid or
# expired agent token" and the model flailed against it until max_turns. The
# relay revokes the token when the turn ends, so a longer TTL is only exposure
# for turns whose worker died before the revoke.
TOKEN_TTL = 3600  # seconds
_TOKEN_ALPHABET = frozenset(string.ascii_letters + string.digits + '-_')


def _key(token):
    return 'agent-token-%s' % token


def _valid_shape(token):
    """ Cheap sanity check before a caller-supplied string is used as a redis key. """
    return bool(token) and len(token) <= 128 and set(token) <= _TOKEN_ALPHABET


def mint(user, project, session):
    """ Create a token scoped to this (user, project, session). Returns the secret. """
    token = secrets.token_urlsafe(32)
    redis_client.set(_key(token), json.dumps({
        'token': token,
        'user_id': user.id,
        'project_id': project.id,
        'session_id': session.id,
    }), ex=TOKEN_TTL)
    return token


def resolve(token):
    """ Returns (user, project, session) or None if the token is unknown, expired or
    points at rows that have since been deleted. """
    if not _valid_shape(token):
        return None
    raw = redis_client.get(_key(token))
    if raw is None:
        return None
    scope = json.loads(raw)
    if not hmac.compare_digest(str(scope.get('token', '')), token):
        return None

    # Imported lazily: this module is imported from utils, which can be loaded before
    # the app registry is ready.
    from django.contrib.auth.models import User
    from ide.models.agent import AgentSession
    from ide.models.project import Project
    try:
        session = AgentSession.objects.get(pk=scope['session_id'])
        project = Project.objects.get(pk=scope['project_id'])
        user = User.objects.get(pk=scope['user_id'])
    except (AgentSession.DoesNotExist, Project.DoesNotExist, User.DoesNotExist):
        return None
    # Belt and braces: the token's scope must still describe reality.
    if project.owner_id != user.id or session.project_id != project.id or session.user_id != user.id:
        logger.warning("agent token scope no longer valid: user=%s project=%s session=%s",
                       scope['user_id'], scope['project_id'], scope['session_id'])
        return None
    return user, project, session


def revoke(token):
    if _valid_shape(token):
        redis_client.delete(_key(token))


def _bearer(request):
    """ The agent token from the Authorization header, or None if there isn't one. """
    scheme, _sep, token = request.META.get('HTTP_AUTHORIZATION', '').partition(' ')
    return token.strip() if scheme.lower() == 'bearer' else None


def _authenticate(request, token, url_project_id):
    """ Resolve the token and stamp the request with it. Raises PermissionDenied. """
    resolved = resolve(token)
    if resolved is None:
        raise PermissionDenied(_("Invalid or expired agent token."))
    user, project, session = resolved
    if url_project_id is not None and str(url_project_id) != str(project.id):
        raise PermissionDenied(_("Agent token is not valid for this project."))
    request.user = user
    request.agent_project = project
    request.agent_session = session


def agent_token_required(f):
    """ Authenticate a request by 'Authorization: Bearer <agent token>' *instead of* a
    session cookie. Sets request.user, request.agent_project and request.agent_session.

    For the transcript routes, which no browser ever calls. Views that also serve the
    IDE want allow_agent_token instead.
    """
    @wraps(f)
    def _wrapped(request, *args, **kwargs):
        token = _bearer(request)
        if token is None:
            raise PermissionDenied(_("Agent token required."))
        _authenticate(request, token, kwargs.get('project_id'))
        return f(request, *args, **kwargs)
    return _wrapped


def allow_agent_token(view):
    """ Accept *either* the usual session cookie or an agent bearer token.

    Apply this as the outermost decorator on the handful of views in AGENT_PLAN §3.3 --
    project_info, source load/save/create/delete, build run/last/info/log/download -- and
    nothing else. Their siblings in the same modules (rename_source_file,
    save_project_settings, delete_project, github_push, publish_submit, ...) must keep
    rejecting the token, which is why this is stamped on view by view rather than
    installed as middleware.

    Requests carrying a bearer token get request.user populated before the view's own
    @login_required runs, so the view's get_object_or_404(..., owner=request.user) is
    still what scopes the data. They are also exempt from CSRF, because there is no
    cookie to ride on; cookie-authenticated requests keep the CSRF check they had.
    """
    cookie_path = csrf_protect(view)

    @wraps(view)
    def _dispatch(request, *args, **kwargs):
        token = _bearer(request)
        if token is None:
            return cookie_path(request, *args, **kwargs)
        _authenticate(request, token, kwargs.get('project_id'))
        return view(request, *args, **kwargs)

    # Outermost, so CsrfViewMiddleware defers to the per-path decision above.
    return csrf_exempt(_dispatch)


def consume_turn(user):
    """ Count one agent turn against the user's daily allowance.

    Returns True if the turn is allowed, False if the cap is already spent. The counter
    is keyed by local date and expires at midnight, so it resets on its own.
    """
    now = timezone.localtime()
    key = 'agent-turns-%s-%s' % (user.id, now.date().isoformat())
    used = redis_client.incr(key)
    if used == 1:
        midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        # +60s of slack because a DST shift can move local midnight by an hour; the date
        # in the key is what actually guarantees the reset.
        redis_client.expire(key, int((midnight - now).total_seconds()) + 60)
    return used <= settings.AGENT_MAX_TURNS_PER_DAY
