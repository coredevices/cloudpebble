#!/usr/bin/env python
__author__ = 'katharine'

import gevent.monkey
gevent.monkey.patch_all(subprocess=True)
import gevent
import gevent.pool
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from time import time as now
import hmac
import ssl
import os
import pwd
import grp
import subprocess
import sys
import urllib.error
import urllib.request

from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
import geventwebsocket
import websocket

import settings
import config_proxy
from emulator import Emulator
from uuid import uuid4, UUID
import logging
import atexit

app = Flask(__name__)
cors = CORS(app, headers=["X-Requested-With", "X-CSRFToken", "Content-Type"], resources="/qemu/*")
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(asctime)s: %(message)s")

import geventwebsocket as _gws
logging.info("gevent-websocket version: %s", getattr(_gws, '__version__', 'unknown'))

emulators = {}

@app.before_request
def log_request():
    logging.debug("REQUEST: %s %s", request.method, request.path)

@app.route('/qemu/launch', methods=['POST'])
def launch():
    supplied = request.headers.get('authorization', '').encode()
    if not any(hmac.compare_digest(supplied, h.encode()) for h in settings.LAUNCH_AUTH_HEADERS):
        abort(403)
    if len(emulators) >= settings.EMULATOR_LIMIT:
        abort(503)
    uuid = uuid4()
    if '/' in request.form['platform'] or '/' in request.form['version']:
        abort(400)
    client_ip = request.form.get('client_ip', '')
    logging.info("GEOLOC controller received client_ip=%r from web", client_ip)
    emu = Emulator(
        request.form['token'],
        request.form['platform'],
        request.form['version'],
        tz_offset=(int(request.form['tz_offset']) if 'tz_offset' in request.form else None),
        oauth=request.form.get('oauth', None),
        client_ip=client_ip
    )
    emulators[uuid] = emu
    emu.last_ping = now()
    emu.run()
    return jsonify(uuid=uuid, ws_port=emu.ws_port, vnc_display=emu.vnc_display, vnc_ws_port=emu.vnc_ws_port)

@app.route('/qemu/<emu>/ping', methods=['POST'])
def ping(emu):
    try:
        emu = UUID(emu)
    except ValueError:
        abort(404)
    if emu not in emulators:
        return jsonify(alive=False)
    if emulators[emu].is_alive():
        emulators[emu].last_ping = now()
        return jsonify(alive=True)
    else:
        try:
            emulators[emu].kill()
        except:
            logging.exception("failed to kill emulator")
            pass
        else:
            del emulators[emu]
        return jsonify(alive=False)


@app.route('/qemu/<emu>/kill', methods=['POST'])
def kill(emu):
    try:
        emu = UUID(emu)
    except ValueError:
        abort(404)
    if emu in emulators:
        try:
            emulators[emu].kill()
        except Exception:
            logging.exception("failed to kill")
        else:
            del emulators[emu]
    return jsonify(status='ok')


def proxy_ws(emu, attr, subprotocols=[], path='/', text=False, close_together=False):
    """Relay a browser WebSocket to one of the emulator's own. Frames go on as binary unless
    `text`, which keeps each frame's own type (for JSON protocols the browser reads as text).
    `close_together` ends the relay as soon as either side goes, so the target sees the browser
    leave; otherwise it lasts until both have."""
    server_ws = request.environ.get('wsgi.websocket', None)
    if server_ws is None:
        logging.warning("proxy_ws: no wsgi.websocket in environ for %s", attr)
        return "websocket endpoint", 400

    try:
        emulator = emulators[UUID(emu)]
    except (ValueError, KeyError):
        logging.warning("proxy_ws: emulator %s not found", emu)
        abort(404)
        return  # unreachable but makes IDE happy.
    target_url = "ws://localhost:%d%s" % (getattr(emulator, attr), path)
    logging.info("proxy_ws: connecting to %s (attr=%s)", target_url, attr)
    # The target (notably pypkjs) may still be booting when the browser
    # connects, so retry connection-refused for a while before giving up.
    deadline = now() + 10
    while True:
        try:
            client_ws = websocket.create_connection(target_url, subprotocols=subprotocols)
            break
        except ConnectionRefusedError:
            if now() >= deadline:
                logging.exception("proxy_ws: connection to %s refused until deadline.", target_url)
                return 'failed', 500
            gevent.sleep(0.25)
        except:
            logging.exception("proxy_ws: connection to %s failed.", target_url)
            return 'failed', 500
    logging.info("proxy_ws: connected to %s, starting relay", target_url)
    alive = [True]
    def do_recv(direction, receive, send):
        try:
            count = 0
            while alive[0]:
                data = receive()
                if data is None:
                    logging.info("proxy_ws: %s received None, closing", direction)
                    alive[0] = False
                    break
                count += 1
                send(data)
            logging.info("proxy_ws: %s loop ended after %d messages", direction, count)
        except (websocket.WebSocketException, geventwebsocket.WebSocketError, TypeError) as e:
            logging.info("proxy_ws: %s ended with %s: %s after %d messages", direction, type(e).__name__, e, count)
            alive[0] = False
        except Exception as e:
            logging.exception("proxy_ws: %s unexpected error after %d messages", direction, count)
            alive[0] = False
            raise

    def to_target(data):
        if text and isinstance(data, str):
            client_ws.send(data)
        else:
            client_ws.send_binary(data)

    def from_target():
        data = client_ws.recv()
        return data if text and isinstance(data, str) else bytearray(data)

    group = gevent.pool.Group()
    group.spawn(do_recv, "browser->target", lambda: server_ws.receive(), to_target)
    group.spawn(do_recv, "target->browser", from_target, lambda x: server_ws.send(x))
    if close_together:
        # Either reader finishing closes both sockets, which ends the other reader too.
        def close_both(greenlet):
            for close in (client_ws.close, server_ws.close):
                try:
                    close()
                except Exception:
                    pass
        for greenlet in group:
            greenlet.link(close_both)
    group.join()
    logging.info("proxy_ws: relay ended for %s", target_url)
    return ''

