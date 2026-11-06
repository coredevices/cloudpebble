import base64
import hashlib
import json
import logging
import secrets
import re
import threading
import time

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
import uuid as uuid_module

from django.core.exceptions import (ObjectDoesNotExist, PermissionDenied,
                                    ValidationError)
from django.db import IntegrityError, connection, transaction
from django.db.models import Max
from django.http import HttpResponse, HttpResponseNotFound, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from urllib.parse import urlencode

from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ide.agent_providers import config_for, describe_for_ui
from ide.models.agent import (AgentCredential, AgentMessage, AgentSession,
                              AgentTranscript)
from ide.models.project import Project
from utils.agent_token import agent_token_required, consume_turn, mint, revoke
from utils.jsonview import BadRequest, InternalServerError, json_view
from utils.redis_helper import redis_client

__author__ = 'ericmigi'

logger = logging.getLogger(__name__)

# Browser SSE poll cadence and keepalive, matching ide.api.sse's reasoning: the
# comment line is what makes gunicorn notice a vanished client.
POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 15
# Connect/read timeouts for the agent VM. The read timeout is a gap timeout, not
# a total: requests resets it on every chunk, so it only has to outlast the
# longest silence between SSE events -- but a model thinking through a big
# generation goes quiet for minutes at a stretch.
#
# Measured whole turns on the space-watchface brief: claude-sonnet-5 441s,
# deepseek-v4-flash 912s, kimi-k3 1400s. A 900s read timeout cut deepseek off
# mid-turn and reported it as "service unavailable", so give it real headroom.
TURN_TIMEOUT = (10, getattr(settings, 'AGENT_TURN_READ_TIMEOUT', 1800))

# Same shape ide/urls.py accepts for qemu_mobile_token.
EMULATOR_UUID_RE = re.compile(r'^[0-9a-f-]{32,36}$')

# Error kinds that end a turn. Anything else -- a transcript mirror hiccup, a
# recoverable assistant-level error -- streams through while the query continues.
FATAL_ERROR_KINDS = frozenset(['relay', 'timeout', 'cancelled', 'usage_limit', 'auth'])

# A turn is relayed by an in-process thread, so a deploy, a worker restart or the
# agent VM bouncing kills it with no terminal event: the session stays 'running'
# forever, every new message is refused with "already working", and the browser
# sits disabled. Sessions therefore heal themselves -- if nothing has been
# appended for this long, the relay is gone.
#
# This measures silence, not death, and healing a LIVE turn is worse than the bug
# it fixes: at 240s a healthy turn that spent five minutes generating a file got a
# "the agent stopped responding" card while its own tool results kept arriving
# underneath it. Past the relay's read timeout, silence really does mean the relay
# is gone -- it would have timed out and written its own terminal event first.
STALE_TURN_SECONDS = getattr(settings, 'AGENT_STALE_TURN_SECONDS',
                             TURN_TIMEOUT[1] + 120)


# ---------------------------------------------------------------------------
# helpers


def _agent_url(path):
    return settings.AGENT_URL.rstrip('/') + '/' + path


def _agent_headers():
    return {'Authorization': settings.AGENT_AUTH_HEADER}


def _require_agent_service():
    """Fail closed rather than talking to the agent VM with a guessable secret."""
    if not settings.AGENT_URL or not settings.AGENT_AUTH_HEADER:
        raise InternalServerError(_("No agent service is configured."))


def agent_enabled(user):
    """Feature flag. Empty setting means nobody; '*' means everybody.

    Settings keeps the raw strings, but tolerate a csv string or a list of ints too so
    the flag behaves the same however it is supplied.
    """
    if not user.is_authenticated:
        return False
    enabled = settings.AGENT_ENABLED_USERS
    if isinstance(enabled, str):
        enabled = enabled.replace(',', ' ').split()
    enabled = {str(x).strip() for x in enabled}
    return '*' in enabled or str(user.id) in enabled


def _check_enabled(user):
    if not agent_enabled(user):
        raise PermissionDenied(_("The agent is not enabled for your account."))


def _get_project(request, project_id):
    _check_enabled(request.user)
    return get_object_or_404(Project, pk=project_id, owner=request.user)


def _get_session(request, project):
    """session_id in the request, or the project's most recent session."""
    session_id = request.POST.get('session_id') or request.GET.get('session_id')
    if session_id:
        return get_object_or_404(AgentSession, pk=session_id, project=project, user=request.user)
    session = project.agent_sessions.filter(user=request.user).order_by('-created').first()
    if session is None:
        raise BadRequest(_("No agent session; call agent/start first."))
    return session


def _stream_key(session_id):
    return 'agent-stream-%s' % session_id


def _append(session, role, type_, data):
    """Persist one event and push it to the browser-facing redis list.

    max(seq)+1 is not atomic and this is not single-writer: the relay thread
    appends while /cancel, /message and heal_if_stale all append from the request
    path. A collision on the unique (session, seq) surfaces as a ValidationError
    from IdeModel's pre_save full_clean, or an IntegrityError if it slips past --
    either one, inside the relay's blanket except, would end a healthy turn as
    "the agent service is unavailable". So retry rather than surface it.
    """
    content = {'type': type_, 'data': data}
    for attempt in range(3):
        seq = (AgentMessage.objects.filter(session=session)
               .aggregate(Max('seq'))['seq__max'] or 0) + 1
        try:
            with transaction.atomic():
                AgentMessage.objects.create(session=session, seq=seq, role=role,
                                            content=content)
            break
        except (IntegrityError, ValidationError):
            if attempt == 2:
                raise
            logger.info("agent: seq %s collided on session %s, retrying", seq, session.pk)
    event = {'seq': seq, 'role': role, 'type': type_, 'data': data}
    key = _stream_key(session.id)
    redis_client.rpush(key, json.dumps(event))
    redis_client.expire(key, 3600)
    # Keeps heal_if_stale accurate through a long turn without a session .save()
    # on the hot path (auto_now would fight the relay's own writes).
    AgentSession.objects.filter(pk=session.pk).update(last_active=timezone.now())
    return event


