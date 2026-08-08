"""Render the project and emulator the agent is actually working on.

The agent used to start every turn blind: it knew the project id and nothing
else, so it guessed at the target platform (and so at the screen size it was
laying out for), could not see whether the project was already flagged as a
watchface, and did not know whether it was a C or an Alloy project until it
happened to list the files. Guessing wrong is expensive here -- a layout built
for 144x168 is cropped on emery, and a watchface built as a watch app looks
perfect in the screenshot and is still wrong.

So the state goes into the turn: settings, file tree, and which watch is
actually running in the user's browser right now.

This is appended to the user's message rather than prepended to the system
prompt on purpose. Providers that cache by prefix (DeepSeek, Moonshot) only hit
when the prefix is identical from the 0th token, and this block changes every
turn -- at the front it would destroy the cache, at the end it costs nothing.
"""

# Screen geometry per platform. The agent gets this from the skill too, but the
# skill is a document it may not have read yet when it starts laying out.
SCREENS = {
    'aplite': ('144x168', 'rectangular', 'black and white'),
    'basalt': ('144x168', 'rectangular', '64 colours'),
    'chalk': ('180x180', 'round', '64 colours'),
    'diorite': ('144x168', 'rectangular', 'black and white'),
    'emery': ('200x228', 'rectangular', '64 colours'),
    'gabbro': ('260x260', 'round', '64 colours'),
    'flint': ('144x168', 'rectangular', '64 colours'),
}


def screen_line(platform):
    spec = SCREENS.get(platform)
    if not spec:
        return platform
    return '%s, %s %s, %s' % (platform, spec[0], spec[1], spec[2])


def _yn(value):
    return 'yes' if value else 'no'


def settings_block(info):
    """The project's settings, as the agent needs to reason about them."""
    lines = []
    project_type = info.get('type') or 'native'
    language = 'Alloy (JavaScript on the watch)' if project_type == 'alloy' else (
        'C' if project_type in ('native', 'package') else project_type)
    lines.append('name: %s' % info.get('name', ''))
    lines.append('language: %s (project_type=%s, fixed at creation -- you cannot change it)'
                 % (language, project_type))
    lines.append('is_watchface: %s%s' % (
        _yn(info.get('app_is_watchface')),
        '' if info.get('app_is_watchface')
        else '  <- builds as a watch APP, not a face. set_app_settings(app_is_watchface=true) if the user wants a face.'))

    platforms = info.get('app_platforms') or ''
    enabled = [p for p in platforms.split(',') if p] or list(info.get('supported_platforms') or [])
    lines.append('target platforms: %s' % (', '.join(enabled) if enabled else '(all supported)'))
    for platform in enabled:
        lines.append('  %s' % screen_line(platform))
    lines.append('platforms this project type supports: %s'
                 % ', '.join(info.get('supported_platforms') or []))

    lines.append('uuid: %s' % (info.get('app_uuid') or ''))
    lines.append('version: %s' % (info.get('app_version_label') or ''))
    lines.append('long name: %s' % (info.get('app_long_name') or ''))
    lines.append('short name: %s' % (info.get('app_short_name') or ''))
    lines.append('company: %s' % (info.get('app_company_name') or ''))
    lines.append('capabilities: %s' % (info.get('app_capabilities') or '(none)'))
    lines.append('message keys: %s' % (info.get('app_keys') or '(none)'))
    dependencies = info.get('app_dependencies') or {}
    lines.append('dependencies: %s' % (', '.join('%s@%s' % kv for kv in sorted(dependencies.items()))
                                       or '(none)'))
    lines.append('multi-JS: %s' % _yn(info.get('app_modern_multi_js')))
    lines.append('hidden from launcher: %s' % _yn(info.get('app_is_hidden')))
    return lines


# Where a file is allowed to live, per project type. CloudPebble derives a file's
# target from its path and rejects anything else -- "Unacceptable file extension
# for app file in [src/index.js]" means the path was wrong, not that the file
# type is unsupported. An agent that reads that as "I cannot write pkjs here"
# silently ships without its JS, which is what happened before this was spelled
# out.
WRITABLE_PATHS = {
    'native': ['src/c/*.c and src/c/*.h — watch-side C',
               'src/pkjs/*.js and *.json — phone-side JS (weather, web requests)',
               'worker_src/c/*.c — background worker',
               'images and fonts are resources, not files: write_resource'],
    'alloy': ['src/embeddedjs/main.js and manifest.json — watch-side JS',
              'src/embeddedjs/*.png, *.pdc, *.ttf — assets, via write_binary_file',
              'src/pkjs/*.js and *.json — phone-side JS',
              'src/c/mdbl.c — boot stub, already there, do not touch'],
    'package': ['src/c/*.c and *.h', 'include/*.h', 'src/js/*.js'],
    'rocky': ['src/rocky/*.js', 'src/pkjs/*.js', 'src/common/*.js'],
}


def paths_block(project_type):
    return WRITABLE_PATHS.get(project_type or 'native', WRITABLE_PATHS['native'])


def files_block(info):
    lines = []
    for f in info.get('source_files') or []:
        lines.append('  %s  (target=%s)' % (f.get('file_path'), f.get('target')))
    if not lines:
        lines.append('  (no source files yet)')
    resources = info.get('resources') or []
    if resources:
        lines.append('resources:')
        for r in resources:
            ids = ', '.join(r.get('identifiers') or [])
            lines.append('  %s  (%s%s)' % (r.get('file_name'), r.get('kind'),
                                           ', ids: %s' % ids if ids else ''))
    return lines


def emulator_block(emulator):
    """Which watch is on screen in front of the user, if any."""
    platform = (emulator or {}).get('platform')
    if not emulator:
        return ['no emulator is open: install() and screenshot() will fail until the '
                'user opens one. build() still works.']
    if not platform:
        return ['an emulator is open, but its platform was not reported. '
                'screenshot() shows what it actually is.']
    return ['running: %s' % screen_line(platform),
            'screenshot() and install() act on THIS watch. If it is not in the target '
            'platform list above, either lay out for it too or say so.']


def render(info, emulator=None):
    """The whole block. Returns '' when there is nothing trustworthy to say."""
    if not info:
        return ''
    out = ['<project-state>',
           'This is the live state of the project you are working on, read just now.',
           '',
           '## Settings (change with set_app_settings, not by writing files)']
    out += settings_block(info)
    out += ['', '## Files (read/write by these paths)']
    out += files_block(info)
    out += ['', 'New files must go in one of these, or the write is refused:']
    out += ['  %s' % line for line in paths_block(info.get('type'))]
    out += ['', '## Emulator']
    out += emulator_block(emulator)
    out += ['</project-state>']
    return '\n'.join(out)
