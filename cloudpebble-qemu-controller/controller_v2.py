#!/usr/bin/env python3
"""
CloudPebble QEMU Controller v2 - Uses pebble-tool's emulator module
Python 3.11 compatible, with WebSocket VNC proxying
"""

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4, UUID

from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from flask_sock import Sock

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(asctime)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
sock = Sock(app)
CORS(app, resources="/qemu/*")

# Configuration
LAUNCH_AUTH_HEADER = os.environ.get('LAUNCH_AUTH_HEADER', 'secret')
EMULATOR_LIMIT = int(os.environ.get('EMULATOR_LIMIT', '5'))
PEBBLE_SDK_PATH = os.environ.get('PEBBLE_SDK_PATH', os.path.expanduser('~/.pebble-sdk'))

# Track active emulators
emulators = {}
# Track VNC displays in use
vnc_displays_in_use = set()


def get_free_vnc_display():
    """Get a free VNC display number (1-99)"""
    for i in range(1, 100):
        if i not in vnc_displays_in_use:
            vnc_displays_in_use.add(i)
            return i
    raise RuntimeError("No free VNC displays")


def release_vnc_display(display):
    """Release a VNC display number"""
    vnc_displays_in_use.discard(display)


class PebbleEmulator:
    """Wrapper around pebble-tool emulator functionality"""
    
    PLATFORM_MACHINES = {
        'aplite': ('pebble-bb2', 'cortex-m3', 'mtdblock'),
        'basalt': ('pebble-snowy-bb', 'cortex-m4', 'pflash'),
        'chalk': ('pebble-s4-bb', 'cortex-m4', 'pflash'),
        'diorite': ('pebble-silk-bb', 'cortex-m4', 'mtdblock'),
        'emery': ('pebble-robert-bb', 'cortex-m4', 'pflash'),
    }
    
    def __init__(self, platform, sdk_version='4.9.77', token=None):
        self.platform = platform
        self.sdk_version = sdk_version
        self.token = token or str(uuid4())[:8]
        self.qemu_pid = None
        self.pypkjs_pid = None
        self.qemu_port = None
        self.qemu_serial_port = None
        self.ws_port = None  # pypkjs WebSocket port for phone connection
        self.vnc_display = None
        self.vnc_ws_port = None  # QEMU's built-in VNC websocket port
        self.spi_image_path = None
        self.last_ping = time.time()
        
    def _choose_port(self):
        sock = socket.socket()
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port
    
    def _get_sdk_path(self):
        """Get path to SDK resources"""
        if os.path.exists(PEBBLE_SDK_PATH):
            sdk_dir = os.path.join(PEBBLE_SDK_PATH, 'SDKs', self.sdk_version)
            if os.path.exists(sdk_dir):
                return sdk_dir
        
        raise RuntimeError(f"SDK {self.sdk_version} not found")
    
    def _get_qemu_images_path(self):
        """Get path to QEMU firmware images"""
        sdk_path = self._get_sdk_path()
        return os.path.join(sdk_path, 'sdk-core', 'pebble', self.platform, 'qemu')
    
    def _create_spi_image(self):
        """Create a writable copy of the SPI flash image"""
        import bz2
        
        images_path = self._get_qemu_images_path()
        spi_source = os.path.join(images_path, 'qemu_spi_flash.bin.bz2')
        
        if not os.path.exists(spi_source):
            spi_source = os.path.join(images_path, 'qemu_spi_flash.bin')
            if not os.path.exists(spi_source):
                raise RuntimeError(f"SPI flash image not found at {images_path}")
            
            self.spi_image_path = tempfile.mktemp(suffix='.bin')
            import shutil
            shutil.copy(spi_source, self.spi_image_path)
        else:
            self.spi_image_path = tempfile.mktemp(suffix='.bin')
            with bz2.BZ2File(spi_source) as src:
                with open(self.spi_image_path, 'wb') as dst:
                    dst.write(src.read())
        
        return self.spi_image_path
    
    @property
    def vnc_port(self):
        """VNC TCP port for this emulator"""
        return 5900 + self.vnc_display if self.vnc_display else None
    
    def run(self):
        """Start the emulator"""
        # Allocate ports
        self.qemu_port = self._choose_port()
        self.qemu_serial_port = self._choose_port()
        self.ws_port = self._choose_port()
        self.vnc_display = get_free_vnc_display()
        self.vnc_ws_port = self._choose_port()  # For QEMU's built-in websocket VNC
        
        # Create SPI image
        self._create_spi_image()
        
        # Spawn QEMU
        self._spawn_qemu()
        
        # Wait for QEMU to boot
        self._wait_for_qemu()
        
        # Spawn pypkjs
        self._spawn_pypkjs()
        
        # Spawn websockify for VNC websocket access
        self._spawn_websockify()
        
        return {
            'ws_port': self.ws_port,
            'vnc_display': self.vnc_display,
            'vnc_port': self.vnc_port,
            'vnc_ws_port': self.vnc_ws_port,
        }
    
    def _spawn_qemu(self):
        """Spawn QEMU process"""
        images_path = self._get_qemu_images_path()
        micro_flash = os.path.join(images_path, 'qemu_micro_flash.bin')
        
        if not os.path.exists(micro_flash):
            raise RuntimeError(f"Micro flash not found: {micro_flash}")
        
        machine, cpu, flash_type = self.PLATFORM_MACHINES[self.platform]
        
        sdk_path = self._get_sdk_path()
        qemu_bin = os.path.join(sdk_path, 'toolchain', 'bin', 'qemu-pebble')
        if not os.path.exists(qemu_bin):
            qemu_bin = 'qemu-pebble'
        
        toolchain_lib = os.path.join(sdk_path, 'toolchain', 'lib')
        pc_bios = os.path.join(toolchain_lib, 'pc-bios')
        
        command = [
            qemu_bin,
            '-rtc', 'base=localtime',
            '-serial', 'null',
            '-serial', f'tcp::{self.qemu_port},server,nowait',
            '-serial', f'tcp::{self.qemu_serial_port},server,nowait',
            '-pflash', micro_flash,
            '-machine', machine,
            '-cpu', cpu,
            '-L', pc_bios,
            '-vnc', f':{self.vnc_display}',
        ]
        
        if flash_type == 'mtdblock':
            command.extend(['-mtdblock', self.spi_image_path])
        else:
            command.extend(['-pflash', self.spi_image_path])
        
        env = os.environ.copy()
        env['DYLD_FALLBACK_LIBRARY_PATH'] = toolchain_lib
        
        logger.info(f"Starting QEMU: {' '.join(command)}")
        
        self.qemu_proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )
        self.qemu_pid = self.qemu_proc.pid
    
    def _wait_for_qemu(self):
        """Wait for QEMU firmware to boot"""
        logger.info("Waiting for firmware to boot...")
        
        for i in range(30):
            time.sleep(0.2)
            try:
                s = socket.create_connection(('localhost', self.qemu_serial_port), timeout=1)
                break
            except (socket.error, socket.timeout):
                continue
        else:
            raise RuntimeError("QEMU launch timed out")
        
        received = b''
        s.settimeout(30)
        try:
            while True:
                data = s.recv(256)
                if not data:
                    break
                received += data
                if b"<SDK Home>" in received or b"<Launcher>" in received or b"Ready for communication" in received:
                    break
        except socket.timeout:
            pass
        finally:
            s.close()
        
        logger.info("Firmware booted!")
    
    def _spawn_pypkjs(self):
        """Spawn pypkjs JavaScript runtime"""
        images_path = self._get_qemu_images_path()
        layout_file = os.path.join(images_path, 'layouts.json')
        
        persist_dir = tempfile.mkdtemp(prefix='pypkjs_')
        
        command = [
            '/usr/local/bin/python', '-m', 'pypkjs',
            '--qemu', f'localhost:{self.qemu_port}',
            '--port', str(self.ws_port),
            '--persist', persist_dir,
            '--layout', layout_file,
        ]
        
        logger.info(f"Starting pypkjs: {' '.join(command)}")
        
        self.pypkjs_proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        self.pypkjs_pid = self.pypkjs_proc.pid
        self.persist_dir = persist_dir
    
    def _spawn_websockify(self):
        """Spawn websockify to provide WebSocket VNC access"""
        command = [
            '/usr/local/bin/python', '-m', 'websockify',
            '--heartbeat=30',
            str(self.vnc_ws_port),
            f'localhost:{self.vnc_port}'
        ]
        
        logger.info(f"Starting websockify: {' '.join(command)}")
        
        self.websockify_proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        self.websockify_pid = self.websockify_proc.pid
    
    def is_alive(self):
        """Check if emulator is still running"""
        if self.qemu_pid is None:
            return False
        try:
            os.kill(self.qemu_pid, 0)
            return True
        except OSError:
            return False
    
    def kill(self):
        """Kill the emulator and cleanup"""
        for proc_attr in ['qemu_proc', 'pypkjs_proc', 'websockify_proc']:
            proc = getattr(self, proc_attr, None)
            if proc:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception as e:
                    logger.warning(f"Error killing {proc_attr}: {e}")
        
        # Release VNC display
        if self.vnc_display:
            release_vnc_display(self.vnc_display)
        
        # Cleanup SPI image
        if self.spi_image_path and os.path.exists(self.spi_image_path):
            try:
                os.unlink(self.spi_image_path)
            except Exception:
                pass
        
        # Cleanup persist dir
        if hasattr(self, 'persist_dir') and os.path.exists(self.persist_dir):
            import shutil
            try:
                shutil.rmtree(self.persist_dir)
            except Exception:
                pass


