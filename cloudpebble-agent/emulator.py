"""Drive a CloudPebble qemu emulator over its phone websocket.

Ported from the verified phase-0 spike (_spike_emulator_VERIFIED.py). The framing
below is reverse-engineered from ide/static/ide/js/libpebble/{proxysocket,libpebble}.js
and was proven end to end against cloudpebble-dev over public wss.

Three gotchas, kept deliberately:
  1. /qemu/launch returns before pypkjs is listening. We never launch -- the browser
     did that -- so instead of sleeping we retry the attach for BOOT_TIMEOUT.
  2. Don't re-dial an emulator that already had a client if you can avoid it: it can
     hang at the auth frame with no error. Hence the process-wide _CONNS registry --
     we attach once and reuse. A connection that dies is evicted and re-attached
     exactly once; an attach that *fails* is remembered for FAILURE_TTL so a model
     calling install/screenshot/logs in a row doesn't spend minutes re-dialling.
  3. Inbound frames are 0x00. 0x01 is outbound only.
"""

import logging
import os
import struct
import threading
import time
import zlib

import websocket

logger = logging.getLogger(__name__)

OP_FROM_WATCH = 0x00
OP_TO_WATCH = 0x01
OP_PHONE_LOG = 0x02
OP_INSTALL = 0x04
OP_INSTALL_STATUS = 0x05
OP_CONNECTION = 0x08
OP_AUTH = 0x09
# QEMU control channel: 0x0b <protocol> <payload>. Same socket as everything else
# (libpebble.js:send_qemu_command).
OP_QEMU = 0x0b

QEMU_TAP = 2
QEMU_BUTTON = 8

# Button *bits*, as libpebble2's QemuButton.Button enumerates them. The payload is
# the set of buttons currently held, so a press is "bit set", a release is 0.
BUTTONS = {'back': 1, 'up': 2, 'select': 4, 'down': 8}

# Accelerometer axes for a tap, matching pebble's own x/y/z ordering.
TAP_AXES = {'x': 0, 'y': 1, 'z': 2}

ENDPOINT_LOGS = 2000
ENDPOINT_APP_LOGS = 2006
ENDPOINT_APP_MANAGER = 6000
ENDPOINT_SCREENSHOT = 8000
ENDPOINT_PUTBYTES = 48879

# How long to keep retrying the attach. pypkjs can bind its port ~10s after the
# browser's /qemu/launch returns, so a user who clicks Launch and immediately sends a
# message needs more than one attempt -- hence a connect timeout well inside this.
BOOT_TIMEOUT = int(os.environ.get('AGENT_EMULATOR_BOOT_TIMEOUT', '60'))
CONNECT_TIMEOUT = 10
RETRY_DELAY = 3
# How long a failed attach is remembered, so the next tool call fails in milliseconds
# instead of re-dialling. Short enough that launching an emulator mid-turn recovers.
FAILURE_TTL = 60

LOG_LEVELS = {0: 'ERROR', 1: 'ERROR', 50: 'WARN', 100: 'INFO', 200: 'DEBUG', 250: 'VERBOSE'}

# The panel-corrected palette the IDE renders these frames through
# (libpebble.js:decode_image_8bit_corrected). The naive 2-bits-per-channel x85 map is a
# different picture -- index 0x30 is pure red there and a muted maroon here -- and the
# whole point of screenshot() is the model judging colours the user will actually see.
COLOUR_MAP = (
    0x000000, 0x001e41, 0x004387, 0x0068ca, 0x2b4a2c, 0x27514f, 0x16638d, 0x007dce,
    0x5e9860, 0x5c9b72, 0x57a5a2, 0x4cb4db, 0x8ee391, 0x8ee69e, 0x8aebc0, 0x84f5f1,
    0x4a161b, 0x482748, 0x40488a, 0x2f6bcc, 0x564e36, 0x545454, 0x4f6790, 0x4180d0,
    0x759a64, 0x759d76, 0x71a6a4, 0x69b5dd, 0x9ee594, 0x9de7a0, 0x9becc2, 0x95f6f2,
    0x99353f, 0x983e5a, 0x955694, 0x8f74d2, 0x9d5b4d, 0x9d6064, 0x9a7099, 0x9587d5,
    0xafa072, 0xaea382, 0xababab, 0xa7bae2, 0xc9e89d, 0xc9eaa7, 0xc7f0c8, 0xc3f9f7,
    0xe35462, 0xe25874, 0xe16aa3, 0xde83dc, 0xe66e6b, 0xe6727c, 0xe37fa7, 0xe194df,
    0xf1aa86, 0xf1ad93, 0xefb5b8, 0xecc3eb, 0xffeeab, 0xfff1b5, 0xfff6d3, 0xffffff,
)

