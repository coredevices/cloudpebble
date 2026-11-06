"""Unit test for the build poll state machine. No network.

    python3 test_cloudpebble_client.py
"""

import json

import requests

import cloudpebble_client as cpc
from cloudpebble_client import CloudPebbleClient, CloudPebbleError

cpc.BUILD_POLL_INTERVAL = 0


class FakeResponse(object):
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode()

    def json(self):
        if isinstance(self._body, bytes):
            raise ValueError('not json')
        return self._body


class FakeSession(object):
    """Replays a scripted list of (url_fragment -> response|exception)."""

    def __init__(self, script):
        self.script = list(script)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        if not self.script:
            raise AssertionError('unscripted call: %s %s' % (method, url))
        fragment, result = self.script.pop(0)
        assert fragment in url, 'expected %r in %r' % (fragment, url)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)


def _client(script):
    c = CloudPebbleClient('https://cp.example/', 'tok', 7)
    c.session = FakeSession(script)
    return c


def test_build_succeeds():
    c = _client([
        ('build/run', FakeResponse({'build_id': 12, 'task_id': 't'})),
        ('build/12/info', FakeResponse({'build': {'id': 12, 'state': 1}})),
        ('build/12/info', FakeResponse({'build': {'id': 12, 'state': 3}})),
        ('build/12/log', FakeResponse({'log': 'all good'})),
    ])
    assert c.build() == ('succeeded', 12, 'all good')


def test_build_fails_is_a_result_not_an_exception():
    c = _client([
        ('build/run', FakeResponse({'build_id': 13, 'task_id': 't'})),
        ('build/13/info', FakeResponse({'build': {'id': 13, 'state': 2}})),
        ('build/13/log', FakeResponse({'log': 'main.c:3: error'})),
    ])
    state, build_id, log = c.build()
    assert (state, build_id) == ('failed', 13) and 'error' in log


def test_a_502_during_the_poll_does_not_kill_the_turn():
    # nginx hands back HTML, or the connection blips: keep polling.
    c = _client([
        ('build/run', FakeResponse({'build_id': 14, 'task_id': 't'})),
        ('build/14/info', FakeResponse(b'<html>502</html>', status=502)),
        ('build/14/info', requests.ConnectionError('boom')),
        ('build/14/info', FakeResponse({'build': {'id': 14, 'state': 3}})),
        ('build/14/log', FakeResponse({'log': 'ok'})),
    ])
    assert c.build() == ('succeeded', 14, 'ok')


def test_a_permanent_poll_failure_gives_up_early():
    # An expired token must not spin for the whole BUILD_TIMEOUT.
    script = [('build/run', FakeResponse({'build_id': 18, 'task_id': 't'}))]
    script += [('build/18/info', FakeResponse({'error': 'forbidden'}, status=403))
               for _ in range(cpc.BUILD_POLL_MISSES)]
    c = _client(script)
    state, build_id, log = c.build()
    assert state == 'unknown' and build_id == 18 and 'lost contact' in log
    assert not c.session.script, 'should have stopped at BUILD_POLL_MISSES'


def test_timeout_is_unknown_not_failed():
    # 'failed' would send the model off fixing code that compiled fine.
    cpc.BUILD_TIMEOUT, saved = 0, cpc.BUILD_TIMEOUT
    try:
        c = _client([('build/run', FakeResponse({'build_id': 15, 'task_id': 't'}))])
        state, build_id, log = c.build()
    finally:
        cpc.BUILD_TIMEOUT = saved
    assert state == 'unknown' and build_id == 15 and 'did not finish' in log


def test_transport_failures_become_cloudpebble_errors():
    c = _client([('project/7/info', requests.ConnectTimeout('dns'))])
    try:
        c.info()
    except CloudPebbleError as e:
        assert 'dns' in str(e)
    else:
        raise AssertionError('expected CloudPebbleError')


def test_download_name_follows_the_project_type():
    c = _client([
        ('project/7/info', FakeResponse({'type': 'package'})),
        ('build/16/download/package.tar.gz', FakeResponse(b'tarball')),
    ])
    assert c.download_pbw(16) == b'tarball'

    c = _client([
        ('project/7/info', FakeResponse({'type': 'native'})),
        ('build/17/download/watchface.pbw', FakeResponse(b'pbw')),
    ])
    assert c.download_pbw(17) == b'pbw'


