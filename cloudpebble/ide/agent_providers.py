"""Decide which model a turn runs on, and with whose quota.

Four routes, in the order they are offered to the user:

  anthropic   their Claude subscription or API key. Agent SDK native, so skills,
              subagents and vision all work exactly as designed. Authenticating a
              third-party app with a user's Claude plan is supported:
              https://support.claude.com/en/articles/15036540
              The secret is either an API key or an OAuth token from
              `claude setup-token`; the SDK reads them from different variables.
  openrouter  their OpenRouter key plus any model string that service serves.
              This is also the route to OpenAI models (openai/gpt-5.2) and to
              anything else with a published model id.
  free        our keys, a cheap model, and a vision describer standing in for the
              model's missing eyes. This is what a signed-out user gets.

Signing in with an OpenAI account is deliberately absent. OpenAI serves no
Anthropic-format /v1/messages endpoint -- api.openai.com/anthropic/v1/messages
and /v1/messages both 404 -- so the Claude Agent SDK cannot drive it, and the
Codex OAuth flow that backs OpenClaw belongs to a different harness. OpenAI
models are reachable today through OpenRouter; supporting an OpenAI *subscription*
would mean running a translating gateway or adding a second harness.

The free tier is deliberately a text-only model plus a describer rather than a
weak vision model: a model that cannot see is told so and behaves honestly,
whereas a model handed an image it cannot read invents a description and then
edits code against it.
"""
from django.conf import settings
from django.utils.translation import gettext as _

from ide.models.agent import AgentCredential

# Sensible defaults per provider. A user may name any model their provider
# serves; these only fill in when they do not.
DEFAULT_MODELS = {
    AgentCredential.PROVIDER_ANTHROPIC: 'claude-sonnet-5',
    AgentCredential.PROVIDER_OPENROUTER: 'anthropic/claude-sonnet-5',
}

# Anthropic-format /v1/messages endpoints. Empty means first-party Anthropic.
API_BASES = {
    AgentCredential.PROVIDER_ANTHROPIC: '',
    AgentCredential.PROVIDER_OPENROUTER: 'https://openrouter.ai/api',
}

# Providers whose models can read an image directly. Everything else gets the
# describer, which is why the free tier still verifies its own work.
VISION_CAPABLE = {
    AgentCredential.PROVIDER_ANTHROPIC: True,
    # OpenRouter serves both kinds, and the user picks the model. Assume it can
    # see; if it cannot, the SDK errors on the image block rather than silently
    # pretending, and they can switch models.
    AgentCredential.PROVIDER_OPENROUTER: True,
}


def free_tier_config():
    """Our keys, our bill. Everything comes from settings so no secret is here."""
    if not settings.AGENT_FREE_API_KEY:
        return None
    return {
        'provider': 'free',
        'model': settings.AGENT_FREE_MODEL,
        'api_base': settings.AGENT_FREE_API_BASE,
        'api_key': settings.AGENT_FREE_API_KEY,
        'secret_kind': AgentCredential.KIND_API_KEY,
        'model_vision': False,
        'vision': {
            'api_base': settings.AGENT_VISION_API_BASE,
            'api_key': settings.AGENT_VISION_API_KEY,
            'model': settings.AGENT_VISION_MODEL,
        },
    }


def config_for(user):
    """The provider config for this user's next turn, or None if unavailable.

    Their own credential wins; otherwise the free tier. Returns plaintext
    secrets, so the result goes straight into the turn payload and is never
    logged, persisted or echoed back to the browser.
    """
    credential = AgentCredential.objects.filter(user=user).first()
    if credential is None:
        return free_tier_config()

    provider = credential.provider
    return {
        'provider': provider,
        'model': credential.model or DEFAULT_MODELS.get(provider, ''),
        'api_base': API_BASES.get(provider, ''),
        'api_key': credential.secret(),
        'secret_kind': credential.secret_kind,
        'model_vision': VISION_CAPABLE.get(provider, True),
        # A user on their own key still gets the describer configured, so a
        # text-only model of their choosing keeps working.
        'vision': {
            'api_base': settings.AGENT_VISION_API_BASE,
            'api_key': settings.AGENT_VISION_API_KEY,
            'model': settings.AGENT_VISION_MODEL,
        },
    }


def describe_for_ui(user):
    """What the settings panel shows. Never includes the secret itself."""
    # Whether the panel can offer browser sign-in for Anthropic, or has to fall
    # back to telling the user to run `claude setup-token`.
    anthropic_oauth = bool(getattr(settings, 'AGENT_ANTHROPIC_OAUTH_CLIENT_ID', ''))
    credential = AgentCredential.objects.filter(user=user).first()
    if credential is None:
        free = free_tier_config()
        return {
            'provider': 'free',
            'configured': False,
            'model': free['model'] if free else None,
            'available': free is not None,
            'description': _("Using the free shared model. Sign in with your own "
                             "provider for better results and higher limits."),
            'anthropic_oauth': anthropic_oauth,
        }
    if credential.needs_reauth:
        description = _("Your %s credentials stopped working. Enter a new key or "
                        "token to carry on.") % credential.get_provider_display()
    else:
        description = _("Using your own %s credentials.") % credential.get_provider_display()
    return {
        'provider': credential.provider,
        'configured': True,
        'secret_kind': credential.secret_kind,
        'masked_secret': credential.masked,
        'model': credential.model or DEFAULT_MODELS.get(credential.provider, ''),
        'available': True,
        'anthropic_oauth': anthropic_oauth,
        'needs_reauth': credential.needs_reauth,
        'auth_error': credential.auth_error or '',
        'description': description,
    }
