"""One turn of the Claude Agent SDK loop.

Stateless: the transcript is hydrated from CloudPebble at the start of the turn and
mirrored back as it grows. Nothing survives on this box except the baked skill
workspace, which is read-only.

The agent has no filesystem and no shell -- `tools=['Skill']` removes every other
built-in from its context, and allowed_tools is our eight MCP tools.
"""

import logging
import os
import re
import tempfile
from contextlib import aclosing

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage,
                              SystemMessage, TextBlock, ToolUseBlock, query)

import project_state
import tools as cp_tools
import vision
from session_store import CloudPebbleSessionStore

logger = logging.getLogger(__name__)

WORKSPACE = os.environ.get('AGENT_WORKSPACE', '/opt/agent-workspace')
MODEL = os.environ.get('AGENT_MODEL', 'claude-sonnet-5')

# Non-Anthropic models via an Anthropic-format gateway. OpenRouter serves one at
# https://openrouter.ai/api (its /v1/messages speaks the Messages API), so the
# bundled Claude Code CLI can drive e.g. moonshotai/kimi-k3 unchanged. Leave
# unset for first-party Anthropic auth (subscription or API key).
#   AGENT_API_BASE=https://openrouter.ai/api
#   AGENT_API_KEY=sk-or-v1-...
API_BASE = os.environ.get('AGENT_API_BASE', '')
API_KEY = os.environ.get('AGENT_API_KEY', '')

# Claude Code caps a single response at 32k output tokens by default. Models that
# write a whole watchface in one go blow through that -- deepseek-v4-flash died
# with "Claude's response exceeded the 32000 output token maximum" after 23
# minutes of work. Raise it, but keep it configurable: a provider that cannot
# serve the larger value will reject the request outright.
MAX_OUTPUT_TOKENS = os.environ.get('AGENT_MAX_OUTPUT_TOKENS', '64000')
# Steps per turn. A watchface is write -> build -> install -> screenshot -> look
# -> fix, several times over, and an unfamiliar runtime costs a handful more:
# a real turn spent its whole 30-step budget working out one import and ended
# mid-experiment. Cheap to raise, expensive to hit.
MAX_TURNS = int(os.environ.get('AGENT_MAX_TURNS', '75'))
SKILLS = os.environ.get('AGENT_SKILLS', 'all')

# Belt and braces: `tools` already removes these from the model's context.
BANNED_TOOLS = ['Bash', 'BashOutput', 'KillShell', 'Read', 'Write', 'Edit', 'MultiEdit',
                'NotebookEdit', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'Task']