def _flag_credential(user_id, message):
    """Remember that this user's key stopped working, so the panel can say so."""
    try:
        AgentCredential.objects.filter(user_id=user_id).update(
            auth_failed_at=timezone.now(), auth_error=(message or '')[:500])
    except Exception:
        logger.exception("agent: could not flag credential for user %s", user_id)


def _clear_credential_flag(user_id):
    """A turn completed, so whatever was wrong with the credential is not."""
    try:
        AgentCredential.objects.filter(
            user_id=user_id, auth_failed_at__isnull=False).update(
                auth_failed_at=None, auth_error='')
    except Exception:
        logger.exception("agent: could not clear credential flag for user %s", user_id)


def _sse(event):
    return 'data: %s\n\n' % json.dumps(event)


def _last_activity(session):
    """When this session last produced anything. Messages are the real signal;
    last_active only moves when the session row itself is saved."""
    latest = AgentMessage.objects.filter(session=session).aggregate(Max('created'))['created__max']
    if latest and session.last_active:
        return max(latest, session.last_active)
    return latest or session.last_active


def _stop_turn(session, status):
    """Tell the agent VM to stop, and retire this turn's number.

    Both the ways a turn ends early -- the user pressing Stop, and a wedged
    session being healed -- have to do this. Healing used to only flip the status,
    so the VM carried on working and the freed session accepted a new message:
    two turns then wrote into the same project at once.
    """
    if settings.AGENT_URL and settings.AGENT_AUTH_HEADER:
        try:
            # Keyed on the AgentSession pk, the same value /turn registered.
            requests.post(_agent_url('cancel'), json={'session_id': session.id},
                          headers=_agent_headers(), timeout=10)
        except requests.RequestException as e:
            logger.warning("agent: cancel failed for session %s: %s", session.id, e)
    session.status = status
    # Retire the turn number too. The agent VM takes a moment to wind down, and
    # its relay must not append to the transcript or reset the status after the
    # user has moved on -- especially when they stopped in order to say something
    # else, which starts the next turn immediately.
    session.turn_count += 1
    session.save(update_fields=['status', 'turn_count'])


def heal_if_stale(session):
    """Release a session wedged in 'running' by a relay that died.

    Emits a terminal error so an already-open browser re-enables its composer,
    rather than only unsticking the next caller. Returns True if it healed.
    """
    if session.status != 'running':
        return False
    last = _last_activity(session)
    if last and (timezone.now() - last).total_seconds() < STALE_TURN_SECONDS:
        return False
    logger.warning("agent: healing stale session %s (last activity %s)", session.id, last)
    _stop_turn(session, 'error')
    _append(session, 'system', 'error', {
        'message': _("The agent stopped responding and the turn was ended. Try again."),
        'kind': 'timeout',
    })
    return True


# ---------------------------------------------------------------------------
# the relay


def _iter_sse(response):
    """Yield parsed JSON payloads from an SSE response body."""
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith('data:'):
            continue
        payload = line[len('data:'):].strip()
        if not payload:
            continue
        try:
            yield json.loads(payload)
        except ValueError:
            logger.warning("agent: unparseable SSE payload: %r", payload[:200])


# The controller reaps an emulator 300s after its last ping, so ping well inside
# that -- a missed one must not be fatal.
EMULATOR_PING_SECONDS = getattr(settings, 'AGENT_EMULATOR_PING_SECONDS', 60)


def _keepalive(uuid, stop):
    """Hold the user's emulator open for as long as the turn runs.

    The only thing pinging the qemu controller is the browser tab, and a phone
    freezes that tab's timers the moment the screen locks. Turns run for minutes,
    so the watch the agent is about to install to gets reaped out from under it:
    the tool then reports "emulator never came up after 20 attempts", which reads
    like the emulator failed to start rather than like it was killed for being
    idle while the agent was busy.

    Pings every configured qemu server: the emulator lives on exactly one of
    them, and the others answer alive=False without side effects.
    """
    while not stop.wait(EMULATOR_PING_SECONDS):
        for server in settings.QEMU_URLS:
            try:
                requests.post('%sqemu/%s/ping' % (server, uuid), timeout=5, verify=False)
            except requests.RequestException as e:
                logger.debug("agent: emulator ping to %s failed: %s", server, e)


def _superseded(session_id, turn):
    """True once a newer turn has started on this session.

    Stopping and immediately sending a new instruction leaves the old relay
    draining a stream the user has already walked away from. Without this check
    its late events land in the new turn's transcript, and its terminal event
    flips the session to idle underneath a turn that is still running --
    re-enabling the composer and letting a third turn start concurrently.
    """
    if turn is None:
        return False
    return not AgentSession.objects.filter(pk=session_id, turn_count=turn).exists()


