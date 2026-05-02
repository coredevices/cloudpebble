#!/usr/bin/env python
__author__ = 'katharine'

import gevent.monkey
gevent.monkey.patch_all(subprocess=True)
import gevent
import gevent.pool
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from time import time as now
import ssl
import os
import pwd
import grp
import subprocess
import sys

from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
import geventwebsocket
import websocket

import settings
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
    if request.headers.get('authorization', None) != settings.LAUNCH_AUTH_HEADER:
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


def proxy_ws(emu, attr, subprotocols=[]):
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
    target_url = "ws://localhost:%d/" % getattr(emulator, attr)
    logging.info("proxy_ws: connecting to %s (attr=%s)", target_url, attr)
    try:
        client_ws = websocket.create_connection(target_url, subprotocols=subprotocols)
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

    group = gevent.pool.Group()
    group.spawn(do_recv, "browser->target", lambda: server_ws.receive(), lambda x: client_ws.send_binary(x))
    group.spawn(do_recv, "target->browser", lambda: bytearray(client_ws.recv()), lambda x: server_ws.send(x))
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
    server = pywsgi.WSGIServer(('', settings.PORT), ws_app, handler_class=WebSocketHandler, **ssl_args)
    server.start()
    if settings.RUN_AS_USER is not None:
        drop_privileges(settings.RUN_AS_USER, settings.RUN_AS_USER)
    server.serve_forever()