# Per-row pixels clipped by the round display's bezel, top half; mirrored for the
# bottom. From libpebble.js:roundify. Chalk only (180px wide).
ROUNDNESS = (76, 71, 66, 63, 60, 57, 55, 52, 50, 48, 46, 45, 43, 41, 40, 38, 37,
             36, 34, 33, 32, 31, 29, 28, 27, 26, 25, 24, 23, 22, 22, 21, 20, 19,
             18, 18, 17, 16, 15, 15, 14, 13, 13, 12, 12, 11, 10, 10, 9, 9, 8, 8, 7,
             7, 7, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


class NoEmulator(Exception):
    """No usable emulator. Typed so the model reports it instead of retrying."""


# ---------------------------------------------------------------------------
# pure framing helpers (unit-tested in test_emulator_framing.py)
# ---------------------------------------------------------------------------

def auth_frame(token):
    tok = token.encode() if isinstance(token, str) else token
    return bytes([OP_AUTH, len(tok)]) + tok


def to_watch(endpoint, payload):
    """0x01 <size:BE16> <endpoint:BE16> <payload> -- message *to* the watch."""
    return bytes([OP_TO_WATCH]) + struct.pack('>HH', len(payload), endpoint) + payload


def parse_inbound(frame):
    """(opcode, endpoint, payload). endpoint is None for non-0x00 opcodes."""
    if not isinstance(frame, bytes) or not frame:
        return None, None, b''
    op = frame[0]
    if op == OP_FROM_WATCH:
        if len(frame) < 5:
            return op, None, b''
        size, endpoint = struct.unpack('>HH', frame[1:5])
        return op, endpoint, frame[5:5 + size]
    return op, None, frame[1:]


def decode_app_log(payload):
    """APP_LOGS payload: 16b uuid, >IBBH (ts, level, msglen, line), 16b filename, msg.

    Layout taken from libpebble.js:handle_app_log.
    """
    if len(payload) < 40:
        return payload.decode('utf-8', 'replace').strip()
    timestamp, level, msg_len, line = struct.unpack('>IBBH', payload[16:24])
    filename = payload[24:40].split(b'\x00')[0].decode('utf-8', 'replace')
    message = payload[40:40 + msg_len].decode('utf-8', 'replace')
    return '[%s] %s:%d %s' % (LOG_LEVELS.get(level, level), filename, line, message)


def screenshot_header(data):
    """(version, width, height, expected_pixel_bytes, remaining_data)."""
    code, version, width, height = struct.unpack('>BIII', data[:13])
    if code != 0:
        raise NoEmulator('watch returned screenshot error code %d' % code)
    if version not in (1, 2):
        raise NoEmulator('unknown screenshot format version %d' % version)
    expected = width * height // 8 if version == 1 else width * height
    return version, width, height, expected, data[13:]


def screenshot_png(version, width, height, pixels):
    rows = []
    if version == 1:
        stride = width // 8
        for y in range(height):
            row = bytearray()
            for x in range(width):
                bit = (pixels[y * stride + x // 8] >> (x % 8)) & 1
                row += bytes([bit * 255]) * 3
            rows.append(bytes(row))
    else:
        for y in range(height):
            row = bytearray()
            for x in range(width):
                c = COLOUR_MAP[pixels[y * width + x] & 63]
                row += bytes([(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF])
            rows.append(bytes(row))
    if width == 180:
        rows = _roundify(rows)
    return encode_png(width, height, rows)


def _roundify(rows):
    """Black out the corners the round (chalk) display clips, so the model doesn't
    try to fix layout in pixels the user cannot see."""
    skips = list(ROUNDNESS) + list(reversed(ROUNDNESS))
    out = []
    for y, row in enumerate(rows):
        skip = skips[y] if y < len(skips) else 0
        if skip:
            row = bytearray(row)
            row[:skip * 3] = b'\x00' * (skip * 3)
            row[-skip * 3:] = b'\x00' * (skip * 3)
            row = bytes(row)
        out.append(row)
    return out


def encode_png(width, height, rows):
    raw = b''.join(b'\x00' + r for r in rows)

    def chunk(tag, body):
        return (struct.pack('>I', len(body)) + tag + body
                + struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


def ws_url(base_url, uuid):
    url = base_url.rstrip('/').replace('https://', 'wss://').replace('http://', 'ws://')
    return '%s/qemu/%s/ws/phone' % (url, uuid)


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------

class Emulator(object):
    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.ws = None
        # Set once a send/recv fails. get_emulator evicts dead connections rather than
        # returning one that will fail forever.
        self.dead = False
        self.lock = threading.Lock()

    def connect(self, boot_timeout=BOOT_TIMEOUT):
        deadline = time.time() + boot_timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                self.ws = self._handshake()
                self._send(to_watch(ENDPOINT_APP_LOGS, b'\x01'))  # enable app logs
                return self
            except (websocket.WebSocketException, OSError) as e:
                if time.time() >= deadline:
                    raise NoEmulator('emulator never came up after %d attempts: %s' % (attempt, e))
                logger.info('emulator not ready (%s), retrying', type(e).__name__)
                time.sleep(RETRY_DELAY)

    def _handshake(self):
        # Well inside BOOT_TIMEOUT, so the retry loop above can actually retry.
        ws = websocket.create_connection(self.url, timeout=CONNECT_TIMEOUT)
        try:
            ws.send_binary(auth_frame(self.token))
            deadline = time.time() + CONNECT_TIMEOUT
            while time.time() < deadline:
                op, _, rest = parse_inbound(ws.recv())
                if op == OP_AUTH:
                    if rest[:1] != b'\x00':
                        raise NoEmulator('emulator rejected the auth token')
                elif op == OP_CONNECTION:
                    if rest[:1] == b'\xff':
                        return ws
                    if rest[:1] == b'\x00':
                        raise websocket.WebSocketException('proxy closed connection remotely')
            raise websocket.WebSocketException('timed out waiting for watch connect')
        except BaseException:
            # Leaving the socket open would register another authed client in pypkjs's
            # broadcast list for every failed attempt.
            try:
                ws.close()
            except Exception:
                pass
            raise

    def _lost(self, e):
        self.dead = True
        return NoEmulator('emulator connection lost: %s' % e)

    def _send(self, frame):
        try:
            self.ws.send_binary(frame)
        except (websocket.WebSocketException, OSError) as e:
            raise self._lost(e)

    def _recv(self, timeout):
        self.ws.settimeout(max(timeout, 0.1))
        try:
            return parse_inbound(self.ws.recv())
        except websocket.WebSocketProtocolException as e:
            # A socket timeout can fire mid-frame, leaving websocket-client's frame
            # buffer desynced so every later recv misparses. Fatal, not ignorable.
            raise self._lost('frame desync: %s' % e)
        except websocket.WebSocketTimeoutException:
            return None, None, b''
        except (websocket.WebSocketException, OSError) as e:
            raise self._lost(e)

    def screenshot(self, timeout=60):
        with self.lock:
            self._send(to_watch(ENDPOINT_SCREENSHOT, b'\x00'))
            buf, expected, meta = b'', None, None
            deadline = time.time() + timeout
            while time.time() < deadline:
                op, endpoint, data = self._recv(deadline - time.time())
                if op != OP_FROM_WATCH or endpoint != ENDPOINT_SCREENSHOT:
                    continue
                if meta is None:
                    version, width, height, expected, data = screenshot_header(data)
                    meta = (version, width, height)
                buf += data
                if len(buf) >= expected:
                    return screenshot_png(meta[0], meta[1], meta[2], buf[:expected])
            raise NoEmulator('timed out collecting screenshot (%d/%s bytes)' % (len(buf), expected))

    def press_button(self, button, hold_ms=120):
        """Hold a watch button down and let go.

        The emulator takes the set of buttons currently held, so this is
        "set the bit, wait, send zero" -- exactly what the IDE's own buttons do
        on mousedown/mouseup.
        """
        bit = BUTTONS[button]
        with self.lock:
            self._send(bytes([OP_QEMU, QEMU_BUTTON, bit]))
            time.sleep(max(0.02, min(hold_ms, 5000) / 1000.0))
            self._send(bytes([OP_QEMU, QEMU_BUTTON, 0]))

    def tap(self, axis='y', direction=1):
        """Shake the watch: one accelerometer tap along an axis."""
        with self.lock:
            self._send(bytes([OP_QEMU, QEMU_TAP, TAP_AXES[axis],
                              1 if direction >= 0 else 0xFF]))

    def enable_app_logs(self):
        """Ask the watch to start shipping APP_LOG output.

        Nothing arrives until this is sent -- the browser does it after every
        install (see libpebble.js enable_app_logs), and without it `logs()`
        returns nothing at all no matter what the app prints. That left the model
        debugging an AppMessage round trip blind, and it shipped an offline demo
        rather than the live data it had been asked for.
        """
        with self.lock:
            self._send(to_watch(ENDPOINT_APP_LOGS, b'\x01'))

    def install(self, pbw, timeout=180):
        with self.lock:
            self._send(bytes([OP_INSTALL]) + pbw)
            deadline = time.time() + timeout
            while time.time() < deadline:
                op, _, data = self._recv(deadline - time.time())
                if op == OP_INSTALL_STATUS and len(data) >= 4:
                    return struct.unpack('>I', data[:4])[0]
            raise NoEmulator('timed out waiting for install to finish')

    def logs(self, seconds):
        with self.lock:
            out = []
            deadline = time.time() + seconds
            while time.time() < deadline:
                op, endpoint, data = self._recv(deadline - time.time())
                if op == OP_PHONE_LOG:
                    out.append(data.decode('utf-8', 'replace').strip())
                elif op == OP_FROM_WATCH and endpoint in (ENDPOINT_APP_LOGS, ENDPOINT_LOGS):
                    out.append(decode_app_log(data))
            return out

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


# One connection per emulator, process wide, because the same emulator survives across
# turns (gotcha 2).
# ponytail: unbounded dicts, one entry per emulator the box ever talked to, and the lock
# is held across the attach. Add an LRU sweep and a per-uuid lock if this service ever
# runs more than a handful of concurrent sessions.
_CONNS = {}
_FAILURES = {}
_CONNS_LOCK = threading.Lock()


def get_emulator(spec, cp_base_url):
    """spec is the `emulator` field of /turn: {uuid, token, ws_url?}.

    ws_url is built by Django from QEMU_PUBLIC_URL, never by the browser -- see
    ide/api/agent.py:_emulator_spec. There is deliberately no other way to point this
    at a host of the caller's choosing.
    """
    if not spec or not spec.get('uuid') or not spec.get('token'):
        raise NoEmulator('no emulator is running -- open the emulator in CloudPebble first')
    uuid = spec['uuid']
    with _CONNS_LOCK:
        conn = _CONNS.get(uuid)
        if conn is not None and conn.dead:
            # pypkjs broadcasts to every authed socket and the controller opens a fresh
            # connection per client, so a second attach is supported. Allow exactly one.
            _CONNS.pop(uuid, None)
            conn.close()
            conn = None
        if conn is not None:
            return conn

        failed_until, failure = _FAILURES.get(uuid, (0, None))
        if failure is not None and time.time() < failed_until:
            # The model will try install, then screenshot, then logs. Without this each
            # one spends BOOT_TIMEOUT re-dialling an emulator that already said no.
            raise failure

        conn = Emulator(spec.get('ws_url') or ws_url(cp_base_url, uuid), spec['token'])
        try:
            conn.connect()
        except NoEmulator as e:
            _FAILURES[uuid] = (time.time() + FAILURE_TTL, e)
            raise
        _FAILURES.pop(uuid, None)
        _CONNS[uuid] = conn
        return conn
