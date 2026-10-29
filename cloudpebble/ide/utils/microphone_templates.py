"""SDK 4.43 microphone examples, available without a network template checkout."""
import io
import json
import zipfile

TEMPLATES = [
    {'id': 'microphone/capture', 'label': 'Microphone: on-watch level meter', 'group': 'microphone', 'dir': 'microphone/'},
    {'id': 'microphone/stream', 'label': 'Microphone: stream to PebbleKit JS', 'group': 'microphone', 'dir': 'microphone/'},
]
COMMON = '''#include <pebble.h>
static Window *s_window;
static TextLayer *s_text;
static char s_status[80];
static void show(const char *text) { text_layer_set_text(s_text, text); }
static void resize(void) {
  GRect bounds = layer_get_unobstructed_bounds(window_get_root_layer(s_window));
  layer_set_frame(text_layer_get_layer(s_text), GRect(8, bounds.size.h / 4, bounds.size.w - 16, bounds.size.h / 2));
}
static void unobstructed(void *context) { resize(); }
__HANDLERS__
static void select_click(ClickRecognizerRef recognizer, void *context) {
__TOGGLE__
}
static void clicks(void *context) { window_single_click_subscribe(BUTTON_ID_SELECT, select_click); }
static void load(Window *window) {
  s_text = text_layer_create(GRect(0, 0, 100, 100));
  text_layer_set_text_alignment(s_text, GTextAlignmentCenter);
  text_layer_set_font(s_text, fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD));
  layer_add_child(window_get_root_layer(window), text_layer_get_layer(s_text));
  resize();
  show("Microphone\\nSELECT to start");
}
static void unload(Window *window) { text_layer_destroy(s_text); }
int main(void) {
  s_window = window_create();
  window_set_click_config_provider(s_window, clicks);
  window_set_window_handlers(s_window, (WindowHandlers){.load = load, .unload = unload});
  unobstructed_area_service_subscribe((UnobstructedAreaHandlers){.did_change = unobstructed}, NULL);
  window_stack_push(s_window, true);
  app_event_loop();
  __STOP__();
  unobstructed_area_service_unsubscribe();
  window_destroy(s_window);
}
'''
CAPTURE = '''static void data(const int16_t *samples, size_t count, void *context) {
  static unsigned frames;
  int peak = 0;
  for (size_t i = 0; i < count; ++i) {
    int value = samples[i] < 0 ? -(int)samples[i] : samples[i];
    if (value > peak) peak = value;
  }
  if (++frames % 5 == 0) {
    snprintf(s_status, sizeof(s_status), "Level: %d%%\\nSELECT to stop", peak * 100 / 32768);
    show(s_status);
    APP_LOG(APP_LOG_LEVEL_INFO, "Capture peak: %d", peak);
  }
}
static void stopped(MicCaptureStopReason reason, void *context) {
  snprintf(s_status, sizeof(s_status), "Capture stopped: %d\\nSELECT to retry", (int)reason);
  show(s_status);
}
'''
STREAM = '''static void started(void *context) { show("Streaming to phone\\nSELECT to stop"); }
static void stopped(MicStreamStopReason reason, void *context) {
  snprintf(s_status, sizeof(s_status), "Stream stopped: %d\\nSELECT to retry", (int)reason);
  show(s_status);
}
'''
PKJS = '''Pebble.addEventListener('ready', function() { console.log('Microphone companion ready'); });
Pebble.addEventListener('audiostreamstart', function(event) {
  console.log('Audio: ' + event.sampleRate + ' Hz ' + event.format);
});
Pebble.addEventListener('audiostream', function(event) {
  var samples = new Int16Array(event.data);
  var peak = 0;
  for (var i = 0; i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i]));
  console.log('Received ' + samples.length + ' samples, peak ' + peak);
});
Pebble.addEventListener('audiostreamstop', function() { console.log('Audio stopped'); });
'''

def build_microphone_archive(template_id):
    capture = template_id == 'microphone/capture'
    prefix = 'mic_capture' if capture else 'mic_stream_to_phone'
    handlers = '(MicCaptureHandlers){.data = data, .stopped = stopped}' if capture else '(MicStreamHandlers){.started = started, .stopped = stopped}'
    toggle = '''  if (%s_is_active()) { %s_stop(); show("Stopped\\nSELECT to start"); return; }
  int result = %s_start(%s, NULL);
  if (result) {
    snprintf(s_status, sizeof(s_status), "Start error: %%d\\nCheck permission", result);
    show(s_status);
    APP_LOG(APP_LOG_LEVEL_WARNING, "Microphone start error: %%d", result);
  }''' % (prefix, prefix, prefix, handlers)
    source = COMMON.replace('__HANDLERS__', CAPTURE if capture else STREAM).replace('__TOGGLE__', toggle).replace('__STOP__', prefix + '_stop')
    manifest = {'name': 'microphone-demo', 'version': '1.0.0', 'author': 'CloudPebble', 'pebble': {
        'displayName': 'Microphone capture' if capture else 'Microphone streaming',
        'sdkVersion': '3', 'projectType': 'native', 'manifestVersion': 2,
        'usesPermissions': ['WatchMicrophone'], 'targetPlatforms': ['emery', 'flint', 'gabbro'],
        'messageKeys': [], 'resources': {'media': []}}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('package.json', json.dumps(manifest))
        archive.writestr('src/c/main.c', source)
        if not capture:
            archive.writestr('src/pkjs/index.js', PKJS)
    return buffer.getvalue()