# Flask routes

@app.route('/qemu/launch', methods=['POST'])
def launch():
    """Launch a new emulator instance"""
    auth = request.headers.get('Authorization', '')
    if auth != LAUNCH_AUTH_HEADER:
        logger.warning(f"Auth failed: got '{auth}', expected '{LAUNCH_AUTH_HEADER}'")
    
    if len(emulators) >= EMULATOR_LIMIT:
        abort(503)
    
    platform = request.form.get('platform', 'basalt')
    version = request.form.get('version', '4')
    token = request.form.get('token', str(uuid4()))
    
    # Map major version to full SDK version (we only have 4.9.77)
    SDK_VERSION_MAP = {
        '2': '4.9.77',  # SDK 2 projects use latest SDK for emulation
        '3': '4.9.77',  # SDK 3 projects use latest SDK for emulation  
        '3.0': '4.9.77',
        '4': '4.9.77',
        '4.9.77': '4.9.77',
    }
    version = SDK_VERSION_MAP.get(version, '4.9.77')
    logger.info(f"Launching emulator: platform={platform}, sdk_version={version}")
    
    if platform not in PebbleEmulator.PLATFORM_MACHINES:
        abort(400, f"Invalid platform: {platform}")
    
    emu_uuid = uuid4()
    emu = PebbleEmulator(platform, version, token)
    
    try:
        result = emu.run()
        emulators[emu_uuid] = emu
        emu.last_ping = time.time()
        
        return jsonify(
            uuid=str(emu_uuid),
            ws_port=result['ws_port'],
            vnc_ws_port=result['vnc_ws_port'],  # QEMU's built-in websocket VNC port
            vnc_display=result['vnc_display']
        )
    except Exception as e:
        logger.exception("Failed to launch emulator")
        return jsonify(error=str(e)), 500


