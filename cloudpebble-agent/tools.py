"""In-process MCP server: the only actions the agent can take.

No filesystem, no shell. Every tool is an HTTPS call to CloudPebble or a frame on
the emulator websocket. Tools also push rendered events onto ctx.events, which
agent_loop drains into the SSE stream the chat panel reads.
"""

import asyncio
import base64
import difflib
import json
import logging
import os
from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

# Vision is not universal: several strong tool-calling models on OpenRouter are
# text-only, and handing them an image block means they "verify" a screenshot
# they never saw. Set AGENT_MODEL_VISION=0 for those.
MODEL_HAS_VISION = os.environ.get('AGENT_MODEL_VISION', '1') not in ('0', 'false', 'no')

import emulator as emu
import project_state
import vision
from cloudpebble_client import CloudPebbleClient, CloudPebbleError

logger = logging.getLogger(__name__)

SERVER_NAME = 'cloudpebble'
# Every tool the server exposes must be listed here: ALLOWED_TOOLS drives
# permission_mode='dontAsk', which denies anything absent. Adding a @tool without
# adding it here means the model sees the tool, calls it, and gets denied.
TOOL_NAMES = ['list_files', 'set_app_settings', 'read_file', 'write_file',
              'delete_file', 'write_binary_file', 'write_resource', 'delete_resource',
              'read_reference', 'build', 'install', 'press', 'screenshot', 'logs']
ALLOWED_TOOLS = ['mcp__%s__%s' % (SERVER_NAME, n) for n in TOOL_NAMES]

MAX_LOG_CHARS = 20000


class Context(object):
    def __init__(self, cp_base_url, cp_token, project_id, emulator):
        self.cp = CloudPebbleClient(cp_base_url, cp_token, project_id)
        self.cp_base_url = cp_base_url
        self.emulator = emulator
        self.events = []
        self.last_build_id = None
        # Describer calls are a real cost on a model that cannot see: one paid
        # call per screenshot, to a different provider than the main model.
        self.vision_calls = 0
        self.vision_cost_usd = 0.0
        # Per-turn, from the caller: whether the acting model can see, and which
        # describer stands in when it cannot. Falls back to the container's own
        # configuration when the caller says nothing.
        self.model_vision = MODEL_HAS_VISION
        self.vision_config = None

    def add_vision_cost(self, usage):
        self.vision_calls += 1
        cost = (usage or {}).get('cost_usd')
        if isinstance(cost, (int, float)):
            self.vision_cost_usd += cost

    def emit(self, role, type_, data):
        self.events.append({'role': role, 'type': type_, 'data': data})


def _text(s):
    return {'content': [{'type': 'text', 'text': s}]}


def _error(ctx, name, message):
    ctx.emit('tool', 'tool_result', {'tool': name, 'ok': False, 'summary': message})
    return {'content': [{'type': 'text', 'text': 'Error: %s' % message}], 'is_error': True}


def _ok(ctx, name, summary, text=None, extra_content=None):
    ctx.emit('tool', 'tool_result', {'tool': name, 'ok': True, 'summary': summary})
    content = [{'type': 'text', 'text': text if text is not None else summary}]
    return {'content': (extra_content or []) + content}


def _decode(b64):
    """Base64 from the model. Whitespace and data: prefixes are common and harmless."""
    raw = (b64 or '').strip()
    if raw.startswith('data:'):
        raw = raw.split(',', 1)[-1]
    try:
        return base64.b64decode(''.join(raw.split()), validate=True)
    except Exception:
        raise ValueError('content_base64 is not valid base64')