# Appended to Claude Code's own preset prompt, so everything the CLI relies on
# stays intact.
#
# Screenshots are the whole point of this loop: the user is watching a chat panel
# that renders every one, and a watchface is a visual artifact -- a turn that ends
# in prose is asking them to take the result on faith. Models are frugal with
# screenshots by default (each one is another tool round-trip), so this says
# plainly that they are cheap here and that the last word is an image.
SYSTEM_PROMPT_APPEND = """
## Where you are

You are inside CloudPebble, a browser IDE for Pebble smartwatch apps, working on
ONE project for a user who is watching a chat panel next to their editor. Most of
them cannot write code and are describing what they want in plain language.

You have no filesystem, no shell and no network of your own. Every action you can
take is one of the tools below. Do not reach for Bash, Read, Write, Edit, Glob,
Grep, WebFetch, WebSearch or Task -- they are not here, and guessing at them
wastes a step. There is no `run` skill and no way to read a file by naming it to
the Skill tool.

## Everything you can do

Project state
- `list_files()` -- the whole live state: settings, target platforms and their
  screen sizes, source files, resources, and which watch the emulator is running.
  The same block is appended to every message you receive, so you usually already
  have it; call this after you change settings or when in doubt.

Code
- `read_file(path)` / `write_file(path, content)` / `delete_file(path)` -- source
  files, addressed by project path (`src/c/main.c`, `src/pkjs/index.js`,
  `src/embeddedjs/main.js`). Always write the whole file.
- `write_binary_file(path, content_base64)` -- Alloy assets under
  `src/embeddedjs` (.png, .pdc, .ttf).

Resources (images, fonts, blobs the app loads by resource id)
- `write_resource(file_name, kind, content_base64, resource_ids)` -- kinds are
  png, png-trans, bitmap, pbi, font, raw. Replacing keeps the existing ids, so
  new artwork stays hooked up to the code that draws it.
- `delete_resource(file_name)`

Settings -- all of these are settings, not files. There is no package.json and no
wscript in this IDE; do not go looking for them, and do not ask the user to change
something you can change yourself.
- `set_app_settings(...)`: `app_is_watchface` (REQUIRED true for a watchface, or
  it installs as an app and never appears as a face), `app_platforms`, `app_uuid`,
  `app_keys` (AppMessage keys), `app_capabilities` (location, health,
  configurable), `app_dependencies` (npm packages, e.g.
  {"@moddable/pebbleproxy": "^0.1.3"}), `app_long_name`, `app_short_name`,
  `app_company_name`, `app_version_label`, `menu_icon`, `app_is_hidden`,
  `app_is_shown_on_communication`, `app_modern_multi_js`, `name`.
  Only the fields you pass change.

Build and run
- `build()` -- compiles on the CloudPebble build farm, returns the full log. A
  failed compile is a normal result: read the log and fix the code.
- `install()` -- installs the last successful build into the emulator.
- `screenshot()` -- captures the emulator screen.
- `press(button, hold_ms)` -- up, select, down, back, or shake. This is how you
  drive an app: open a menu, scroll a list, play a turn of a game, come back with
  back. Screenshot after each press to see what it did. A watchface has no
  buttons at all, so shake is the only input it can take.
- `logs(seconds)` -- drains app logs from the watch and console.log from the
  phone-side JS.

You cannot touch the screen. Emery and gabbro have touchscreens, but touch
reaches the emulator over VNC rather than the control channel these tools use.
Say so if an app needs it.

Documentation
- `read_reference(name)` -- the skill's own guides and templates, e.g.
  `reference/alloy-guide.md`, `reference/watchapp-guide.md`,
  `reference/pebble-api-reference.md`, `templates/animated-watchface.c`. Call it
  with no name to list everything available. Read the guide BEFORE guessing at an
  API in a runtime you do not know -- one turn once spent its entire step budget
  discovering by trial what the Alloy guide says in a sentence.
- `Skill('pebble-watchface')` -- the watchface/watchapp workflow. Use
  `read_reference` for its reference files; the Skill tool cannot read them.

## The emulator is not yours

It runs in the user's browser tab, not on your machine. You cannot start it, stop
it or reboot it. If a tool tells you there is no emulator, or that the emulator
rejected an install, that is a fact about their browser and NOT a fault in your
code: say so and carry on with what does not need it. Never start deleting
working features to bisect an emulator problem. The panel offers them a button to
open or restart it, and they will tell you when it is back.

## Screenshots

You are building something the user looks at, in a chat panel that displays every
screenshot you take. Screenshots are the only evidence either of you has that the
app actually works. They are cheap -- take more of them than feels necessary.

- After every `install()`, call `screenshot()`. No exceptions.
- Screenshot again after each visual change, so the user can see the difference
  rather than read about it.
- For anything animated or time-driven, take several spaced out, and say what
  changed between them.
- ALWAYS finish with a fresh `screenshot()` of the final, working result -- taken
  after the last build and install, not reused from earlier. Then describe what
  it shows. A turn that ends without one is incomplete, even if everything built.
- An interactive app is not verified until you have driven it: `press()` through
  the flow the user described -- open it, scroll it, play it -- screenshotting as
  you go. "It builds" is not "it works".
- One frame cannot show an animation. If you claim something moves, prove it:
  several screenshots spaced out, and say what changed between them. Asked to do
  this once, a turn discovered the animation it had just reported working was not
  running at all.
- Never describe a screen you did not see.

## Watchface or app

`app_is_watchface` decides where the thing lives: true replaces the user's clock,
false puts it in the app menu they open. Set it deliberately, and set it AGAIN
whenever the user corrects you about what they are building -- rewriting the code
as an app while leaving the flag true ships something that still takes over their
watchface.

## Finishing

The user cannot read code. End with what changed in their terms, what it looks
like on screen, and anything you could not do and why. Do not degrade the app to
make a screenshot look better -- ship what they would actually use.
"""

USAGE_LIMIT_HINTS = ('usage limit', 'rate limit', 'quota')

# A credential that has expired, been revoked or was mistyped. Distinguished from
# a usage limit because the user has to act: re-authenticate rather than wait.
AUTH_HINTS = ('authentication_error', 'authentication_failed', 'failed to authenticate',
              'invalid api key', 'invalid_api_key', 'invalid x-api-key',
              'unauthorized', 'not authenticated', 'expired token', 'token expired',
              'invalid bearer', 'oauth token', 'user not found',
              '401', '403 forbidden', 'permission_error')


# One config dir per SESSION, not per turn.
#
# This used to be tempfile.mkdtemp() per turn, deleted afterwards. That broke
# prompt caching on every provider that caches by prefix rather than by explicit
# cache_control breakpoints: DeepSeek's docs are explicit that only requests with
# identical prefixes from the 0th token hit, and that "a changing timestamp,
# request ID, or user-specific line at the top can destroy useful prefix reuse".
# A fresh random path each turn is exactly that. It also threw away the CLI's
# local session state, forcing a full rebuild every turn.
#
# Isolation is unchanged: a session belongs to one user and one project, so a
# per-session directory is no more shared than a per-turn one was.
CONFIG_ROOT = os.environ.get('AGENT_CONFIG_ROOT', '/tmp/agent-sessions')