def _relay(session_id, token, message, emulator, cp_base_url, provider=None, turn=None):
    """Consume the agent VM's SSE stream into AgentMessage rows + redis.

    Runs off-request. Under gunicorn's gevent worker threading is monkeypatched,
    so this is a greenlet; under `manage.py runserver` it is a real thread. Both
    work, which is why this is threading and not gevent.spawn.

    ponytail: an in-process thread dies with the web worker, leaving the session
    'running' with no terminal event, and the browser stream then just sits there.
    Move to a celery task on a dedicated queue if turns need to survive deploys.
    """
    terminal = False
    stop_keepalive = threading.Event()
    if emulator and emulator.get('uuid') and settings.QEMU_URLS:
        threading.Thread(target=_keepalive, name='agent-keepalive-%s' % session_id,
                         daemon=True, args=(emulator['uuid'], stop_keepalive)).start()
    try:
        session = AgentSession.objects.get(pk=session_id)
        payload = {
            # The stable AgentSession pk: what /cancel keys on, and always truthy.
            'session_id': session.id,
            # The SDK's own id, for resume. None on the first turn.
            'sdk_session_id': session.sdk_session_id or None,
            'project_id': session.project_id,
            'cp_token': token,
            'cp_base_url': cp_base_url,
            'emulator': emulator,
            'message': message,
            # Whose quota this turn spends. Contains a plaintext secret, so it is
            # never logged and never echoed back to the browser.
            'provider': provider,
        }
        response = requests.post(_agent_url('turn'), json=payload, headers=_agent_headers(),
                                 stream=True, timeout=TURN_TIMEOUT)
        response.raise_for_status()
        for event in _iter_sse(response):
            if _superseded(session_id, turn):
                logger.info("agent: dropping turn %s of session %s, a newer one started",
                            turn, session_id)
                terminal = True  # the newer turn owns the session's status now
                break
            type_ = event.get('type', 'text')
            role = event.get('role', 'assistant')
            data = event.get('data') or {}
            # The agent tells us its SDK session id so the next turn can resume.
            sdk_session_id = data.get('sdk_session_id')
            if sdk_session_id and session.sdk_session_id != sdk_session_id:
                session.sdk_session_id = sdk_session_id
                session.save(update_fields=['sdk_session_id'])
            if type_ == 'error' and data.get('kind') == 'auth':
                _flag_credential(session.user_id, data.get('message', ''))
            elif type_ == 'done':
                _clear_credential_flag(session.user_id)
            _append(session, role, type_, data)
            # A 'mirror_error' or an assistant-level error is not the end of the turn:
            # the agent explicitly carries on after both.
            if type_ == 'done' or (type_ == 'error' and data.get('kind') in FATAL_ERROR_KINDS):
                terminal = True
                session.status = 'idle' if type_ == 'done' else 'error'
                # update_fields, because this object was read when the turn began:
                # a full save writes back its stale turn_count and undoes the
                # increment a newer turn made, which silently unfences that turn.
                session.save(update_fields=['status'])
                break
    except Exception as exc:
        logger.exception("agent: relay failed for session %s", session_id)
        # Deliberately not str(exc): requests puts the private agent host in the
        # message, and this string is persisted and shown to the user.
        if isinstance(exc, requests.exceptions.ReadTimeout):
            # The turn may well still be running on the agent VM; we just stopped
            # listening. Say that rather than blaming the service.
            message_text = _("The agent went quiet for too long and the turn was "
                             "ended. It may still have been working.")
        else:
            message_text = _("The agent service is unavailable.")
        if _superseded(session_id, turn):
            # A stopped turn's connection dying is not news the user needs, and
            # the session's status belongs to the turn that replaced it.
            terminal = True
        else:
            try:
                session = AgentSession.objects.get(pk=session_id)
                session.status = 'error'
                session.save(update_fields=['status'])
                _append(session, 'system', 'error', {'message': message_text, 'kind': 'relay'})
                terminal = True
            except Exception:
                logger.exception("agent: could not record relay failure for session %s",
                                 session_id)
    finally:
        # The turn is over: stop holding the emulator open, and let the browser's
        # own ping decide its fate from here.
        stop_keepalive.set()
        # The token's work is done -- don't leave it live in redis for the rest
        # of its 30 minute TTL.
        revoke(token)
        if not terminal and not _superseded(session_id, turn):
            # Never leave a browser stream hanging -- unless a newer turn owns the
            # session now, in which case its 'done' is not ours to write.
            try:
                session = AgentSession.objects.get(pk=session_id)
                if session.status == 'running':
                    session.status = 'idle'
                    session.save(update_fields=['status'])
                _append(session, 'system', 'done', {'turn_count': session.turn_count})
            except Exception:
                logger.exception("agent: could not close out session %s", session_id)
        connection.close()


# ---------------------------------------------------------------------------
# browser-facing views


@login_required
@require_POST
@json_view
def agent_start(request, project_id):
    """The project's chat session, created on first use.

    Get-or-create rather than always-create: the panel calls this on every page load,
    and reusing the session is what makes the conversation (and the SDK's resume id)
    survive a reload.
    """
    project = _get_project(request, project_id)
    session = project.agent_sessions.filter(user=request.user).order_by('-created').first()
    if session is None:
        session = AgentSession.objects.create(project=project, user=request.user, status='idle')
    else:
        heal_if_stale(session)
    return {'session_id': session.id, 'status': session.status}