def _resource_ids(raw):
    """The identifiers a resource is known by in code. None means 'leave them'."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise ValueError('resource_ids must be JSON, e.g. [{"id": "IMAGE_BACKGROUND"}]')
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError('resource_ids must be a JSON list')
    out = []
    for entry in parsed:
        if isinstance(entry, str):
            out.append({'id': entry})
        elif isinstance(entry, dict) and entry.get('id'):
            out.append(entry)
        else:
            raise ValueError('each resource id needs an "id", e.g. {"id": "IMAGE_BACKGROUND"}')
    return out


# The skill ships reference guides and templates the model is told to read, but
# it has no filesystem: Read is banned and read_file only sees CloudPebble project
# files. On the first real Alloy project the model tried both routes, failed, and
# then spent an entire 30-step budget rediscovering by trial that
# `import Battery from "battery"` does not exist -- which is what the guide it
# could not open says. So serve them.
WORKSPACE = os.environ.get('AGENT_WORKSPACE', '/opt/agent-workspace')
SKILLS_ROOT = os.path.realpath(os.path.join(WORKSPACE, '.claude', 'skills'))
MAX_REFERENCE_CHARS = 120000


def _reference_path(name):
    """Resolve a name under the skills directory, or raise. Never escapes it."""
    raw = (name or '').strip()
    # Tolerate the shapes the model actually types: the absolute path it saw in an
    # error message, a path relative to the skills root, a path relative to the
    # skill itself, or a bare file name.
    relative = raw[len(SKILLS_ROOT):] if raw.startswith(SKILLS_ROOT) else raw
    relative = relative.lstrip('/')
    candidates = [relative]
    if os.path.isdir(SKILLS_ROOT):
        for skill in sorted(os.listdir(SKILLS_ROOT)):
            candidates.append(os.path.join(skill, relative))
    for candidate in candidates:
        full = os.path.realpath(os.path.join(SKILLS_ROOT, candidate))
        if full.startswith(SKILLS_ROOT + os.sep) and os.path.isfile(full):
            return full
    raise ValueError('no such reference: %s' % name)


def _reference_index():
    out = []
    for root, _dirs, files in os.walk(SKILLS_ROOT):
        for f in sorted(files):
            out.append(os.path.relpath(os.path.join(root, f), SKILLS_ROOT))
    return sorted(out)


async def _connect(ctx):
    """The emulator connection, re-resolving the descriptor if it has gone stale.

    The one handed to the turn dies whenever the user reboots or reopens the
    emulator, and a turn runs for minutes. Without this, one reboot poisons every
    remaining install and screenshot in the turn.
    """
    try:
        return await asyncio.to_thread(emu.get_emulator, ctx.emulator, ctx.cp_base_url)
    except emu.NoEmulator:
        fresh = await asyncio.to_thread(
            ctx.cp.live_emulator, (ctx.emulator or {}).get('platform'))
        if not fresh or fresh.get('uuid') == (ctx.emulator or {}).get('uuid'):
            raise
        logger.info('emulator changed under this turn, retrying with %s', fresh['uuid'])
        ctx.emulator = fresh
        return await asyncio.to_thread(emu.get_emulator, ctx.emulator, ctx.cp_base_url)


def _changed(ctx, what):
    """Tell the IDE its view of the project is out of date.

    write_file already says so through its file_edit event, which carries a diff.
    These changes have no diff to show -- a delete, an uploaded image, a settings
    write -- but the sidebar, the resource list and the open editor buffer are
    just as stale without them.
    """
    ctx.emit('tool', 'project_changed', {'what': what})


def _tail(s, limit=MAX_LOG_CHARS):
    return s if len(s) <= limit else '...(truncated)...\n' + s[-limit:]


def build_server(ctx):
    """Build the MCP server bound to one turn's context."""

    @tool('list_files',
          "The project's current state: settings, target platforms and screen sizes, "
          "source files, and which watch the emulator is running.", {})
    async def list_files(args):
        try:
            info = await asyncio.to_thread(ctx.cp.info)
        except CloudPebbleError as e:
            return _error(ctx, 'list_files', str(e))
        files = info.get('source_files') or []
        return _ok(ctx, 'list_files', '%d files' % len(files),
                   project_state.render(info, ctx.emulator))

    @tool('set_app_settings',
          "Change this project's settings. Only the fields you pass are touched. "
          "A watchface MUST have app_is_watchface=true or it installs as an app "
          "and never appears as a face. Scoped to this project alone.",
          {'app_is_watchface': Annotated[bool, 'True for a watchface, False for a watch app'],
           'app_platforms': Annotated[str, 'Comma-separated, e.g. "basalt,emery". Empty = all'],
           'app_long_name': Annotated[str, 'Display name on the watch'],
           'app_short_name': Annotated[str, 'Short name for the launcher'],
           'app_company_name': Annotated[str, 'Author/company name'],
           'app_version_label': Annotated[str, 'Version string, e.g. "1.2"'],
           'app_capabilities': Annotated[str, 'Comma-separated: location, health, configurable'],
           'app_keys': Annotated[str, 'AppMessage keys as a JSON list or object'],
           'app_is_hidden': Annotated[bool, 'Hide from the launcher'],
           'app_is_shown_on_communication': Annotated[bool, 'Show on communication events'],
           'app_modern_multi_js': Annotated[bool, 'Use the modern multi-JS build'],
           'menu_icon': Annotated[str, 'Resource id of a project resource to use as menu icon'],
           'app_uuid': Annotated[str, 'Project UUID'],
           'app_dependencies': Annotated[str, 'npm packages as a JSON object, e.g. '
                                              '{"@moddable/pebbleproxy": "^0.1.3"}. '
                                              'Replaces the whole list.'],
           'name': Annotated[str, 'CloudPebble project name']})
    async def set_app_settings(args):
        fields = {k: v for k, v in args.items() if v is not None and v != ''}
        if not fields:
            return _error(ctx, 'set_app_settings', 'no settings given')
        try:
            res = await asyncio.to_thread(lambda: ctx.cp.set_app_settings(**fields))
        except CloudPebbleError as e:
            return _error(ctx, 'set_app_settings', str(e))
        changed = res.get('changed', {})
        # Settings drive the sidebar's own state (project type, platforms, the
        # resource list's menu icon), so the IDE needs the same nudge.
        _changed(ctx, 'settings')
        return _ok(ctx, 'set_app_settings',
                   ', '.join('%s=%s' % kv for kv in changed.items()) or 'no change')

    @tool('read_file', 'Read a source file.',
          {'path': Annotated[str, 'File name or project path, e.g. src/c/main.c']})
    async def read_file(args):
        path = args['path']
        try:
            content = await asyncio.to_thread(ctx.cp.read_file, path)
        except CloudPebbleError as e:
            return _error(ctx, 'read_file', str(e))
        return _ok(ctx, 'read_file', path, content)

    @tool('write_file', 'Create or overwrite a source file. Always write the whole file.',
          {'path': Annotated[str, 'File name or project path, e.g. src/c/main.c'],
           'content': Annotated[str, 'Full new contents of the file']})
    async def write_file(args):
        path, content = args['path'], args['content']
        try:
            file_id, old = await asyncio.to_thread(ctx.cp.write_file, path, content)
        except CloudPebbleError as e:
            return _error(ctx, 'write_file', str(e))
        diff = ''.join(difflib.unified_diff((old or '').splitlines(True),
                                            content.splitlines(True),
                                            'a/' + path, 'b/' + path))
        ctx.emit('tool', 'file_edit', {'path': path, 'file_id': file_id, 'diff': diff})
        return _ok(ctx, 'write_file', '%s (%s)' % (path, 'created' if old is None else 'updated'))

    @tool('delete_file', 'Delete a source file.', {'path': Annotated[str, 'File name or project path']})
    async def delete_file(args):
        try:
            await asyncio.to_thread(ctx.cp.delete_file, args['path'])
        except CloudPebbleError as e:
            return _error(ctx, 'delete_file', str(e))
        _changed(ctx, 'files')
        return _ok(ctx, 'delete_file', 'deleted %s' % args['path'])

    @tool('write_binary_file',
          "Create or replace a non-text source file -- an Alloy asset under "
          "src/embeddedjs, such as a .png, .pdc or .ttf. Images the app draws with "
          "resource ids go through write_resource instead.",
          {'path': Annotated[str, 'Project path, e.g. src/embeddedjs/dial.png'],
           'content_base64': Annotated[str, 'The file, base64 encoded']})
    async def write_binary_file(args):
        path = args['path']
        try:
            data = _decode(args['content_base64'])
            file_id, replaced = await asyncio.to_thread(ctx.cp.write_binary_file, path, data)
        except (CloudPebbleError, ValueError) as e:
            return _error(ctx, 'write_binary_file', str(e))
        _changed(ctx, 'files')
        return _ok(ctx, 'write_binary_file', '%s (%d bytes, %s)'
                   % (path, len(data), 'replaced' if replaced else 'created'))

    @tool('write_resource',
          "Add or replace a project resource: an image, font or raw blob the app "
          "loads by resource id. Replacing keeps the existing ids unless you pass "
          "new ones. Keep assets small -- they travel base64 through this tool, and "
          "drawing in code is usually cheaper than shipping a bitmap.",
          {'file_name': Annotated[str, 'Resource file name, e.g. background.png'],
           'kind': Annotated[str, 'bitmap, png, png-trans, font, pbi or raw'],
           'content_base64': Annotated[str, 'The file, base64 encoded'],
           'resource_ids': Annotated[str, 'Optional JSON list of identifiers, e.g. '
                                          '[{"id": "IMAGE_BACKGROUND"}] or with options: '
                                          '[{"id": "FONT_BIG", "tracking": 1}]. '
                                          'Defaults to one id derived from the file name.']})
    async def write_resource(args):
        name, kind = args['file_name'], args['kind']
        try:
            data = _decode(args['content_base64'])
            ids = _resource_ids(args.get('resource_ids'))
            resource, replaced = await asyncio.to_thread(
                ctx.cp.write_resource, name, kind, data, ids)
        except (CloudPebbleError, ValueError) as e:
            return _error(ctx, 'write_resource', str(e))
        _changed(ctx, 'resources')
        return _ok(ctx, 'write_resource',
                   '%s (%s, %d bytes, %s)' % (name, kind, len(data),
                                              'replaced' if replaced else 'created'),
                   'ids: %s' % ', '.join(resource.get('identifiers') or []))

    @tool('delete_resource', 'Delete a project resource.',
          {'file_name': Annotated[str, 'Resource file name, e.g. background.png']})
    async def delete_resource(args):
        try:
            await asyncio.to_thread(ctx.cp.delete_resource, args['file_name'])
        except CloudPebbleError as e:
            return _error(ctx, 'delete_resource', str(e))
        _changed(ctx, 'resources')
        return _ok(ctx, 'delete_resource', 'deleted %s' % args['file_name'])

    @tool('read_reference',
          "Read one of the skill's own reference guides or templates -- the Alloy "
          "guide, the watchapp guide, the API reference, a template .c file. Call it "
          "with no name to list what is available. These are NOT project files; use "
          "read_file for those.",
          {'name': Annotated[str, 'e.g. reference/alloy-guide.md, or blank to list']})
    async def read_reference(args):
        name = (args.get('name') or '').strip()
        if not name:
            return _ok(ctx, 'read_reference', 'index',
                       'Available:\n' + '\n'.join('  ' + p for p in _reference_index()))
        try:
            path = _reference_path(name)
            with open(path) as handle:
                body = handle.read()
        except (ValueError, OSError) as e:
            return _error(ctx, 'read_reference', '%s. Call read_reference with no name '
                                                 'to see what exists.' % e)
        if len(body) > MAX_REFERENCE_CHARS:
            body = body[:MAX_REFERENCE_CHARS] + '\n...(truncated)'
        return _ok(ctx, 'read_reference', os.path.relpath(path, SKILLS_ROOT), body)

    @tool('build', 'Compile the project. Returns the build log; a failed compile is a '
                   'normal result, read the log and fix the code.', {})
    async def build(args):
        try:
            state, build_id, log = await asyncio.to_thread(ctx.cp.build)
        except CloudPebbleError as e:
            return _error(ctx, 'build', str(e))
        ok = state == 'succeeded'
        if ok:
            ctx.last_build_id = build_id
        ctx.emit('tool', 'build', {'build_id': build_id, 'state': state,
                                   'log_url': '/ide/project/%d/build/%d/log' % (ctx.cp.project_id, build_id)})
        ctx.emit('tool', 'tool_result', {'tool': 'build', 'ok': ok,
                                         'summary': 'build %d %s' % (build_id, state)})
        headers = {'succeeded': 'Build %d succeeded.',
                   'failed': 'Build %d FAILED.',
                   'unknown': 'Build %d did not report a result in time -- it may still '
                              'be running. Do not assume it failed.'}
        header = headers[state] % build_id
        return {'content': [{'type': 'text', 'text': header + '\n\n' + _tail(log)}]}

    @tool('install', 'Install the latest successful build into the running emulator.', {})
    async def install(args):
        try:
            build_id = ctx.last_build_id
            if build_id is None:
                last = await asyncio.to_thread(ctx.cp.last_build)
                if not last or last.get('state') != 3:
                    return _error(ctx, 'install', 'no successful build to install -- run build first')
                build_id = last['id']
            pbw = await asyncio.to_thread(ctx.cp.download_pbw, build_id)
            conn = await _connect(ctx)
            status = await asyncio.to_thread(conn.install, pbw)
            # The watch ships APP_LOG output only after it is asked to, and a
            # fresh install is exactly when the model wants to read it.
            await asyncio.to_thread(conn.enable_app_logs)
        except emu.NoEmulator as e:
            return _error(ctx, 'install', str(e))
        except CloudPebbleError as e:
            return _error(ctx, 'install', str(e))
        if status != 0:
            # A rejection is almost always the emulator, not the code: qemu answers
            # BlobDB errors this way and CloudPebble's own UI responds by telling
            # the user to reboot it. Say so, because a model told only "rejected"
            # concludes its own app is crashing and starts deleting working
            # features to bisect -- which is exactly what happened on the first
            # real run of this feature.
            return _error(ctx, 'install',
                          'the emulator rejected the install (status %d). This is an '
                          'emulator problem, NOT your code -- the build is fine. Ask '
                          'the user to reboot the emulator in CloudPebble (Build & Run '
                          '-> the reboot button, or close and reopen it) and then say '
                          'continue. Do not change working code over this.' % status)
        return _ok(ctx, 'install', 'installed build %d' % build_id)

    @tool('screenshot', 'Take a screenshot of the emulator and look at it. Use this to '
                        'verify layout after every install.', {})
    async def screenshot(args):
        try:
            conn = await _connect(ctx)
            png = await asyncio.to_thread(conn.screenshot)
        except emu.NoEmulator as e:
            return _error(ctx, 'screenshot', str(e))
        b64 = base64.b64encode(png).decode()
        # The user always sees the screenshot in the chat panel, even when the
        # model cannot.
        ctx.emit('tool', 'tool_result', {'tool': 'screenshot', 'ok': True,
                                         'summary': 'screenshot', 'image_png_b64': b64})
        if not ctx.model_vision:
            # Text-only main model: a separate vision model looks at it and the
            # description comes back as text, so the verification step still
            # happens. Without one configured, say so plainly rather than let
            # the model "verify" an image it never received.
            if vision.configured(ctx.vision_config):
                try:
                    described, vision_usage = await asyncio.to_thread(
                        vision.describe, png, ctx.vision_config)
                    ctx.add_vision_cost(vision_usage)
                except vision.VisionError as e:
                    logger.warning('vision describe failed: %s', e)
                    return {'content': [{'type': 'text', 'text':
                        'Screenshot captured and shown to the user, but it could not be '
                        'described (%s) and YOU CANNOT SEE IMAGES. Do not claim to have '
                        'checked it.' % e}]}
                return {'content': [{'type': 'text', 'text':
                    'You cannot see images, so a vision model looked at the screenshot '
                    'for you. Treat this description as what is on screen:\n\n%s' % described}]}
            return {'content': [{'type': 'text', 'text':
                'Screenshot captured and shown to the user, but THIS MODEL CANNOT SEE '
                'IMAGES and no vision model is configured. You did not look at it. Do '
                'not describe it, do not claim it is centred or correct, and do not '
                'tick off the visual verification checklist. Say the user needs to '
                'check it, or reason from the code and from logs() instead.'}]}
        return {'content': [{'type': 'image', 'data': b64, 'mimeType': 'image/png'},
                            {'type': 'text', 'text': 'Screenshot of the emulator.'}]}

    @tool('press',
          "Press a button on the watch, or shake it. This is how you drive an app: "
          "menus, scrolling, game input, anything that only happens after a press. "
          "Take a screenshot afterwards to see what it did. Watchfaces have no "
          "buttons -- shake is their only input.",
          {'button': Annotated[str, 'up, select, down, back, or shake'],
           'hold_ms': Annotated[int, 'How long to hold it, default 120. '
                                     'Use ~700 for a long press']})
    async def press(args):
        button = (args.get('button') or '').strip().lower()
        if button not in emu.BUTTONS and button != 'shake':
            return _error(ctx, 'press', 'unknown button %r -- use up, select, down, '
                                        'back or shake' % button)
        try:
            conn = await _connect(ctx)
            if button == 'shake':
                await asyncio.to_thread(conn.tap)
            else:
                await asyncio.to_thread(conn.press_button, button,
                                        int(args.get('hold_ms') or 120))
        except emu.NoEmulator as e:
            return _error(ctx, 'press', str(e))
        return _ok(ctx, 'press', button if button == 'shake' else 'pressed %s' % button)

    @tool('logs', 'Drain app and phone logs from the emulator for a few seconds. '
                  'Covers APP_LOG from the watch and console.log from the phone-side '
                  'JS, which is where AppMessage and web request problems show up.',
          {'seconds': Annotated[int, 'How long to collect logs, 1-30']})
    async def logs(args):
        seconds = max(1, min(int(args.get('seconds') or 5), 30))
        try:
            conn = await _connect(ctx)
            # Harmless if the app was installed by the browser rather than by us.
            await asyncio.to_thread(conn.enable_app_logs)
            lines = await asyncio.to_thread(conn.logs, seconds)
        except emu.NoEmulator as e:
            return _error(ctx, 'logs', str(e))
        return _ok(ctx, 'logs', '%d log lines' % len(lines),
                   _tail('\n'.join(lines)) or '(no output in %ds)' % seconds)

    return create_sdk_mcp_server(
        name=SERVER_NAME,
        tools=[list_files, set_app_settings, read_file, write_file, delete_file,
               write_binary_file, write_resource, delete_resource, read_reference,
               build, install, press, screenshot, logs],
    )