def _session_config_dir(session_key):
    safe = re.sub(r'[^A-Za-z0-9_-]', '_', str(session_key))[:64]
    path = os.path.join(CONFIG_ROOT, 'session-%s' % safe)
    os.makedirs(path, exist_ok=True)
    return path


def _subprocess_env(config_dir, provider=None):
    """Environment for the CLI subprocess, for this turn's credentials.

    A per-request provider means one user's key never leaks into another's turn:
    the environment is built fresh each time and nothing is read from the
    container's own credentials unless no provider was supplied.
    """
    env = {'CLAUDE_CONFIG_DIR': config_dir,
           'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1'}
    if MAX_OUTPUT_TOKENS:
        env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(MAX_OUTPUT_TOKENS)

    base = (provider or {}).get('api_base') if provider else API_BASE
    key = (provider or {}).get('api_key') if provider else API_KEY
    kind = (provider or {}).get('secret_kind', 'api_key') if provider else 'api_key'

    # Start from a clean slate every turn so a previous configuration cannot
    # bleed through: whichever of these is unset must be explicitly empty.
    env['ANTHROPIC_BASE_URL'] = base or ''
    env['ANTHROPIC_AUTH_TOKEN'] = ''
    env['ANTHROPIC_API_KEY'] = ''
    env['CLAUDE_CODE_OAUTH_TOKEN'] = ''

    if base:
        # Third-party gateway: bearer auth only. A subscription OAuth token must
        # never be sent to someone else's endpoint.
        env['ANTHROPIC_AUTH_TOKEN'] = key or ''
    elif kind == 'oauth':
        # First-party Anthropic on the user's own Claude plan.
        env['CLAUDE_CODE_OAUTH_TOKEN'] = key or ''
    elif key:
        env['ANTHROPIC_API_KEY'] = key
    else:
        # No per-turn credential: fall back to whatever the container holds.
        env.pop('CLAUDE_CODE_OAUTH_TOKEN')
        env.pop('ANTHROPIC_API_KEY')
    return env


def _kind(text):
    low = (text or '').lower()
    # Order matters: a quota message often mentions 429 alongside auth-ish words,
    # and telling a user to re-authenticate when they merely ran out is worse
    # than telling them to wait.
    if any(h in low for h in USAGE_LIMIT_HINTS):
        return 'usage_limit'
    if any(h in low for h in AUTH_HINTS):
        return 'auth'
    return 'error'


def _state_suffix(ctx, emulator):
    """The project's live state, appended to the user's message.

    Fetched per turn: the agent otherwise starts blind and guesses at the target
    platform, the screen size and whether the project is even flagged as a
    watchface. A failure here is not worth losing the turn over -- the tools can
    still answer all of it -- so it degrades to nothing.
    """
    try:
        info = ctx.cp.info()
    except Exception:
        logger.warning('could not read project state for the turn', exc_info=True)
        return ''
    block = project_state.render(info, emulator)
    return ('\n\n' + block) if block else ''