app.app_protocol = lambda x: 'binary' if 'vnc' in x else None

@app.route('/qemu/<emu>/ws/phone')
def ws_phone(emu):
    logging.info("ws_phone called for emu=%s", emu)
    try:
        return proxy_ws(emu, 'ws_port')
    except Exception:
        logging.exception("ws_phone crashed")
        return 'error', 500

@app.route('/qemu/<emu>/ws/vnc')
def ws_vnc(emu):
    logging.info("ws_vnc called for emu=%s", emu)
    try:
        return proxy_ws(emu, 'vnc_ws_port', subprotocols=['binary'])
    except Exception:
        logging.exception("ws_vnc crashed")
        return 'error', 500


def _config_page_emulator(emu, uuid):
    """The emulator a settings-page request is for, once its token and the pbw uuid check out."""
    try:
        emulator = emulators[UUID(emu)]
        UUID(uuid)
    except (ValueError, KeyError):
        abort(404)
    token = request.args.get('token', '')
    if not token or not hmac.compare_digest(token.encode('utf-8'),
                                            (emulator.token or '').encode('utf-8')):
        logging.warning("config page: bad token for emu=%s", emu)
        abort(403)
    return emulator


@app.route('/qemu/<emu>/config/<uuid>/')
def config_page(emu, uuid):
    """An installed pbw's settings page, as the emulator's phone simulator serves it."""
    emulator = _config_page_emulator(emu, uuid)
    try:
        with urllib.request.urlopen('http://localhost:%d/config/%s/' % (emulator.ws_port, uuid),
                                    timeout=30) as response:
            html = response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logging.warning("config page: phone simulator answered %d for %s", e.code, uuid)
            return "The phone simulator could not serve this settings page.", 502
        return ("No settings page for this app is installed on the emulator. "
                "Install a build that has one, then try again."), 404
    except OSError:
        logging.exception("config page: phone simulator unreachable")
        return "The phone simulator is not running.", 502
    html, found = config_proxy.rewrite_bridge(html, uuid)
    if not found:
        logging.warning("config page: no bridge path to rewrite for %s", uuid)
    return html, 200, config_proxy.PAGE_HEADERS


@app.route('/qemu/<emu>/config/<uuid>/bridge')
def config_bridge(emu, uuid):
    """The settings page's live connection to its pbw's scripts."""
    _config_page_emulator(emu, uuid)
    try:
        return proxy_ws(emu, 'ws_port', path='/config/%s/bridge' % uuid, text=True, close_together=True)
    except Exception:
        logging.exception("config_bridge crashed")
        return 'error', 500


