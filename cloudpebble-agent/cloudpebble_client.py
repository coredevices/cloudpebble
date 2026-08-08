"""HTTP client for the CloudPebble API, authorised by a scoped agent bearer token.

Only the endpoints the token is accepted by (see utils/agent_token.py) are here:
project info, source load/save/create/delete, build run/last/info/log/download.

Everything that can fail on the wire raises CloudPebbleError, never a bare
requests exception -- tools.py turns CloudPebbleError into a tool result the model can
read and react to, and anything else kills the whole turn.
"""

import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 60
BUILD_POLL_INTERVAL = 2
BUILD_TIMEOUT = 600
# Consecutive poll failures before we stop waiting. Rides out a 502; does not spin for
# ten minutes on an expired token.
BUILD_POLL_MISSES = 10

STATE_WAITING, STATE_FAILED, STATE_SUCCEEDED = 1, 2, 3

# Where each kind of source file lives, mirroring SourceFile.DIR_MAP server-side.
#
# CloudPebble stores a file as (target, name-relative-to-that-target's-dir), and
# validates the two together: a name of 'src/pkjs/index.js' with target 'app'
# becomes 'src/c/src/pkjs/index.js' and is refused with "Unacceptable file
# extension for app file in [src/c/...]". Sending target='app' for everything is
# why writing pkjs used to fail three times and then get given up on. The model
# should keep passing whole project paths -- it is this client's job to split
# them the way the server expects.
#
# Order matters: the longest prefixes must be tried first, or 'src' swallows
# 'src/pkjs'.
DIR_MAP = {
    'native': [('src/pkjs', 'pkjs'), ('src/js', 'pkjs'), ('worker_src/c', 'worker'),
               ('worker_src', 'worker'), ('src/c', 'app'), ('src', 'app')],
    'alloy': [('src/pkjs', 'pkjs'), ('src/embeddedjs', 'embeddedjs'),
              ('src/c', 'app'), ('src', 'app')],
    'package': [('src/c', 'app'), ('include', 'public'), ('src/js', 'pkjs')],
    'rocky': [('src/rocky', 'app'), ('src/pkjs', 'pkjs'), ('src/common', 'common')],
    'pebblejs': [('src/js', 'app')],
    'simplyjs': [('src', 'app')],
}

# Text extensions CloudPebble accepts; anything else has to go through the
# binary upload endpoint instead of the source-file one.
TEXT_EXTENSIONS = ('.c', '.h', '.js', '.json')


def _default_identifier(file_name):
    """IMAGE_MY_THING from my-thing.png, the same shape the IDE suggests."""
    stem = os.path.splitext(os.path.basename(file_name))[0]
    return re.sub(r'[^A-Za-z0-9]+', '_', stem).strip('_').upper() or 'RESOURCE'


def split_path(project_type, path):
    """('src/pkjs/index.js', native) -> ('pkjs', 'index.js').

    A bare name with no directory keeps the caller's default target, which is how
    'main.c' still works.
    """
    path = path.replace('\\', '/').lstrip('/')
    for prefix, target in DIR_MAP.get(project_type or 'native', DIR_MAP['native']):
        if path.startswith(prefix + '/'):
            return target, path[len(prefix) + 1:]
    return None, path


class CloudPebbleError(Exception):
    pass


