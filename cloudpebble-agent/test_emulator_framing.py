"""Unit test for the emulator wire framing and screenshot assembly. No network.

    python3 test_emulator_framing.py
"""

import struct
import zlib

from emulator import (BUTTONS, COLOUR_MAP, ENDPOINT_APP_LOGS, ENDPOINT_SCREENSHOT,
                      NoEmulator, OP_QEMU, QEMU_BUTTON, QEMU_TAP, TAP_AXES,
                      OP_FROM_WATCH, OP_TO_WATCH, ROUNDNESS, auth_frame, decode_app_log,
                      get_emulator, parse_inbound, screenshot_header, screenshot_png,
                      to_watch, ws_url)


def test_auth_frame():
    assert auth_frame('abc') == b'\x09\x03abc'


def test_to_watch():
    frame = to_watch(ENDPOINT_SCREENSHOT, b'\x00')
    assert frame == bytes([OP_TO_WATCH]) + struct.pack('>HH', 1, 8000) + b'\x00'


def test_parse_inbound():
    # 0x00 is from the watch; 0x01 is outbound-only and must not be mistaken for it.
    inbound = bytes([OP_FROM_WATCH]) + struct.pack('>HH', 3, 2006) + b'abc' + b'trailing'
    assert parse_inbound(inbound) == (OP_FROM_WATCH, 2006, b'abc')
    op, endpoint, payload = parse_inbound(to_watch(8000, b'\x00'))
    assert op == OP_TO_WATCH and endpoint is None
    # opcodes without a pebble header hand back the raw tail
    assert parse_inbound(b'\x02hello') == (0x02, None, b'hello')
    assert parse_inbound(b'') == (None, None, b'')


def test_app_log_decode():
    payload = (b'\x00' * 16
               + struct.pack('>IBBH', 1700000000, 100, 5, 42)
               + b'main.c'.ljust(16, b'\x00')
               + b'hello')
    assert decode_app_log(payload) == '[INFO] main.c:42 hello'
    # short/garbage payloads degrade instead of blowing up mid-turn
    assert decode_app_log(b'oops') == 'oops'


