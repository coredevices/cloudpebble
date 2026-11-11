import config_proxy

UUID = '8b1c6b0e-7d6a-4cf2-a9b2-2c3f8b1c6b0e'
SHIM = 'var socket = new WebSocket("ws://" + location.host +\n "/config/%s/bridge");' % UUID


def test_bridge_follows_the_page():
    html, found = config_proxy.rewrite_bridge('<html><script>%s</script></html>' % SHIM, UUID)
    assert found
    assert '"/config/' not in html
    assert 'location.host +\n ' + config_proxy.BRIDGE_EXPRESSION in html


def test_page_without_a_bridge_is_reported():
    html, found = config_proxy.rewrite_bridge('<html></html>', UUID)
    assert (html, found) == ('<html></html>', False)


def test_page_is_sandboxed_away_from_the_ide_origin():
    policy = dict(config_proxy.PAGE_HEADERS)['Content-Security-Policy']
    assert policy.startswith('sandbox ')
    assert 'allow-same-origin' not in policy


def test_access_log_drops_the_token():
    line = '1.2.3.4 - - [now] "GET /qemu/e/config/u/?token=s3cr%3Det&return_to=x HTTP/1.1" 200 12 0.01'
    assert config_proxy.redact_token(line) == (
        '1.2.3.4 - - [now] "GET /qemu/e/config/u/?token=<redacted>&return_to=x HTTP/1.1" 200 12 0.01')
    assert config_proxy.redact_token('"GET /qemu/e/ws/audio?token=abc HTTP/1.1"') == (
        '"GET /qemu/e/ws/audio?token=<redacted> HTTP/1.1"')
    assert config_proxy.redact_token('"GET /qemu/e/ping HTTP/1.1"') == '"GET /qemu/e/ping HTTP/1.1"'
