"""Serving a pbw's bundled settings page from the emulator's phone simulator.

pypkjs serves the page at /config/<uuid>/ on its own port, which only this container can reach,
and the page talks to the pbw's scripts over a WebSocket at /config/<uuid>/bridge. The controller
relays both under /qemu/<emu>/config/<uuid>/.
"""
import json
import re

# The page is written by whoever wrote the project, and /qemu may share an origin with the IDE.
# Sandboxed without allow-same-origin it runs in an opaque origin: no IDE cookies, storage or
# same-origin requests. Its bridge WebSocket still connects.
PAGE_HEADERS = [
    ('Content-Type', 'text/html; charset=utf-8'),
    ('Content-Security-Policy', 'sandbox allow-scripts allow-forms allow-modals allow-popups'),
    ('Cache-Control', 'no-store'),
    ('X-Content-Type-Options', 'nosniff'),
    # The URL carries the emulator token; keep it out of the Referer of anything the page loads.
    ('Referrer-Policy', 'no-referrer'),
]

# Wherever the page ended up being served from, its bridge is beside it, with the same token.
BRIDGE_EXPRESSION = '(location.pathname.replace(/\\/?$/, "/") + "bridge" + location.search)'


def rewrite_bridge(html, uuid):
    """Point pypkjs' page shim at the relayed bridge rather than pypkjs' own path.

    Returns (html, found): found is False if the page has no bridge path to replace, in which
    case it can't reach its scripts."""
    literal = json.dumps('/config/%s/bridge' % uuid)
    return html.replace(literal, BRIDGE_EXPRESSION), literal in html


_TOKEN = re.compile(r'([?&]token=)[^&\s"]*')


def redact_token(line):
    """An access-log line without the emulator token its query string carried."""
    return _TOKEN.sub(r'\1<redacted>', line)
