__author__ = 'katharine'

import gevent
import gevent.pool
import logging
import os
import re
import tempfile
import settings
import shutil
import socket
import subprocess
import itertools
import uuid as _uuid

AUDIO_PLATFORMS = ('emery', 'flint')
_PACTL_MODULE_ID_RE = re.compile(r'^\s*(\d+)\s*$', re.MULTILINE)

_used_displays = set()
def _find_display():
    for i in itertools.count():
        if i not in _used_displays:
            _used_displays.add(i)
            return i

def _free_display(display):
    _used_displays.remove(display)


class Emulator(object):
    def __init__(self, token, platform, version, tz_offset=None, oauth=None, client_ip=''):
        self.token = token
        self.qemu = None
        self.pkjs = None
        self.console_port = None
        self.bt_port = None
        self.ws_port = None
        self.spi_image = None
        self.vnc_display = None
        self.vnc_ws_port = None
        self.group = None
        self.platform = platform
        self.version = version
        self.tz_offset = tz_offset
        self.oauth = oauth
        self.client_ip = client_ip
        self.persist_dir = None
        self.audio_sink = None
        self.audio_module_id = None
        self.audio_client_conf = None

    def run(self):
        self.group = gevent.pool.Group()
        self._choose_ports()
        self._make_spi_image()
        self._load_audio_sink()
        self._spawn_qemu()
        gevent.sleep(4)  # wait for the pebble to boot.
        self._spawn_pkjs()

    def kill(self):
        if self.qemu is not None:
            try:
                self.qemu.kill()
                for i in range(10):
                    gevent.sleep(0.1)
                    if self.qemu.poll() is not None:
                        break
                else:
                    raise Exception("Failed to kill qemu in one second.")
            except OSError as e:
                if e.errno == 3:  # No such process
                    pass
                else:
                    raise
            try:
                os.unlink(self.spi_image.name)
            except OSError:
                pass
        if self.pkjs is not None:
            try:
                self.pkjs.kill()
                for i in range(10):
                    gevent.sleep(0.1)
                    if self.pkjs.poll() is not None:
                        break
                else:
                    raise Exception("Failed to kill pkjs in one second.")
            except OSError as e:
                if e.errno == 3:  # No such process
                    pass
                else:
                    raise
            try:
                shutil.rmtree(self.persist_dir)
            except OSError:
                pass
        if self.audio_sink is not None:
            # Unloading the null-sink also drops its monitor source, which
            # gives EOF to any parec subprocesses serving live WS audio
            # tunnels — they exit and the WS read loop in controller.py
            # closes naturally. No explicit subscriber tracking needed.
            self._unload_audio_sink()
        self.group.kill(block=True)

    def is_alive(self):
        if self.qemu is None or self.pkjs is None:
            return False
        return self.qemu.poll() is None and self.pkjs.poll() is None

    def _choose_ports(self):
        self.console_port = self._find_port()
        self.bt_port = self._find_port()
        self.ws_port = self._find_port()
        self.vnc_display = self._find_port() - 5900
        self.vnc_ws_port = self._find_port()

    def _make_spi_image(self):
        with tempfile.NamedTemporaryFile(delete=False) as spi:
            self.spi_image = spi
            image_dir = self._find_qemu_images()
            bz2_path = image_dir + "qemu_spi_flash.bin.bz2"
            raw_path = image_dir + "qemu_spi_flash.bin"
            if os.path.exists(bz2_path):
                import bz2
                with open(bz2_path, 'rb') as f:
                    spi.write(bz2.decompress(f.read()))
            else:
                with open(raw_path, 'rb') as f:
                    spi.write(f.read())

    def _load_audio_sink(self):
        if self.platform not in AUDIO_PLATFORMS:
            return
        sink_name = 'emu_' + _uuid.uuid4().hex
        try:
            out = subprocess.check_output([
                'pactl', 'load-module', 'module-null-sink',
                'sink_name=' + sink_name,
                'channel_map=mono',
                'rate=16000',
                'format=s16le',
            ], stderr=subprocess.STDOUT, timeout=5).decode().strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logging.exception('audio: pactl load-module failed: %s', getattr(e, 'output', ''))
            return
        m = _PACTL_MODULE_ID_RE.search(out)
        if not m:
            logging.error('audio: unexpected pactl output: %r', out)
            return
        self.audio_sink = sink_name
        self.audio_module_id = int(m.group(1))
        # Per-emulator pulse client.conf as belt-and-suspenders for routing —
        # libpulse uses default-sink from this when QEMU passes dev=NULL.
        self.audio_client_conf = '/tmp/pulse-' + sink_name + '.conf'
        try:
            with open(self.audio_client_conf, 'w') as f:
                f.write('default-sink = ' + sink_name + '\n')
        except OSError:
            logging.exception('audio: failed to write %s', self.audio_client_conf)
            self.audio_client_conf = None
        # Make our sink the server-side default. QEMU's libpulse passes
        # dev=NULL to pa_simple_new, so the server routes to its current
        # default. Concurrent launches race here — last writer wins — but
        # previously-attached streams stay bound to their original sink,
        # so existing emulators keep their routing intact.
        try:
            subprocess.call(['pactl', 'set-default-sink', sink_name], timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            logging.exception('audio: failed to set default sink %s', sink_name)
        logging.info('audio: created null-sink %s module=%s', sink_name, self.audio_module_id)

    def _unload_audio_sink(self):
        if self.audio_module_id is None:
            return
        try:
            subprocess.call(['pactl', 'unload-module', str(self.audio_module_id)], timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            logging.exception('audio: failed to unload %s', self.audio_sink)
        if self.audio_client_conf:
            try:
                os.unlink(self.audio_client_conf)
            except OSError:
                pass
        self.audio_sink = None
        self.audio_module_id = None
        self.audio_client_conf = None


    @staticmethod
    def _find_port():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('localhost', 0))
        addr, port = s.getsockname()
        s.close()
        return port

    def _spawn_qemu(self):
        image_dir = self._find_qemu_images()
        micro_flash = image_dir + "qemu_micro_flash.bin"
        spi_flash = self.spi_image.name

        qemu_args = [
            settings.QEMU_BIN,
            "-rtc", "base=localtime",
            "-kernel", micro_flash,
            "-serial", "null",
            "-serial", "tcp:127.0.0.1:%d,server=on,wait=off" % self.bt_port,   # Bluetooth
            "-serial", "tcp:127.0.0.1:%d,server=on" % self.console_port,        # Console (blocks until connect)
            "-monitor", "stdio",
            "-vnc", ":%d,password=on,websocket=%d" % (self.vnc_display, self.vnc_ws_port),
        ]
        if settings.QEMU_DATA_DIR:
            qemu_args[1:1] = ["-L", settings.QEMU_DATA_DIR]

        # Single rollback toggle: set to False to revert emery/flint/gabbro
        # to their legacy machine names without touching the SDK pin.
        use_new_boards = True

        spi_drive = ['-drive', 'if=none,id=spi-flash,file=%s,format=raw' % spi_flash]
        mtd_args = ['-mtdblock', spi_flash]
        mtd_drive = ['-drive', 'if=mtd,format=raw,file=%s' % spi_flash]
        if self.platform in AUDIO_PLATFORMS and self.audio_sink:
            audio_args = [
                '-audiodev',
                'pa,id=audio0,server=unix:/run/cloudpebble-pipewire/pulse/native',
                '-machine', 'audiodev=audio0',
            ]
        else:
            audio_args = ['-audiodev', 'none,id=audio0', '-machine', 'audiodev=audio0']

        if use_new_boards:
            platform_args = {
                'aplite':  ['-machine', 'pebble-bb2',      '-cpu', 'cortex-m3']  + mtd_args,
                'basalt':  ['-machine', 'pebble-snowy-bb', '-cpu', 'cortex-m4']  + spi_drive,
                'chalk':   ['-machine', 'pebble-s4-bb',    '-cpu', 'cortex-m4']  + spi_drive,
                'diorite': ['-machine', 'pebble-silk-bb',  '-cpu', 'cortex-m4']  + mtd_args,
                'emery':   ['-machine', 'pebble-emery',    '-cpu', 'cortex-m33'] + mtd_drive + audio_args,
                'flint':   ['-machine', 'pebble-flint',    '-cpu', 'cortex-m4']  + mtd_drive + audio_args,
                'gabbro':  ['-machine', 'pebble-gabbro',   '-cpu', 'cortex-m33'] + mtd_drive,
            }
        else:
            platform_args = {
                'aplite':  ['-machine', 'pebble-bb2',                '-cpu', 'cortex-m3'] + mtd_args,
                'basalt':  ['-machine', 'pebble-snowy-bb',           '-cpu', 'cortex-m4'] + spi_drive,
                'chalk':   ['-machine', 'pebble-s4-bb',              '-cpu', 'cortex-m4'] + spi_drive,
                'diorite': ['-machine', 'pebble-silk-bb',            '-cpu', 'cortex-m4'] + mtd_args,
                'emery':   ['-machine', 'pebble-snowy-emery-bb',     '-cpu', 'cortex-m4'] + spi_drive,
                'gabbro':  ['-machine', 'pebble-spalding-gabbro-bb', '-cpu', 'cortex-m4'] + spi_drive,
                'flint':   ['-machine', 'pebble-silk-bb',            '-cpu', 'cortex-m4'] + mtd_args,
            }
        qemu_args.extend(platform_args[self.platform])

        logging.info("spawning qemu (%s): %s", self.platform, " ".join(qemu_args))
        qemu_env = os.environ.copy()
        if self.platform in AUDIO_PLATFORMS and self.audio_sink and self.audio_client_conf:
            qemu_env['PULSE_CLIENTCONFIG'] = self.audio_client_conf
        self.qemu = subprocess.Popen(qemu_args, stdout=None, stdin=subprocess.PIPE, stderr=None,
                                      env=qemu_env,
                                      preexec_fn=lambda: os.nice(19))
        self.qemu.stdin.write(b"change vnc password\n")
        self.qemu.stdin.write(("%s\n" % self.token[:8]).encode())
        self.group.spawn(self.qemu.communicate)
        self._wait_for_qemu()

    def _wait_for_qemu(self):
        for i in range(20):
            gevent.sleep(0.2)
            try:
                s = socket.create_connection(('localhost', self.console_port))
            except socket.error:
                pass
            else:
                break
        else:
            raise Exception("Emulator launch timed out.")

        received = b''
        for i in range(150):
            gevent.sleep(0.2)
            received += s.recv(256)
            # PBL-21275: we'll add less hacky solutions for this to the firmware.
            if b"<SDK Home>" in received or b"<Launcher>" in received or b"Ready for communication" in received:
                break
        else:
            raise Exception("Didn't get ready message from firmware.")
        s.close()

    def _spawn_pkjs(self):
        env = os.environ.copy()
        hours = self.tz_offset // 60
        minutes = abs(self.tz_offset % 60)
        tz = "PBL%+03d:%02d" % (-hours, minutes)  # Why minus? Because POSIX is backwards.
        env['TZ'] = tz
        if self.client_ip:
            env['PYPKJS_CLIENT_IP'] = self.client_ip
            logging.info("GEOLOC setting PYPKJS_CLIENT_IP=%s for pypkjs", self.client_ip)
        else:
            logging.warning("GEOLOC no client_ip available for pypkjs")
        if self.oauth is not None:
            oauth_arg = ['--oauth', self.oauth]
        else:
            oauth_arg = []
        self.persist_dir = tempfile.mkdtemp()
        cmd = [
            'pypkjs',
            '--qemu', '127.0.0.1:%d' % self.bt_port,
            '--port', str(self.ws_port),
            # Use --arg=value form so tokens beginning with '-' are not parsed as flags.
            '--token=%s' % self.token,
            '--persist', self.persist_dir,
        ] + oauth_arg
        if settings.BLOCK_PRIVATE_ADDRESSES:
            cmd.append('--block-private-addresses')
        logging.info("spawning pkjs: token=%r (len=%d), cmd=%s", self.token, len(self.token), cmd)
        self.pkjs = subprocess.Popen(cmd, env=env)
        self.group.spawn(self.pkjs.communicate)

    def _find_qemu_images(self):
        return settings.QEMU_IMAGE_ROOT + "/" + self.platform + "/qemu/"
