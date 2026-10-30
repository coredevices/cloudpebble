import gevent.monkey; gevent.monkey.patch_all(subprocess=True)
import socket
import base64
import tempfile
import json
import subprocess
import sys
import requests
import hmac
import hashlib
import gevent
import requests.exceptions
import shutil
import time
import os

from symbol_blacklist import is_valid_symbol
import settings
from filesync import FileSync

__author__ = 'katharine'


class YCM(object):
    def __init__(self, files, platform='aplite'):
        assert isinstance(files, FileSync)
        self.files = files
        self.platform = platform
        self._port = self._get_port()
        self._secret = os.urandom(16)
        self._spawn()
        self._update_ping()
        self.wait()

    def _spawn(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            ycmd_settings = json.load(open(settings.YCMD_SETTINGS))
            ycmd_settings['hmac_secret'] = base64.b64encode(self._secret).decode('ascii')
            # Never auto-load extra confs: the server's own conf is force-loaded via
            # apply_settings(); any other .ycm_extra_conf.py raises instead of running.
            ycmd_settings['confirm_extra_conf'] = 1
            ycmd_settings['extra_conf_globlist'] = []
            json.dump(ycmd_settings, f)
            options_file = f.name
        env = os.environ.copy()
        env['PLATFORM'] = self.platform
        self._process = subprocess.Popen([
            sys.executable, settings.YCMD_BINARY,
            '--idle_suicide_seconds', '300',
            '--port', str(self._port),
            '--options_file', options_file
        ], cwd=self.files.root_dir, env=env)

    def apply_settings(self, file):
        self._request('load_extra_conf_file', {'filepath': file})

    def go_to(self, path, line, ch):
        path = self.files.abs_path(path)
        with open(path) as f:
            request = {
                'command_arguments': ['GoTo'],
                'filepath': path,
                'line_num': line + 1,
                'column_num': ch + 1,
                'file_data': {
                    path: {
                        'contents': f.read(),
                        'filetypes': ['c'],
                    }
                }
            }
        result = self._request('run_completer_command', request)
        if result.status_code != 200:
            return None
        location = result.json()
        filepath = location['filepath']
        if filepath.startswith(self.files.root_dir):
            filepath = filepath[len(self.files.root_dir)+1:]
        else:
            return None
        return {
            'filepath': filepath,
            'line': location['line_num'] - 1,
            'ch': location['column_num'] - 1,
        }

    def parse(self, filepath, line, ch):
        self._update_ping()
        path = self.files.abs_path(filepath)
        with open(path) as f:
            request = {
                'event_name': 'FileReadyToParse',
                'filepath': path,
                'line_num': line + 1,
                'column_num': ch + 1,
                'file_data': {
                    path: {
                        'contents': f.read(),
                        'filetypes': ['c']
                    }
                }
            }
        result = self._request("event_notification", request)
        try:
            return result.json()
        except:
            return None

    def ping(self):
        self._update_ping()
        headers = {
            'X-Ycm-Hmac': self._request_hmac('GET', '/healthy', ''),
        }
        return requests.get("http://localhost:%d/healthy" % self._port, headers=headers).status_code == 200

    def get_completions(self, filepath, line, ch):
        self._update_ping()
        path = self.files.abs_path(filepath)
        with open(path) as f:
            request = {
                'column_num': ch + 1,
                'line_num': line + 1,
                'filepath': path,
                'file_data': {
                    path: {
                        'contents': f.read(),
                        'filetypes': ['c']
                    }
                },
                'force_semantic': True,
            }

        result = self._request("completions", request)
        if result.status_code == 200:
            response = result.json()
            completions = list(map(self._clean_symbol, list(filter(is_valid_symbol, response['completions']))[:10]))
            return {
                'completions': completions,
                'completion_start_column': response['completion_start_column'],
            }
        else:
            return None

    def wait(self):
        while True:
            try:
                gevent.sleep(0.1)
                headers = {
                    'X-Ycm-Hmac': self._request_hmac('GET', '/ready', ''),
                }
                result = requests.get("http://localhost:%d/ready" % self._port, headers=headers)
                print(result)
            except requests.exceptions.ConnectionError:
                pass
            else:
                if 200 <= result.status_code < 300 and result.json():
                    return True

    def _content_hmac(self, content):
        if isinstance(content, str):
            content = content.encode('utf-8')
        return hmac.new(self._secret, content, hashlib.sha256).digest()

    def _request_hmac(self, method, path, body):
        if isinstance(method, str):
            method = method.encode('utf-8')
        if isinstance(path, str):
            path = path.encode('utf-8')
        if isinstance(body, str):
            body = body.encode('utf-8')
        method_hmac = self._content_hmac(method)
        path_hmac = self._content_hmac(path)
        body_hmac = self._content_hmac(body)
        joined = method_hmac + path_hmac + body_hmac
        return base64.b64encode(
            self._content_hmac(joined)
        ).decode('ascii')

    def _request(self, endpoint, data=None):
        body = json.dumps(data)
        path = '/%s' % endpoint
        headers = {
            'X-Ycm-Hmac': self._request_hmac('POST', path, body),
            'Content-Type': 'application/json',
        }
        return requests.post("http://localhost:%d%s" % (self._port, path), body, headers=headers)

    def _update_ping(self):
        self._last_ping = time.time()

    @property
    def alive(self):
        return time.time() < self._last_ping + 280

    def close(self):
        print("terminating server")
        try:
            self._process.terminate()
        except Exception as e:
            print("Error terminating process: %s" % e)
        try:
            shutil.rmtree(self.files.root_dir)
        except:
            pass

    @staticmethod
    def _get_port():
        # Get a temporary socket by binding to an unspecified one, getting the number, and unbinding.
        # (There is a race condition here if you create lots of ports...)
        sock = socket.socket()
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    @staticmethod
    def _clean_symbol(sym):
        sym = sym.copy()
        sym['detailed_info'] = sym['detailed_info'].split("\n")[0]
        return sym
