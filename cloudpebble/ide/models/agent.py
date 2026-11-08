from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from ide.models.meta import IdeModel
from ide.utils.crypto import decrypt_value, encrypt_value
from ide.models.project import Project

__author__ = 'ericmigi'


class AgentSession(IdeModel):
    """ One AI agent conversation about one project. """

    STATUS_IDLE = 'idle'
    STATUS_RUNNING = 'running'
    STATUS_ERROR = 'error'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_IDLE, _('Idle')),
        (STATUS_RUNNING, _('Running')),
        (STATUS_ERROR, _('Error')),
        (STATUS_CANCELLED, _('Cancelled')),
    )

    project = models.ForeignKey(Project, related_name='agent_sessions', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='agent_sessions', on_delete=models.CASCADE)
    # The Agent SDK's own session id, used for resume. Empty until the first turn completes.
    sdk_session_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_IDLE)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    last_active = models.DateTimeField(auto_now=True)
    turn_count = models.IntegerField(default=0)

    class Meta(IdeModel.Meta):
        db_table = 'cloudpebble_agent_sessions'


class AgentMessage(IdeModel):
    """ A rendered chat event. This is what the chat panel displays; it is not the
    SDK transcript (see AgentTranscript). """

    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_TOOL = 'tool'
    ROLE_SYSTEM = 'system'
    ROLE_CHOICES = (
        (ROLE_USER, _('User')),
        (ROLE_ASSISTANT, _('Assistant')),
        (ROLE_TOOL, _('Tool')),
        (ROLE_SYSTEM, _('System')),
    )

    session = models.ForeignKey(AgentSession, related_name='messages', on_delete=models.CASCADE)
    seq = models.IntegerField()
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    class Meta(IdeModel.Meta):
        db_table = 'cloudpebble_agent_messages'
        # Also the index that serves ?since=<seq>.
        unique_together = (('session', 'seq'),)
        ordering = ['seq']


class AgentTranscript(IdeModel):
    """ SessionStore backing for the Agent SDK: append-only JSONL, one entry per line.

    One row per (sdk_session_id, subpath). subpath is empty for the main transcript and
    set for subagent transcripts -- see claude_agent_sdk.types.SessionKey.
    """

    # Beyond this the mirror is refused: a 12-turn watchface transcript is orders of
    # magnitude smaller, and the row is read-modify-written on every append.
    MAX_BYTES = 8 * 1024 * 1024

    sdk_session_id = models.CharField(max_length=64, db_index=True)
    subpath = models.CharField(max_length=128, blank=True, default='')
    session = models.ForeignKey(AgentSession, related_name='transcripts', on_delete=models.CASCADE)
    data = models.BinaryField(default=b'')

    class Meta(IdeModel.Meta):
        db_table = 'cloudpebble_agent_transcripts'
        unique_together = (('sdk_session_id', 'subpath'),)


class AgentCredential(IdeModel):
    """A user's own model provider, so they can spend their own quota.

    Supported, per Anthropic's own guidance that Agent SDK usage in third-party
    applications may authenticate with a user's Claude subscription:
    https://support.claude.com/en/articles/15036540

    The secret is Fernet-encrypted with the same helper the project env-var
    feature uses, is never returned to the browser, and is decrypted only when a
    turn is dispatched.
    """

    PROVIDER_ANTHROPIC = 'anthropic'
    PROVIDER_OPENROUTER = 'openrouter'
    # No OpenAI entry: OpenAI serves no Anthropic-format /v1/messages endpoint,
    # so the Agent SDK cannot drive it. OpenAI models go through OpenRouter.
    PROVIDER_CHOICES = (
        (PROVIDER_ANTHROPIC, 'Anthropic'),
        (PROVIDER_OPENROUTER, 'OpenRouter'),
    )

    # An Anthropic secret is either an API key or an OAuth token from
    # `claude setup-token`; the SDK takes both, on different env vars.
    KIND_API_KEY = 'api_key'
    KIND_OAUTH = 'oauth'
    KIND_CHOICES = ((KIND_API_KEY, 'API key'), (KIND_OAUTH, 'OAuth token'))

    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='agent_credential',
                                on_delete=models.CASCADE)
    provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES)
    secret_kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_API_KEY)
    encrypted_secret = models.TextField()
    # Free-form so a user can name any model their provider serves, including
    # OpenRouter's "vendor/model" strings, without waiting on us to allowlist it.
    model = models.CharField(max_length=128, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    # Set when a turn fails authentication, cleared when one succeeds. Tokens
    # expire and keys get rotated, so the panel has to be able to say so instead
    # of failing the same way forever.
    auth_failed_at = models.DateTimeField(null=True, blank=True)
    auth_error = models.TextField(blank=True)

    class Meta(IdeModel.Meta):
        db_table = 'cloudpebble_agent_credentials'

    def __unicode__(self):
        return u"%s/%s" % (self.user_id, self.provider)

    @property
    def masked(self):
        """Enough to recognise which key is stored, useless if intercepted."""
        try:
            secret = decrypt_value(self.encrypted_secret)
        except Exception:
            return '(unreadable)'
        return '%s...%s' % (secret[:7], secret[-4:]) if len(secret) > 15 else '******'

    def secret(self):
        return decrypt_value(self.encrypted_secret)

    def set_secret(self, plaintext):
        self.encrypted_secret = encrypt_value(plaintext)
        # A new secret deserves a clean slate.
        self.auth_failed_at = None
        self.auth_error = ''

    @property
    def needs_reauth(self):
        return self.auth_failed_at is not None