def _emulator_spec(raw):
    """Reduce the browser's emulator blob to a descriptor the agent VM may dial.

    The websocket URL is built here from QEMU_PUBLIC_URL, never taken from the request:
    the agent VM connects to whatever it is handed, so a caller-chosen host would be an
    SSRF primitive aimed at the loop box's own network.
    """
    if not raw:
        return None
    try:
        spec = json.loads(raw)
    except ValueError:
        raise BadRequest(_("Malformed emulator parameter."))
    if not isinstance(spec, dict):
        raise BadRequest(_("Malformed emulator parameter."))
    uuid = str(spec.get('uuid') or '')
    token = str(spec.get('token') or '')
    if not EMULATOR_UUID_RE.match(uuid):
        raise BadRequest(_("Malformed emulator parameter."))
    if not 0 < len(token) <= 128 or not token.isprintable() or any(c.isspace() for c in token):
        raise BadRequest(_("Malformed emulator parameter."))
    if not settings.QEMU_PUBLIC_URL:
        # Nothing off-box can address the emulator; the turn is build-only.
        return None
    base = settings.QEMU_PUBLIC_URL.rstrip('/').replace('https://', 'wss://').replace('http://', 'ws://')
    # Which watch is on screen, so the agent lays out for the size it will be
    # screenshotting. Anything unrecognised is dropped rather than passed on:
    # this string ends up in the model's context, and a bogus one would have it
    # designing for a watch that does not exist.
    platform = str(spec.get('platform') or '')
    return {'uuid': uuid, 'token': token,
            'platform': platform if platform in _VALID_PLATFORMS else '',
            'ws_url': '%s/qemu/%s/ws/phone' % (base, uuid)}


@login_required
@require_POST
@json_view
def agent_message(request, project_id):
    project = _get_project(request, project_id)
    _require_agent_service()
    session = _get_session(request, project)
    heal_if_stale(session)
    if session.status == 'running':
        raise BadRequest(_("The agent is already working. Cancel first."))
    message = request.POST.get('message', '').strip()
    if not message:
        raise BadRequest(_("Empty message."))
    # Optional -- build-only turns work fine without an emulator.
    emulator = _emulator_spec(request.POST.get('emulator'))

    # Everything that can refuse the turn goes first. Marking the session running
    # and spending a daily turn before checking the configuration left the user
    # with the right error message AND a locked composer AND one fewer turn.
    #
    # Not request.build_absolute_uri: ALLOWED_HOSTS is '*', and this is the origin
    # the agent VM sends the scoped token to.
    if not settings.PUBLIC_URL:
        raise InternalServerError(_("PUBLIC_URL is not configured."))
    cp_base_url = settings.PUBLIC_URL.rstrip('/') + '/'

    # Their own provider if they have one, otherwise the free tier. Refusing here
    # beats letting the turn fail on the agent VM with a less obvious message.
    provider = config_for(request.user)
    if provider is None:
        raise InternalServerError(
            _("No model is configured. Add your own provider key in the agent settings."))

    if not consume_turn(request.user):
        raise BadRequest(_("You have reached your daily agent limit. Try again tomorrow."))
    token = mint(request.user, project, session)

    session.status = 'running'
    session.turn_count += 1
    session.save()
    _append(session, 'user', 'text', {'text': message})

    threading.Thread(target=_relay, name='agent-relay-%s' % session.id, daemon=True,
                     args=(session.id, token, message, emulator, cp_base_url, provider,
                           session.turn_count)).start()
    return {'ok': True}


def _event_stream(session_id, since):
    last_seq = since
    key = _stream_key(session_id)
    try:
        # Catch-up straight from the durable rows, then hand over to redis and drop
        # the DB connection — an idle IDE tab must not pin a pooler client (see
        # the same reasoning in ide.api.sse).
        for msg in AgentMessage.objects.filter(session_id=session_id, seq__gt=last_seq).order_by('seq'):
            last_seq = msg.seq
            content = msg.content or {}
            event = {'seq': msg.seq, 'role': msg.role,
                     'type': content.get('type', 'text'), 'data': content.get('data') or {}}
            yield _sse(event)

        # The truth about whether a turn is running, sent after the replay and
        # never persisted. Replaying history means replaying old terminal events:
        # a fatal error from an earlier turn would otherwise leave a reloaded tab
        # convinced nothing is running, with no spinner and no Stop button, while
        # the agent works away and every message it sends comes back "the agent is
        # already working".
        session = AgentSession.objects.filter(pk=session_id).first()
        if session is not None:
            heal_if_stale(session)
            yield _sse({'type': 'sync', 'role': 'system',
                        'data': {'status': session.status}})
        connection.close()

        # One long-lived stream per tab, kept open across turns and heartbeated -- the
        # same posture as ide.api.sse.project_events. Terminal events are streamed and
        # then we keep listening, so the next turn flows down this same connection.
        # ponytail: a 0.5s LRANGE poll per open tab. Move to redis pubsub (as sse.py
        # does) if the tab count ever matters.
        index = 0
        since_heartbeat = 0.0
        while True:
            # The list carries a 1 hour TTL, so a tab left open through a quiet
            # hour comes back to an empty key and a cursor pointing past its end:
            # every event of the next turn would be skipped, and the panel would
            # sit blank until a reload. seq dedupe makes re-reading harmless.
            if redis_client.llen(key) < index:
                index = 0
            batch = redis_client.lrange(key, index, -1)
            index += len(batch)
            if not batch:
                time.sleep(POLL_SECONDS)
                since_heartbeat += POLL_SECONDS
                if since_heartbeat >= HEARTBEAT_SECONDS:
                    since_heartbeat = 0.0
                    # The write is what makes gunicorn notice a vanished client.
                    yield ': keepalive\n\n'
                continue
            since_heartbeat = 0.0
            for raw in batch:
                event = json.loads(raw)
                if event.get('seq', 0) <= last_seq:
                    continue
                last_seq = event['seq']
                yield _sse(event)
    except GeneratorExit:
        pass
    finally:
        connection.close()