class RecordingSession(FakeSession):
    """Like FakeSession, but keeps the request bodies so we can assert on them."""

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get('data'), kwargs.get('files')))
        if not self.script:
            raise AssertionError('unscripted call: %s %s' % (method, url))
        fragment, result = self.script.pop(0)
        assert fragment in url, 'expected %r in %r' % (fragment, url)
        if isinstance(result, Exception):
            raise result
        return result


def _recording(script):
    c = CloudPebbleClient('https://cp.example/', 'tok', 7)
    c.session = RecordingSession(script)
    return c


def test_paths_split_into_the_target_and_name_the_server_expects():
    # CloudPebble stores (target, name-under-that-target's-dir) and validates the
    # pair. Sending the whole path with target=app is what made writing pkjs fail.
    assert cpc.split_path('native', 'src/pkjs/index.js') == ('pkjs', 'index.js')
    assert cpc.split_path('native', 'src/c/main.c') == ('app', 'main.c')
    assert cpc.split_path('native', 'worker_src/c/worker.c') == ('worker', 'worker.c')
    assert cpc.split_path('alloy', 'src/embeddedjs/main.js') == ('embeddedjs', 'main.js')
    assert cpc.split_path('alloy', 'src/pkjs/index.js') == ('pkjs', 'index.js')
    # A bare name has no directory to read a target from.
    assert cpc.split_path('native', 'main.c') == (None, 'main.c')


def test_a_new_pkjs_file_is_created_as_pkjs():
    c = _recording([
        ('project/7/info', FakeResponse({'type': 'native', 'source_files': []})),
        ('create_source_file', FakeResponse({'file': {'id': 4}})),
    ])
    c.write_file('src/pkjs/index.js', 'var x = 1;')
    method, url, data, _files = c.session.calls[-1]
    assert data == {'name': 'index.js', 'target': 'pkjs', 'content': 'var x = 1;'}


def test_a_binary_path_is_refused_with_a_pointer_to_the_right_tool():
    c = _client([
        ('project/7/info', FakeResponse({'type': 'native', 'source_files': []})),
    ])
    try:
        c.write_file('src/c/logo.png', 'not text')
    except CloudPebbleError as e:
        assert 'write_binary_file' in str(e)
    else:
        raise AssertionError('expected CloudPebbleError')


def test_a_new_resource_gets_an_identifier_derived_from_its_name():
    c = _recording([
        ('project/7/info', FakeResponse({'type': 'native', 'resources': []})),
        ('create_resource', FakeResponse({'file': {'id': 3, 'identifiers': ['SPACE_BG']}})),
    ])
    resource, replaced = c.write_resource('space-bg.png', 'png', b'\x89PNG')
    assert replaced is False
    _method, _url, data, files = c.session.calls[-1]
    assert json.loads(data['resource_ids']) == [{'id': 'SPACE_BG'}]
    assert data['kind'] == 'png'
    assert 'file' in files


def test_replacing_a_resource_keeps_the_ids_the_code_already_uses():
    existing = {'id': 3, 'file_name': 'bg.png', 'identifiers': ['IMAGE_BG'],
                'extra': {'IMAGE_BG': {'memory_format': '8Bit'}}}
    c = _recording([
        ('project/7/info', FakeResponse({'type': 'native', 'resources': [existing]})),
        ('resource/3/update', FakeResponse({'file': {'id': 3, 'identifiers': ['IMAGE_BG']}})),
    ])
    _resource, replaced = c.write_resource('bg.png', 'png', b'new bytes')
    assert replaced is True
    _method, _url, data, _files = c.session.calls[-1]
    assert json.loads(data['resource_ids']) == [{'memory_format': '8Bit', 'id': 'IMAGE_BG'}]


def test_an_unknown_resource_kind_is_refused_before_the_upload():
    c = _client([])
    try:
        c.write_resource('x.png', 'jpeg', b'')
    except CloudPebbleError as e:
        assert 'unknown resource kind' in str(e)
    else:
        raise AssertionError('expected CloudPebbleError')


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok  %s' % name)
    print('PASSED')
