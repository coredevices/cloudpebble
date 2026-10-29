"""A small, offline plugin that can be exercised without third-party credentials."""
PLUGIN_SCRIPT = '''// Plugins run on the phone when a source is requested.
Pebble.registerSourceHandler(function(request, respond) {
  if (request.category !== 'demo' || request.item !== 'hello') {
    respond.error('PLUGIN_UNAVAILABLE');
    return;
  }
  respond.data({
    validUntilMs: Date.now() + 60000,
    instances: [{
      instanceId: 'hello',
      properties: {message: {shortText: {text: 'Hello from CloudPebble!'}}}
    }]
  });
});
'''
CONFIG_HTML = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hello plugin</title>
<style>body { font: 17px system-ui; max-width: 36rem; padding: 2rem; margin: auto; color: #18332f; } h1 { color: #087f70; }</style>
<h1>Hello from CloudPebble</h1>
<p>This plugin shares a greeting through <strong>demo/hello</strong>.</p>
<p>Edit plugin.js to change the source, or add actions and permissions in Project Settings.</p>
</html>
'''