@login_required
@require_GET
def agent_stream(request, project_id):
    try:
        project = _get_project(request, project_id)
        session = _get_session(request, project)
    except PermissionDenied:
        return HttpResponse(status=403)
    except BadRequest as e:
        return HttpResponse(str(e), status=400)
    # A browser reconnecting to a session whose relay died gets the terminal
    # event it never received, instead of hanging on "Working...".
    heal_if_stale(session)
    try:
        since = int(request.GET.get('since', 0))
    except ValueError:
        since = 0

    response = StreamingHttpResponse(_event_stream(session.id, since),
                                     content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@login_required
@require_POST
@json_view
def agent_cancel(request, project_id):
    project = _get_project(request, project_id)
    session = _get_session(request, project)
    _stop_turn(session, 'cancelled')
    _append(session, 'system', 'error', {'message': _("Stopped."), 'kind': 'cancelled'})
    return {'ok': True}


# ---------------------------------------------------------------------------
# Model credentials — the user's own provider, or the free tier.
#
# OpenRouter supports OAuth PKCE, so a user connects by clicking a link rather
# than finding and pasting a key: https://openrouter.ai/docs/guides/overview/auth/oauth
#
# Anthropic has no equivalent we can use. Its OAuth flow is bound to Claude Code
# and Claude.ai, there is no way to register a client_id, and borrowing Claude
# Code's would misrepresent this app to the user's account. `claude setup-token`
# and paste stays the honest route there.

# Anthropic PKCE. OFF unless AGENT_ANTHROPIC_OAUTH_CLIENT_ID is set, because the
# only client_id that works here is Claude Code's own: Anthropic has no self-serve
# client registration, so a third-party app cannot obtain one. Borrowing it means
# the consent screen says Claude Code when the app asking is CloudPebble.
#
# That is a deliberate testing shortcut, not a shipping design. Leave the setting
# empty in production and use `claude setup-token` and paste, which the panel
# already walks through. Getting a real client_id means asking Anthropic
# (mcp-review@anthropic.com).
ANTHROPIC_AUTH_URL = 'https://claude.com/cai/oauth/authorize'
ANTHROPIC_TOKEN_URL = 'https://console.anthropic.com/v1/oauth/token'
# The redirect shows the code on screen for the user to copy, which is what makes
# this work on a phone with no CLI.
ANTHROPIC_REDIRECT_URI = 'https://platform.claude.com/oauth/code/callback'
ANTHROPIC_SCOPE = 'user:inference'
ANTHROPIC_PKCE_SESSION_KEY = 'agent_anthropic_verifier'
ANTHROPIC_STATE_SESSION_KEY = 'agent_anthropic_state'

OPENROUTER_AUTH_URL = 'https://openrouter.ai/auth'
OPENROUTER_KEY_EXCHANGE = 'https://openrouter.ai/api/v1/auth/keys'
# The verifier must survive the round trip to OpenRouter and back, but must never
# reach the browser, so it lives in the user's server-side session.
PKCE_SESSION_KEY = 'agent_openrouter_verifier'


def _pkce_pair():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip('=')
    return verifier, challenge


@require_POST
@login_required
@json_view
def agent_openrouter_start(request):
    """Hand back the URL to send the user to, and remember the verifier."""
    _check_enabled(request.user)
    if not settings.PUBLIC_URL:
        raise InternalServerError(_("PUBLIC_URL is not configured."))
    verifier, challenge = _pkce_pair()
    request.session[PKCE_SESSION_KEY] = verifier
    callback = settings.PUBLIC_URL.rstrip('/') + reverse('ide:agent_openrouter_callback')
    url = '%s?%s' % (OPENROUTER_AUTH_URL, urlencode({
        'callback_url': callback,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    }))
    return {'url': url}


@require_POST
@login_required
@json_view
def agent_anthropic_start(request):
    """URL for the user to open. They come back with a code to paste."""
    _check_enabled(request.user)
    client_id = settings.AGENT_ANTHROPIC_OAUTH_CLIENT_ID
    if not client_id:
        raise BadRequest(_("Anthropic sign-in is not enabled here. Use "
                           "`claude setup-token` and paste the token instead."))
    verifier, challenge = _pkce_pair()
    # State must be its own random value of the same shape as the challenge --
    # a truncated copy of the challenge is rejected as an invalid request.
    state = secrets.token_urlsafe(32)
    request.session[ANTHROPIC_PKCE_SESSION_KEY] = verifier
    request.session[ANTHROPIC_STATE_SESSION_KEY] = state
    url = '%s?%s' % (ANTHROPIC_AUTH_URL, urlencode({
        'code': 'true',
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': ANTHROPIC_REDIRECT_URI,
        'scope': ANTHROPIC_SCOPE,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        # The page shows "<code>#<state>", and the state it echoes back must be
        # the one we sent.
        'state': state,
    }))
    return {'url': url}


@require_POST
@login_required
@json_view
def agent_anthropic_finish(request):
    """Exchange the pasted code for a token and store it."""
    _check_enabled(request.user)
    client_id = settings.AGENT_ANTHROPIC_OAUTH_CLIENT_ID
    if not client_id:
        raise BadRequest(_("Anthropic sign-in is not enabled here."))
    verifier = request.session.pop(ANTHROPIC_PKCE_SESSION_KEY, None)
    expected_state = request.session.pop(ANTHROPIC_STATE_SESSION_KEY, None)
    if not verifier:
        raise BadRequest(_("That sign-in attempt expired. Start again."))
    # The callback page shows "code#state"; accept either form.
    pasted = request.POST.get('code', '').strip()
    code, _sep, returned_state = pasted.partition('#')
    code = code.strip()
    if not code:
        raise BadRequest(_("Paste the code from the Anthropic page."))
    if returned_state and expected_state and returned_state.strip() != expected_state:
        raise BadRequest(_("That code came from a different sign-in attempt. "
                           "Start again."))
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': client_id,
        'redirect_uri': ANTHROPIC_REDIRECT_URI,
        'code_verifier': verifier,
    }
    # The authorize step round-trips state, and the exchange is rejected without
    # it. Prefer what the page echoed back over what we stored, so a paste that
    # includes it still works if the session was recycled.
    if returned_state or expected_state:
        payload['state'] = (returned_state or expected_state or '').strip()

    try:
        response = requests.post(ANTHROPIC_TOKEN_URL, json=payload, timeout=30)
    except requests.RequestException as e:
        logger.warning("agent: anthropic token exchange unreachable: %s", e)
        raise BadRequest(_("Could not reach Anthropic to finish signing in."))

    if response.status_code >= 400:
        # Surface what the provider actually said: "may have expired" sent the
        # user round the loop again when the real problem was the request.
        detail = response.text[:300]
        logger.warning("agent: anthropic token exchange %s: %s",
                       response.status_code, detail)
        raise BadRequest(_("Anthropic rejected the sign-in (%(status)s): %(detail)s")
                         % {'status': response.status_code, 'detail': detail})

    token = (response.json() or {}).get('access_token')
    if not token:
        raise BadRequest(_("Anthropic did not return a token."))

    credential = AgentCredential.objects.filter(user=request.user).first()
    if credential is None:
        credential = AgentCredential(user=request.user)
    credential.provider = AgentCredential.PROVIDER_ANTHROPIC
    credential.secret_kind = AgentCredential.KIND_OAUTH
    credential.model = request.POST.get('model', '').strip()[:128]
    credential.set_secret(token)
    credential.save()
    return describe_for_ui(request.user)