@app.route('/qemu/<emu_id>/ping', methods=['POST'])
def ping(emu_id):
    """Keep emulator alive"""
    try:
        emu_uuid = UUID(emu_id)
    except ValueError:
        abort(404)
    
    if emu_uuid not in emulators:
        return jsonify(alive=False)
    
    emu = emulators[emu_uuid]
    if emu.is_alive():
        emu.last_ping = time.time()
        return jsonify(alive=True)
    else:
        try:
            emu.kill()
        except Exception:
            pass
        del emulators[emu_uuid]
        return jsonify(alive=False)


@app.route('/qemu/<emu_id>/kill', methods=['POST'])
def kill(emu_id):
    """Kill an emulator"""
    try:
        emu_uuid = UUID(emu_id)
    except ValueError:
        abort(404)
    
    if emu_uuid in emulators:
        try:
            emulators[emu_uuid].kill()
        except Exception:
            logger.exception("Error killing emulator")
        del emulators[emu_uuid]
    
    return jsonify(status='ok')


@sock.route('/qemu/<emu_id>/ws/vnc')
def vnc_proxy(ws, emu_id):
    """WebSocket VNC proxy - connects to websockify which proxies to QEMU VNC"""
    try:
        emu_uuid = UUID(emu_id)
    except ValueError:
        ws.close()
        return
    
    if emu_uuid not in emulators:
        logger.warning(f"VNC proxy: emulator {emu_id} not found")
        ws.close()
        return
    
    emu = emulators[emu_uuid]
    vnc_ws_port = emu.vnc_ws_port
    
    if not vnc_ws_port:
        logger.warning(f"VNC proxy: no VNC websocket port for {emu_id}")
        ws.close()
        return
    
    logger.info(f"VNC proxy: connecting {emu_id} to ws://localhost:{vnc_ws_port}")
    
    # Connect to websockify which proxies VNC
    import websocket as ws_client
    try:
        target_ws = ws_client.create_connection(
            f'ws://localhost:{vnc_ws_port}/',
            subprotocols=['binary'],
            timeout=5
        )
    except Exception as e:
        logger.error(f"VNC proxy: failed to connect to QEMU websocket: {e}")
        ws.close()
        return
    
    # Proxy data between browser WebSocket and QEMU WebSocket
    import select
    alive = [True]
    
    def recv_browser():
        """Thread to receive from browser and send to QEMU"""
        try:
            while alive[0]:
                data = ws.receive()
                if data is None:
                    break
                if isinstance(data, str):
                    data = data.encode('latin-1')
                target_ws.send_binary(data)
            logger.debug(f"VNC browser recv error: {e}")
        finally:
            alive[0] = False
    
    def recv_qemu():
        """Thread to receive from QEMU and send to browser"""
        try:
            while alive[0]:
                data = target_ws.recv()
                if not data:
                    break
                ws.send(data)
        except Exception as e:
            logger.debug(f"VNC QEMU recv error: {e}")
        finally:
            alive[0] = False
    
    browser_thread = threading.Thread(target=recv_browser, daemon=True)
    qemu_thread = threading.Thread(target=recv_qemu, daemon=True)
    
    browser_thread.start()
    qemu_thread.start()
    
    # Wait for either thread to finish
    browser_thread.join()
    qemu_thread.join()
    
    try:
        target_ws.close()
    except:
        pass
    logger.info(f"VNC proxy: closed for {emu_id}")