def _png_pixels(png):
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    width, height, depth, colour = struct.unpack('>IIBB', png[16:26])
    assert (depth, colour) == (8, 2)
    pos, idat = 8, b''
    while pos < len(png):
        length = struct.unpack('>I', png[pos:pos + 4])[0]
        tag = png[pos + 4:pos + 8]
        if tag == b'IDAT':
            idat += png[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = []
    for y in range(height):
        assert raw[y * stride] == 0, 'expected filter type 0'
        rows.append(raw[y * stride + 1:(y + 1) * stride])
    return width, height, rows


def test_screenshot_v2_assembly():
    # 2x2 8bpp frame: palette indices 0 (black), 63 (white), 48, 3.
    pixels = bytes([0b00000000, 0b00111111, 0b00110000, 0b00000011])
    header = struct.pack('>BIII', 0, 2, 2, 2)

    # the watch splits the image across several 0x00 frames on endpoint 8000
    frames = [bytes([OP_FROM_WATCH]) + struct.pack('>HH', len(header) + 2, ENDPOINT_SCREENSHOT) + header + pixels[:2],
              bytes([OP_FROM_WATCH]) + struct.pack('>HH', 2, ENDPOINT_SCREENSHOT) + pixels[2:],
              bytes([OP_FROM_WATCH]) + struct.pack('>HH', 3, ENDPOINT_APP_LOGS) + b'xxx']

    buf, meta, expected = b'', None, None
    for frame in frames:
        op, endpoint, data = parse_inbound(frame)
        if op != OP_FROM_WATCH or endpoint != ENDPOINT_SCREENSHOT:
            continue
        if meta is None:
            version, width, height, expected, data = screenshot_header(data)
            meta = (version, width, height)
        buf += data
    assert meta == (2, 2, 2)
    assert expected == 4 and buf == pixels

    width, height, rows = _png_pixels(screenshot_png(2, 2, 2, buf))
    assert (width, height) == (2, 2)

    def rgb(index):
        c = COLOUR_MAP[index]
        return bytes([(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF])

    assert rows[0] == rgb(0) + rgb(63) == bytes([0, 0, 0]) + bytes([255, 255, 255])
    # The panel-corrected palette, not the naive x85 map: index 48 is a muted red in
    # the IDE, and the model must judge its colours against what the user sees.
    assert rows[1] == rgb(48) + rgb(3)
    assert rows[1] != bytes([255, 0, 0]) + bytes([0, 0, 255])


def test_chalk_corners_are_masked():
    # 180px wide is the round display; the bezel clips ROUNDNESS[y] pixels each side.
    pixels = bytes([63]) * (180 * 180)
    width, height, rows = _png_pixels(screenshot_png(2, 180, 180, pixels))
    assert (width, height) == (180, 180)
    skip = ROUNDNESS[0]
    assert rows[0][:skip * 3] == b'\x00' * (skip * 3)
    assert rows[0][skip * 3:skip * 3 + 3] == b'\xff\xff\xff'
    assert rows[-1][-skip * 3:] == b'\x00' * (skip * 3)
    # The middle rows are untouched.
    assert rows[90] == b'\xff' * (180 * 3)


def test_get_emulator_rejects_a_spec_with_no_uuid_or_token():
    for spec in (None, {}, {'uuid': 'abc'}, {'token': 'x'}):
        try:
            get_emulator(spec, 'https://cloudpebble-dev.exe.xyz/')
        except NoEmulator as e:
            assert 'no emulator is running' in str(e)
        else:
            raise AssertionError('expected NoEmulator for %r' % (spec,))


def test_screenshot_v1_assembly():
    # 8x1 1bpp: alternating pixels, bit 0 is the leftmost pixel.
    pixels = bytes([0b01010101])
    width, height, rows = _png_pixels(screenshot_png(1, 8, 1, pixels))
    assert (width, height) == (8, 1)
    assert rows[0] == b''.join(bytes([255] * 3) if x % 2 == 0 else bytes([0] * 3) for x in range(8))


def test_screenshot_error_code():
    try:
        screenshot_header(struct.pack('>BIII', 1, 2, 144, 168))
    except Exception as e:
        assert 'error code 1' in str(e)
    else:
        raise AssertionError('expected a NoEmulator for a non-zero status code')


def test_ws_url():
    assert ws_url('https://cloudpebble-dev.exe.xyz/', 'abc') == 'wss://cloudpebble-dev.exe.xyz/qemu/abc/ws/phone'




def test_button_bits_match_what_the_watch_expects():
    """The payload is the set of buttons currently HELD, and the bits are
    libpebble2's QemuButton.Button values -- not the 0..3 indices the IDE's own
    JS uses before it shifts them."""
    assert BUTTONS == {'back': 1, 'up': 2, 'select': 4, 'down': 8}, BUTTONS
    # The IDE computes 1 << Pebble.Button.X; the two must agree.
    js_indices = {'back': 0, 'up': 1, 'select': 2, 'down': 3}
    for name, index in js_indices.items():
        assert BUTTONS[name] == 1 << index, name
    assert set(TAP_AXES) == {'x', 'y', 'z'}


def test_qemu_control_frames_are_opcode_protocol_payload():
    """0x0b <protocol> <payload>, on the same socket as everything else."""
    press = bytes([OP_QEMU, QEMU_BUTTON, BUTTONS['select']])
    assert press == b'\x0b\x08\x04', press
    release = bytes([OP_QEMU, QEMU_BUTTON, 0])
    assert release == b'\x0b\x08\x00', release
    shake = bytes([OP_QEMU, QEMU_TAP, TAP_AXES['y'], 1])
    assert shake == b'\x0b\x02\x01\x01', shake


def test_app_log_shipping_is_requested_the_way_the_browser_does():
    """Nothing arrives on logs() until the watch is told to ship APP_LOG output.
    The browser sends APP_LOGS=1 after every install (libpebble.js:enable_app_logs);
    the agent has to send the same frame or it debugs blind."""
    frame = to_watch(ENDPOINT_APP_LOGS, b'\x01')
    op, endpoint, payload = parse_inbound(b'\x00' + frame[1:])
    assert frame[0] == 0x01, frame[0]
    assert endpoint == 2006, endpoint
    assert payload == b'\x01', payload
    print('app log shipping frame correct')


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok  %s' % name)
    print('PASSED')