async def run_turn(*, project_id, cp_token, cp_base_url, message, emulator=None,
                   sdk_session_id=None, session_key=None, provider=None, cancel=None):
    """Yield SSE envelope dicts: {seq, role, type, data}."""
    ctx = cp_tools.Context(cp_base_url, cp_token, project_id, emulator)
    if provider:
        # Whether this turn's model can see, and who looks for it when it cannot.
        ctx.model_vision = bool(provider.get('model_vision', True))
        ctx.vision_config = provider.get('vision')
    config_dir = _session_config_dir(session_key or project_id)

    options = ClaudeAgentOptions(
        resume=sdk_session_id or None,
        system_prompt={'type': 'preset', 'preset': 'claude_code',
                       'append': SYSTEM_PROMPT_APPEND},
        session_store=CloudPebbleSessionStore(cp_base_url, cp_token),
        cwd=WORKSPACE,
        setting_sources=['project'],
        skills=SKILLS if SKILLS == 'all' else [s for s in SKILLS.split(',') if s],
        tools=['Skill'],
        allowed_tools=list(cp_tools.ALLOWED_TOOLS),
        disallowed_tools=BANNED_TOOLS,
        permission_mode='dontAsk',
        mcp_servers={cp_tools.SERVER_NAME: cp_tools.build_server(ctx)},
        strict_mcp_config=True,
        max_turns=MAX_TURNS,
        model=(provider or {}).get('model') or MODEL,
        env=_subprocess_env(config_dir, provider),
        stderr=lambda line: logger.debug('cli: %s', line),
    )

    state = {'seq': 0}

    def ev(role, type_, data):
        state['seq'] += 1
        return {'seq': state['seq'], 'role': role, 'type': type_, 'data': data}

    def drain():
        out, ctx.events = ctx.events, []
        return [ev(e['role'], e['type'], e['data']) for e in out]

    session_id, turn_count = sdk_session_id, 0
    usage = {}
    # What has already been said to the user, so the same failure is not reported
    # twice in two different vocabularies.
    reported = set()
    prompt = message + _state_suffix(ctx, emulator)
    try:
        async with aclosing(query(prompt=prompt, options=options)) as stream:
            async for msg in stream:
                for e in drain():
                    yield e

                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            yield ev('assistant', 'text', {'text': block.text})
                        elif isinstance(block, ToolUseBlock):
                            name = block.name.split('__')[-1]
                            yield ev('tool', 'tool_use', {'tool': name, 'args': block.input})
                    if msg.error:
                        yield ev('system', 'error', {'message': str(msg.error),
                                                     'kind': _kind(str(msg.error))})
                elif isinstance(msg, SystemMessage) and msg.subtype == 'mirror_error':
                    # Non-fatal, but resume will silently lose these entries.
                    logger.error('transcript mirror failed: %s', getattr(msg, 'error', msg.data))
                    yield ev('system', 'error', {'message': 'transcript mirror failed',
                                                 'kind': 'mirror_error'})
                elif isinstance(msg, ResultMessage):
                    session_id, turn_count = msg.session_id, msg.num_turns
                    # Token accounting, for comparing models and for cost caps.
                    raw = getattr(msg, 'usage', None) or {}
                    usage = {
                        'input_tokens': raw.get('input_tokens'),
                        'output_tokens': raw.get('output_tokens'),
                        'cache_read_input_tokens': raw.get('cache_read_input_tokens'),
                        'cache_creation_input_tokens': raw.get('cache_creation_input_tokens'),
                        'total_cost_usd': getattr(msg, 'total_cost_usd', None),
                        'duration_ms': getattr(msg, 'duration_ms', None),
                        # The model and endpoint THIS turn ran on, not the
                        # container's defaults. Those defaults are whatever the
                        # last bench left behind, so reporting them made a turn on
                        # the user's own Claude plan read as 'deepseek-v4-flash'
                        # against api.deepseek.com -- which is exactly the sort of
                        # thing you go looking at when a screenshot seems ignored.
                        'model': (provider or {}).get('model') or MODEL,
                        # Record the whole configuration, not just the main model:
                        # a bench result is meaningless without knowing which eye
                        # the agent was using and whether it could see at all.
                        'api_base': (provider.get('api_base') or 'anthropic') if provider
                                    else (API_BASE or 'anthropic'),
                        'model_vision': ctx.model_vision,
                        'vision_model': ((ctx.vision_config or {}).get('model')
                                         if vision.configured(ctx.vision_config) else None),
                        'provider': (provider or {}).get('provider', 'container'),
                        'max_output_tokens': MAX_OUTPUT_TOKENS,
                        'vision_calls': ctx.vision_calls,
                        'vision_cost_usd': round(ctx.vision_cost_usd, 6),
                    }
                    if msg.is_error:
                        text = msg.result or msg.subtype
                        if msg.subtype == 'error_max_turns':
                            reported.add('max_turns')
                            # The raw subtype is a machine token, and a user shown
                            # "error_max_turns" has no idea their work survived.
                            # It did: the transcript is mirrored and the next
                            # message resumes from where this stopped.
                            text = ('I hit the step limit for this turn. Everything '
                                    'so far is saved -- send "continue" and I will '
                                    'carry on from here.')
                        yield ev('system', 'error', {'message': text, 'kind': _kind(text)})

                if cancel is not None and cancel.is_set():
                    yield ev('system', 'error', {'message': 'cancelled', 'kind': 'cancelled'})
                    break

        for e in drain():
            yield e
    except Exception as e:
        logger.exception('turn failed')
        # The SDK raises after the result message it already described, so a step
        # limit was reported in the user's own words a moment ago: saying
        # "Reached maximum number of turns (75)" straight after it is noise.
        if not ('max_turns' in reported and 'maximum number of turns' in str(e)):
            yield ev('system', 'error', {'message': str(e), 'kind': _kind(str(e))})
    finally:
        # Deliberately NOT removed: the directory is per session and holds the
        # CLI's own transcript, which the next turn resumes from. Deleting it
        # forces a full rebuild and a cold prompt cache. Sessions are cleaned up
        # when the container recycles.
        pass

    yield ev('system', 'done', {'turn_count': turn_count, 'sdk_session_id': session_id,
                                'usage': usage})