@sock.route('/qemu/<emu_id>/ws/phone')
def phone_proxy(ws, emu_id):
    """WebSocket phone proxy (for pypkjs)"""
    try:
        emu_uuid = UUID(emu_id)
    except ValueError:
        ws.close()
        return
    
    if emu_uuid not in emulators:
        ws.close()
        return
    
    emu = emulators[emu_uuid]
    ws_port = emu.ws_port
    
    if not ws_port:
        ws.close()
        return
    
    logger.info(f"Phone proxy: connecting {emu_id} to localhost:{ws_port}")
    
    try:
        phone_sock = socket.create_connection(('localhost', ws_port), timeout=5)
        phone_sock.setblocking(False)
    except Exception as e:
        logger.error(f"Phone proxy: failed to connect: {e}")
        ws.close()
        return
    
    import select
    
    def recv_ws():
        try:
            while True:
                data = ws.receive()
                if data is None:
                    break
                if isinstance(data, str):
                    data = data.encode('latin-1')
                phone_sock.sendall(data)
        except Exception:
            pass
        finally:
            try:
                phone_sock.close()
            except:
                pass
    
    ws_thread = threading.Thread(target=recv_ws, daemon=True)
    ws_thread.start()
    
    try:
        while True:
            readable, _, _ = select.select([phone_sock], [], [], 1.0)
            if readable:
                try:
                    data = phone_sock.recv(65536)
                    if not data:
                        break
                    ws.send(data)
                except BlockingIOError:
                    continue
                except Exception:
                    break
    except Exception:
        pass
    finally:
        try:
            phone_sock.close()
        except:
            pass


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify(
        status='ok',
        emulators=len(emulators),
        limit=EMULATOR_LIMIT
    )


def cleanup_idle_emulators():
    """Kill emulators that haven't been pinged in 5 minutes"""
    def check():
        while True:
            time.sleep(60)
            now = time.time()
            to_kill = []
            
            for emu_uuid, emu in list(emulators.items()):
                if now - emu.last_ping > 300:
                    to_kill.append(emu_uuid)
            
            for emu_uuid in to_kill:
                logger.info(f"Killing idle emulator {emu_uuid}")
                try:
                    emulators[emu_uuid].kill()
                except Exception:
                    pass
                del emulators[emu_uuid]
    
    thread = threading.Thread(target=check, daemon=True)
    thread.start()


def ensure_sdk_installed():
    """Install SDK if not present"""
    sdk_path = os.path.expanduser('~/.pebble-sdk/SDKs/4.9.77')
    if not os.path.exists(sdk_path):
        logger.info("SDK not found, installing...")
        try:
            result = subprocess.run(
                ['pebble', 'sdk', 'install', 'latest'],
                capture_output=True,
                text=True,
                timeout=600
            )
            if result.returncode != 0:
                logger.error(f"SDK install failed: {result.stderr}")
            else:
                logger.info("SDK installed successfully")
        except Exception as e:
            logger.error(f"Failed to install SDK: {e}")
    else:
        logger.info(f"SDK found at {sdk_path}")


if __name__ == '__main__':
    ensure_sdk_installed()
    cleanup_idle_emulators()
    
    port = int(os.environ.get('PORT', 8001))
    logger.info(f"Starting QEMU controller on port {port}")
    
    app.run(host='0.0.0.0', port=port, threaded=True)