@login_required
def agent_openrouter_callback(request):
    """Where OpenRouter sends the user back, with ?code=...

    Exchanges the code for a key server-side and stores it, so the key never
    touches the browser. Renders a tiny page that closes itself.
    """
    code = request.GET.get('code', '')
    verifier = request.session.pop(PKCE_SESSION_KEY, None)
    error = None
    if not code:
        error = _("OpenRouter did not return an authorisation code.")
    elif not verifier:
        error = _("This authorisation link has expired. Start again.")
    else:
        try:
            response = requests.post(OPENROUTER_KEY_EXCHANGE, json={
                'code': code,
                'code_verifier': verifier,
                'code_challenge_method': 'S256',
            }, timeout=30)
            response.raise_for_status()
            key = (response.json() or {}).get('key')
            if not key:
                error = _("OpenRouter did not return a key.")
        except requests.RequestException:
            logger.exception("agent: OpenRouter key exchange failed")
            error = _("Could not reach OpenRouter to finish signing in.")

    if error is None:
        credential = AgentCredential.objects.filter(user=request.user).first()
        if credential is None:
            credential = AgentCredential(user=request.user)
        credential.provider = AgentCredential.PROVIDER_OPENROUTER
        credential.secret_kind = AgentCredential.KIND_API_KEY
        credential.set_secret(key)
        credential.save()

    return render(request, 'ide/agent-oauth-done.html', {'error': error})


@require_GET
@login_required
@json_view
def agent_credentials(request):
    """What the user is currently running on. Never returns the secret."""
    _check_enabled(request.user)
    return describe_for_ui(request.user)


@require_POST
@login_required
@json_view
def agent_credentials_save(request):
    _check_enabled(request.user)
    provider = request.POST.get('provider', '').strip()
    valid = dict(AgentCredential.PROVIDER_CHOICES)
    if provider not in valid:
        raise BadRequest(_("Unknown provider: %s") % provider)

    secret = request.POST.get('secret', '').strip()

    kind = request.POST.get('secret_kind', AgentCredential.KIND_API_KEY)
    if kind not in dict(AgentCredential.KIND_CHOICES):
        raise BadRequest(_("Unknown credential type."))
    # An OAuth token only means anything to the Anthropic path.
    if kind == AgentCredential.KIND_OAUTH and provider != AgentCredential.PROVIDER_ANTHROPIC:
        raise BadRequest(_("OAuth tokens are only supported for Anthropic."))

    # Not get_or_create: IdeModel validates on save, and creating a blank row
    # first fails on the empty provider and secret before they can be filled in.
    credential = AgentCredential.objects.filter(user=request.user).first()

    # Changing only the model must not cost the user their key: the secret is
    # write-only, so the browser cannot send it back, and a blank one here means
    # "keep what is stored". It can only be kept when it still applies -- a
    # different provider, or an API key where an OAuth token is now wanted, has
    # to be re-entered.
    keeping = (secret == '' and credential is not None
               and credential.provider == provider and credential.secret_kind == kind)
    if not secret and not keeping:
        raise BadRequest(_("A key or token is required."))

    if credential is None:
        credential = AgentCredential(user=request.user)
    credential.provider = provider
    credential.secret_kind = kind
    credential.model = request.POST.get('model', '').strip()[:128]
    if secret:
        credential.set_secret(secret)
    credential.save()
    return describe_for_ui(request.user)