class CloudPebbleClient(object):
    def __init__(self, base_url, token, project_id):
        self.base = base_url.rstrip('/')
        self.project_id = int(project_id)
        self.session = requests.Session()
        self.session.headers['Authorization'] = 'Bearer %s' % token
        self._project_type = None

    # -- plumbing ----------------------------------------------------------

    def _url(self, path):
        return '%s/ide/%s' % (self.base, path.lstrip('/'))

    def _request(self, method, path, **kwargs):
        """One place where a transport failure becomes a CloudPebbleError."""
        kwargs.setdefault('timeout', TIMEOUT)
        try:
            return self.session.request(method, self._url(path), **kwargs)
        except requests.RequestException as e:
            raise CloudPebbleError('%s %s failed: %s' % (method, path, e))

    def _json(self, method, path, **kwargs):
        r = self._request(method, path, **kwargs)
        try:
            body = r.json()
        except ValueError:
            raise CloudPebbleError('%s %s returned %d (not JSON)' % (method, path, r.status_code))
        if r.status_code >= 400 or body.get('success') is False:
            raise CloudPebbleError(body.get('error') or 'HTTP %d' % r.status_code)
        return body

    def _project(self, path):
        return 'project/%d/%s' % (self.project_id, path)

    # -- files -------------------------------------------------------------

    def info(self):
        info = self._json('GET', self._project('info'))
        # Which DIR_MAP applies. Set at project creation and never changed, so
        # one read is enough for the turn.
        self._project_type = info.get('type') or 'native'
        return info

    @property
    def project_type(self):
        if self._project_type is None:
            self.info()
        return self._project_type

    def list_files(self):
        return self.info()['source_files']

    def live_emulator(self, platform=None):
        """The user's emulator as it is right now, or None.

        A turn is handed one descriptor at the start; rebooting the emulator
        mid-turn (which CloudPebble tells the user to do when an install is
        rejected) makes that descriptor point at something dead for the rest of
        the turn. This is how the tools pick up the replacement.
        """
        path = self._project('agent/emulator')
        if platform:
            path += '?platform=%s' % platform
        try:
            return self._json('GET', path).get('emulator')
        except CloudPebbleError:
            return None

    # Project settings. Scoped by the token to this one project; the endpoint
    # refuses anything that reaches another project or an external service.
    SETTINGS_FIELDS = (
        'name', 'app_company_name', 'app_short_name', 'app_long_name',
        'app_version_label', 'app_capabilities', 'app_keys', 'app_platforms',
        'app_uuid', 'menu_icon', 'app_dependencies',
        'app_is_watchface', 'app_is_hidden', 'app_is_shown_on_communication',
        'app_modern_multi_js',
    )
    _BOOL_FIELDS = ('app_is_watchface', 'app_is_hidden',
                    'app_is_shown_on_communication', 'app_modern_multi_js')

    def set_app_settings(self, **fields):
        data = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key not in self.SETTINGS_FIELDS:
                raise CloudPebbleError('unknown setting: %s' % key)
            if key in self._BOOL_FIELDS:
                data[key] = 'true' if value else 'false'
            else:
                data[key] = str(value)
        if not data:
            raise CloudPebbleError('no settings given')
        return self._json('POST', self._project('agent/app_settings'), data=data)

    def _find(self, path):
        for f in self.list_files():
            if path in (f['name'], f['file_path']):
                return f
        return None

    def read_file(self, path):
        f = self._find(path)
        if f is None:
            raise CloudPebbleError('no such file: %s' % path)
        return self._json('GET', self._project('source/%d/load' % f['id']))['source']

    def write_file(self, path, content, target=None):
        """Returns (file_id, old_content). old_content is None for a new file."""
        f = self._find(path)
        if f is None:
            guessed, name = split_path(self.project_type, path)
            target = target or guessed or 'app'
            if not name.endswith(TEXT_EXTENSIONS) and target != 'embeddedjs':
                raise CloudPebbleError(
                    '%s is not a text source file. Use write_binary_file for images, '
                    'fonts and other binary assets, or add it as a resource.' % path)
            created = self._json('POST', self._project('create_source_file'),
                                 data={'name': name, 'target': target, 'content': content})
            return created['file']['id'], None
        old = self._json('GET', self._project('source/%d/load' % f['id']))['source']
        # `modified` is the server's own timestamp for the file: if someone saved
        # in between, Django refuses rather than clobbering.
        self._json('POST', self._project('source/%d/save' % f['id']),
                   data={'content': content, 'folded_lines': '[]',
                         'modified': int(f['lastModified'])})
        return f['id'], old

    def delete_file(self, path):
        f = self._find(path)
        if f is None:
            raise CloudPebbleError('no such file: %s' % path)
        self._json('POST', self._project('source/%d/delete' % f['id']))
        return f['id']

    def write_binary_file(self, path, data):
        """A non-text source file: an Alloy asset (.png, .pdc, .ttf) under src/embeddedjs.

        There is no binary save, only create, so replacing means deleting first.
        """
        guessed, name = split_path(self.project_type, path)
        target = guessed or 'embeddedjs'
        # Binary *source* files exist only under src/embeddedjs, and only Alloy
        # projects have that. Everywhere else an image or font is a resource, and
        # saying so beats letting the server answer "Unacceptable file extension
        # for app file in [src/c/embeddedjs/x.png]".
        if target != 'embeddedjs' or self.project_type != 'alloy':
            raise CloudPebbleError(
                'binary source files only exist under src/embeddedjs in an Alloy '
                'project (this is a %s project). An image or font belongs in '
                'resources -- use write_resource.' % self.project_type)
        existing = self._find(path)
        if existing is not None:
            self._json('POST', self._project('source/%d/delete' % existing['id']))
        created = self._json('POST', self._project('create_binary_source_file'),
                             data={'name': name, 'target': target},
                             files={'file': (name.split('/')[-1], data,
                                             'application/octet-stream')})
        return created['file']['id'], existing is not None

    def read_binary_file(self, path):
        f = self._find(path)
        if f is None:
            raise CloudPebbleError('no such file: %s' % path)
        r = self._request('GET', self._project('source/%d/download' % f['id']))
        if r.status_code >= 400:
            raise CloudPebbleError('could not download %s: HTTP %d' % (path, r.status_code))
        return r.content

    # -- resources ---------------------------------------------------------
    #
    # Images, fonts and raw blobs: everything the IDE's Resources pane does,
    # except renaming and per-variant deletes, which nothing has needed.

    RESOURCE_KINDS = ('bitmap', 'png', 'png-trans', 'font', 'pbi', 'raw')

    def _find_resource(self, name):
        for r in self.info().get('resources') or []:
            if r.get('file_name') == name:
                return r
        return None

    def write_resource(self, file_name, kind, data, resource_ids=None):
        """Create a resource, or replace the file of one that exists.

        resource_ids are the identifiers C code refers to (RESOURCE_ID_<id>), each
        optionally carrying its own font/bitmap options. Replacing keeps the
        existing identifiers unless new ones are given -- changing the artwork
        should not silently unhook it from the code that draws it.
        """
        if kind not in self.RESOURCE_KINDS:
            raise CloudPebbleError('unknown resource kind %r (expected one of %s)'
                                   % (kind, ', '.join(self.RESOURCE_KINDS)))
        existing = self._find_resource(file_name)
        upload = {'file': (file_name.split('/')[-1], data, 'application/octet-stream')}
        if existing is None:
            ids = resource_ids or [{'id': _default_identifier(file_name)}]
            created = self._json('POST', self._project('create_resource'),
                                 data={'kind': kind, 'file_name': file_name,
                                       'resource_ids': json.dumps(ids),
                                       'new_tags': json.dumps([])},
                                 files=upload)
            return created['file'], False
        ids = resource_ids
        if ids is None:
            # get_options_dict shape, back the way it came -- minus the nulls.
            # The server reads options by presence, so an unset 'tracking': None
            # comes back as int(None) and 500s the whole update.
            ids = [dict({k: v for k, v in (extra or {}).items() if v is not None}, id=rid)
                   for rid, extra in (existing.get('extra') or {}).items()] or \
                  [{'id': rid} for rid in existing.get('identifiers') or []]
        updated = self._json('POST', self._project('resource/%d/update' % existing['id']),
                             data={'resource_ids': json.dumps(ids),
                                   'file_name': file_name,
                                   'replacements': json.dumps([['', 0]])},
                             files={'replacement_files[]': upload['file']})
        return updated['file'], True

    def delete_resource(self, file_name):
        existing = self._find_resource(file_name)
        if existing is None:
            raise CloudPebbleError('no such resource: %s' % file_name)
        self._json('POST', self._project('resource/%d/delete' % existing['id']))
        return existing['id']

    # No read_resource: show_resource 302s to a storage URL that is only
    # resolvable from inside the CloudPebble network (on dev it is literally
    # http://s3:4569/), so the agent cannot follow it. Nothing needs it -- the
    # agent writes assets, it does not read them back.

    # -- builds ------------------------------------------------------------

    def build_info(self, build_id):
        # ide/urls.py: project/<id>/build/<build_id>/info -> get_build_info
        return self._json('GET', self._project('build/%d/info' % build_id)).get('build') or {}

    def build(self):
        """Run a build to completion. Returns (state, build_id, log), where state is
        'succeeded', 'failed' or 'unknown'.

        A failed compile is a normal result, not an exception -- the model is
        expected to read the log and fix its code. Likewise a transient 502 while
        polling: keep polling until the deadline rather than killing the turn.

        Polls this specific build rather than build/last, which returns the project's
        newest build and would report someone else's compile.
        """
        started = self._json('POST', self._project('build/run'))
        build_id = started['build_id']

        state, misses = None, 0
        deadline = time.time() + BUILD_TIMEOUT
        while time.time() < deadline:
            time.sleep(BUILD_POLL_INTERVAL)
            try:
                state = self.build_info(build_id).get('state')
            except CloudPebbleError as e:
                # A 502 or a blip is worth retrying; an expired token is not, and
                # spinning on it for the full BUILD_TIMEOUT would stall the turn.
                misses += 1
                logger.info('build poll hiccup %d/%d: %s', misses, BUILD_POLL_MISSES, e)
                if misses >= BUILD_POLL_MISSES:
                    return 'unknown', build_id, 'lost contact with the build: %s' % e
                continue
            misses = 0
            if state in (STATE_FAILED, STATE_SUCCEEDED):
                break
        else:
            return 'unknown', build_id, 'build did not finish within %ds' % BUILD_TIMEOUT

        try:
            log = self._json('GET', self._project('build/%d/log' % build_id)).get('log', '')
        except CloudPebbleError as e:
            log = '(could not read the build log: %s)' % e
        return ('succeeded' if state == STATE_SUCCEEDED else 'failed'), build_id, log

    def last_build(self):
        return self._json('GET', self._project('build/last')).get('build')

    def download_pbw(self, build_id):
        # 'package' projects ship a tarball, everything else a pbw. v1 is watchfaces
        # only, but hardcoding the name here would 404 silently outside that.
        name = 'package.tar.gz' if self.info().get('type') == 'package' else 'watchface.pbw'
        r = self._request('GET', self._project('build/%d/download/%s' % (build_id, name)))
        if r.status_code != 200:
            raise CloudPebbleError('could not download build %d (HTTP %d)' % (build_id, r.status_code))
        return r.content