@app.route('/qemu/<emu>/ws/audio')
def ws_audio(emu):
    """Fallback audio path. Streams raw s16le 16kHz mono PCM frames over a
    WebSocket — used when WebRTC ICE can't establish a direct UDP path.
    Sources from the same per-emulator pulseaudio null-sink monitor that
    aiortc reads from; multiple parec readers on the same monitor source
    is supported by pulseaudio."""
    logging.info("ws_audio called for emu=%s", emu)
    server_ws = request.environ.get('wsgi.websocket', None)
    if server_ws is None:
        return "websocket endpoint", 400
    try:
        emulator = emulators[UUID(emu)]
    except (ValueError, KeyError):
        return "not found", 404
    # Unlike VNC/phone, this endpoint had no credential check.
    token = request.args.get('token', '')
    if not token or not hmac.compare_digest(token.encode('utf-8'),
                                            (emulator.token or '').encode('utf-8')):
        logging.warning("ws_audio: bad token for emu=%s", emu)
        return "forbidden", 403
    if emulator.platform not in ('emery', 'flint') or not emulator.audio_sink:
        return "no audio for this platform", 400

    sink = emulator.audio_sink
    proc = None
    try:
        proc = subprocess.Popen([
            'parec',
            '--device=' + sink + '.monitor',
            '--rate=16000',
            '--channels=1',
            '--format=s16le',
            '--latency-msec=20',
            '--raw',
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        # 20ms @ 16kHz s16le mono = 640 bytes. parec may return short reads;
        # we send whatever we get to keep latency low.
        while True:
            chunk = proc.stdout.read(640)
            if not chunk:
                break
            try:
                server_ws.send(chunk)
            except (geventwebsocket.WebSocketError, OSError):
                break
    except Exception:
        logging.exception("ws_audio: stream error")
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
    logging.info("ws_audio: closed for emu=%s", emu)
    return ''


def _kill_idle_emulators():
    try:
        while True:
            try:
                logging.info("STATS active_sessions=%d", len(emulators))
                to_kill = []
                for key, emulator in list(emulators.items()):
                    logging.debug("checking %s", key)
                    if now() - emulator.last_ping > 300:
                        to_kill.append(key)
                    else:
                        logging.debug("okay; last ping: %s", emulator.last_ping)
                for key in to_kill:
                    logging.info("killing idle emulator %s", key)
                    try:
                        emulators[key].kill()
                    except Exception:
                        logging.exception("failed to kill emulator %s", key)
                    del emulators[key]
                if to_kill:
                    logging.info("killed %d idle emulators", len(to_kill))
            except Exception:
                logging.exception('Failed to kill idle emulator')
            sys.stdout.flush()
            gevent.sleep(60)
    except Exception:
        logging.exception("IDLE EMULATOR WATCHDOG DIED. %d emulators were running.", len(emulators))
        raise

idle_killer = gevent.spawn(_kill_idle_emulators)

@atexit.register
def kill_emulators():
    for emulator in emulators.values():
        emulator.kill()
    emulators.clear()


def drop_privileges(uid_name='nobody', gid_name='nogroup'):
    if os.getuid() != 0:
        # We're not root so, like, whatever dude
        return

    # Get the uid/gid from the name
    running_uid = pwd.getpwnam(uid_name).pw_uid
    running_gid = grp.getgrnam(gid_name).gr_gid

    # Remove group privileges
    os.setgroups([])

    # Try setting the new uid/gid
    os.setgid(running_gid)
    os.setuid(running_uid)

    # Ensure a very conservative umask
    os.umask(0o77)

logging.info("Emulator limit: %d", settings.EMULATOR_LIMIT)

class WebSocketFixMiddleware(object):
    """Werkzeug 2.x+ has WebSocket-aware routing that rejects WS requests
    to non-WebSocket routes with 400. Since we use gevent-websocket which
    handles the upgrade before Flask sees the request, we strip the Upgrade
    header so Werkzeug treats it as a normal GET. The actual WebSocket
    object remains available in environ['wsgi.websocket']."""
    def __init__(self, app):
        self._app = app
        if hasattr(app, 'app_protocol'):
            self.app_protocol = app.app_protocol
    def __call__(self, environ, start_response):
        if environ.get('wsgi.websocket') is not None:
            environ.pop('HTTP_UPGRADE', None)
            environ.pop('HTTP_CONNECTION', None)
        return self._app(environ, start_response)

class TokenRedactingHandler(WebSocketHandler):
    """The settings-page and audio endpoints take the emulator token in the query string, which
    the access log would otherwise record."""
    def format_request(self):
        return config_proxy.redact_token(super().format_request())


if __name__ == '__main__':
    app.debug = settings.DEBUG
    ssl_args = {}
    if settings.SSL_ROOT is not None:
        ssl_args = {
            'keyfile': '%s/server-key.pem' % settings.SSL_ROOT,
            'certfile': '%s/server-cert.pem' % settings.SSL_ROOT,
            'ca_certs': '%s/ca-cert.pem' % settings.SSL_ROOT,
            'ssl_version': ssl.PROTOCOL_TLSv1_2,
            'ciphers': 'EECDH+ECDSA+AESGCM EECDH+aRSA+AESGCM EECDH+ECDSA+SHA384 EECDH+ECDSA+SHA256 EECDH+aRSA+SHA384 EECDH+aRSA+SHA256 EECDH+aRSA+RC4 EECDH EDH+aRSA RC4 !aNULL !eNULL !LOW !3DES !MD5 !EXP !PSK !SRP !DSS !RC4',
        }
    ws_app = WebSocketFixMiddleware(app)
    server = pywsgi.WSGIServer(('', settings.PORT), ws_app, handler_class=TokenRedactingHandler, **ssl_args)
    server.start()
    if settings.RUN_AS_USER is not None:
        drop_privileges(settings.RUN_AS_USER, settings.RUN_AS_USER)
    server.serve_forever()