@require_POST
@login_required
@json_view
def agent_credentials_delete(request):
    """Drop back to the free tier."""
    _check_enabled(request.user)
    AgentCredential.objects.filter(user=request.user).delete()
    return describe_for_ui(request.user)


# ---------------------------------------------------------------------------
# Project settings — agent token only.
#
# The agent cannot reach save_project_settings, which resolves its project from
# the URL against request.user and would let a token touch any project the user
# owns. This endpoint always writes to request.agent_project — the single
# project the token was minted for — and nothing here can reference another
# project or anything outside it.
#
# Deliberately NOT exposed, because they reach beyond this project:
#   interdependencies                         (link to the user's OTHER projects)
#   github repo settings, publishing          (write to third-party services)
#   owner                                     (ownership transfer)
#
# npm dependencies ARE exposed: they name a package on the public registry, not
# another project, and a watchface that needs @moddable/pebbleproxy cannot be
# built without one.
#
# Partial update: only the fields present in the POST are touched.

_VALID_PLATFORMS = ('aplite', 'basalt', 'chalk', 'diorite', 'emery', 'gabbro', 'flint')
_EMBEDDED_JS_PLATFORMS = {'emery', 'gabbro', 'flint'}

_BOOL_SETTINGS = (
    'app_is_watchface',
    'app_is_hidden',
    'app_is_shown_on_communication',
    'app_modern_multi_js',
)
_TEXT_SETTINGS = (
    'name',
    'app_company_name',
    'app_short_name',
    'app_long_name',
    'app_version_label',
    'app_capabilities',
)


def _as_bool(raw):
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


@csrf_exempt
@require_GET
@agent_token_required
@json_view
def agent_emulator(request, project_id):
    """The user's emulator as it is right now -- agent token only.

    A turn is handed one emulator descriptor when it starts and nothing updates it,
    so rebooting the emulator mid-turn (which CloudPebble itself tells the user to
    do when an install is rejected) left every later install and screenshot dialling
    a dead instance for the rest of the turn: "emulator never came up after 20
    attempts", with no way back. The agent calls this to pick up the live one.

    Same shape and the same rules as _emulator_spec: the websocket URL is built
    here, never taken from the caller.
    """
    preferred = request.GET.get('platform', '')
    order = ([preferred] if preferred in _VALID_PLATFORMS else []) + \
            [p for p in _VALID_PLATFORMS if p != preferred]
    for platform in order:
        raw = redis_client.get('qemu-user-%s-%s' % (request.user.id, platform))
        if not raw:
            continue
        try:
            info = json.loads(raw)
        except ValueError:
            continue
        uuid, token = info.get('uuid'), info.get('token')
        if not uuid or not token or not EMULATOR_UUID_RE.match(str(uuid)):
            continue
        # Registered is not running: the controller reaps, and the row outlives it.
        try:
            alive = requests.post(info['ping_url'], timeout=3,
                                  verify=False).json().get('alive')
        except (requests.RequestException, ValueError, KeyError):
            continue
        if not alive:
            continue
        base = settings.QEMU_PUBLIC_URL.rstrip('/').replace(
            'https://', 'wss://').replace('http://', 'ws://')
        return {'emulator': {'uuid': uuid, 'token': token, 'platform': platform,
                             'ws_url': '%s/qemu/%s/ws/phone' % (base, uuid)}}
    return {'emulator': None}


@csrf_exempt
@require_POST
@agent_token_required
@json_view
def agent_app_settings(request, project_id):
    """Write project settings for the token's project. Never any other project."""
    project = request.agent_project
    changed = {}

    for field in _TEXT_SETTINGS:
        if field in request.POST:
            value = request.POST[field].strip()
            if field == 'name' and not value:
                raise BadRequest(_("Project name cannot be empty."))
            setattr(project, field, value)
            changed[field] = value

    for field in _BOOL_SETTINGS:
        if field in request.POST:
            value = _as_bool(request.POST[field])
            setattr(project, field, value)
            changed[field] = value

    if 'app_platforms' in request.POST:
        raw = request.POST['app_platforms'].strip()
        if raw:
            names = [p.strip() for p in raw.split(',') if p.strip()]
            bad = [p for p in names if p not in _VALID_PLATFORMS]
            if bad:
                raise BadRequest(_("Unknown platform(s): %s") % ', '.join(bad))
            # Same rule save_project_settings enforces.
            if project.has_embeddedjs_files:
                unsupported = set(names) - _EMBEDDED_JS_PLATFORMS
                if unsupported:
                    raise BadRequest(
                        _("Projects with Embedded JS files can only target Emery, Gabbro "
                          "and Flint. Remove: %s") % ', '.join(sorted(unsupported)))
            project.app_platforms = ','.join(names)
        else:
            project.app_platforms = None
        changed['app_platforms'] = project.app_platforms

    if 'app_keys' in request.POST:
        raw = request.POST['app_keys'].strip() or '[]'
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise BadRequest(_("app_keys must be valid JSON."))
        if not isinstance(parsed, (list, dict)):
            raise BadRequest(_("app_keys must be a JSON list or object."))
        project.app_keys = json.dumps(parsed)
        changed['app_keys'] = project.app_keys

    if 'app_uuid' in request.POST:
        value = request.POST['app_uuid'].strip()
        try:
            uuid_module.UUID(value)
        except (ValueError, AttributeError, TypeError):
            raise BadRequest(_("app_uuid must be a valid UUID."))
        project.app_uuid = value
        changed['app_uuid'] = value

    # Resource ids are looked up through project.resources, so a menu icon
    # belonging to another project cannot be selected.
    if 'menu_icon' in request.POST:
        raw = request.POST['menu_icon'].strip()
        old_icon = project.menu_icon
        if raw:
            try:
                icon = project.resources.get(pk=int(raw))
            except (ValueError, ObjectDoesNotExist):
                raise BadRequest(_("No such resource in this project: %s") % raw)
            if old_icon is not None and old_icon.pk != icon.pk:
                old_icon.is_menu_icon = False
                old_icon.save()
            icon.is_menu_icon = True
            icon.save()
            changed['menu_icon'] = icon.pk
        elif old_icon is not None:
            old_icon.is_menu_icon = False
            old_icon.save()
            changed['menu_icon'] = None

    # npm-style packages only. save_project_dependencies also writes
    # interdependencies, which link to the user's OTHER projects -- that half
    # stays out of reach, so this is written here rather than by calling it.
    if 'app_dependencies' in request.POST:
        raw = request.POST['app_dependencies'].strip() or '{}'
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise BadRequest(_("app_dependencies must be valid JSON."))
        if not isinstance(parsed, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
            raise BadRequest(_("app_dependencies must be a JSON object of name -> version."))
        try:
            project.set_dependencies(parsed)
        except (IntegrityError, ValueError) as e:
            raise BadRequest(str(e))
        changed['app_dependencies'] = parsed

    if not changed:
        raise BadRequest(_("Nothing to change."))

    try:
        project.save()
    except IntegrityError as e:
        raise BadRequest(str(e))
    return {'ok': True, 'changed': changed}


# ---------------------------------------------------------------------------
# SessionStore mirror — agent token only, no session cookie, no CSRF.
#
# Wire format, matching cloudpebble-agent/session_store.py:
#   POST {project_key, subpath, entries: [...]}  -> 204
#   GET  ?subpath=...                            -> {entries: [...]} | 404
# Stored as JSONL, one json.dumps(entry) per line, appended.


@csrf_exempt
@agent_token_required
def agent_transcript(request, sdk_session_id):
    if request.method == 'POST':
        return _transcript_post(request, sdk_session_id)
    if request.method == 'GET':
        return _transcript_get(request, sdk_session_id)
    return HttpResponse(status=405)


def _find_transcript(request, sdk_session_id, subpath):
    """An existing transcript is only visible to the session it belongs to — the
    sdk_session_id is caller-supplied and is not itself a secret."""
    transcript = AgentTranscript.objects.filter(sdk_session_id=sdk_session_id,
                                                subpath=subpath).first()
    if transcript is None:
        return None
    if transcript.session_id != request.agent_session.id:
        raise PermissionDenied(_("Agent token is not valid for this transcript."))
    return transcript


def _transcript_get(request, sdk_session_id):
    subpath = request.GET.get('subpath', '')[:128]
    transcript = _find_transcript(request, sdk_session_id, subpath)
    if transcript is None:
        return HttpResponseNotFound()
    entries = []
    for line in bytes(transcript.data or b'').splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            logger.warning("agent: unparseable transcript line for %s", sdk_session_id)
    return HttpResponse(json.dumps({'entries': entries}), content_type='application/json')


def _transcript_post(request, sdk_session_id):
    try:
        body = json.loads(request.body)
        entries = body['entries']
        subpath = str(body.get('subpath') or '')[:128]
    except (ValueError, KeyError, TypeError):
        return HttpResponse('expected {entries: [...]}', status=400)
    if not isinstance(entries, list):
        return HttpResponse('expected {entries: [...]}', status=400)

    transcript = _find_transcript(request, sdk_session_id, subpath)
    if transcript is None:
        session = request.agent_session
        transcript = AgentTranscript(sdk_session_id=sdk_session_id, subpath=subpath,
                                     session=session, data=b'')
        # First mirror is how we learn the SDK's session id, which is what the
        # next turn resumes from.
        if not subpath and not session.sdk_session_id:
            session.sdk_session_id = sdk_session_id
            session.save(update_fields=['sdk_session_id'])

    existing = bytes(transcript.data or b'')
    addition = b''.join(json.dumps(e).encode('utf-8') + b'\n' for e in entries)
    # Read-modify-write of the whole blob, so bound it: the SDK surfaces the refusal as
    # a mirror_error rather than silently losing resume.
    if len(existing) + len(addition) > AgentTranscript.MAX_BYTES:
        logger.error("agent: transcript %s over %d bytes, refusing the mirror",
                     sdk_session_id, AgentTranscript.MAX_BYTES)
        return HttpResponse('transcript too large', status=413)
    transcript.data = existing + addition
    transcript.save()
    return HttpResponse(status=204)
