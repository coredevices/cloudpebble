import re
import json
import time
import logging
import os
import uuid as uuid_module

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.views.decorators.http import require_safe, require_POST
from django.utils.translation import gettext as _

from ide.models.build import BuildResult
from ide.models.project import Project, TemplateProject
from ide.models.files import SourceFile, ResourceFile, PublishedMedia
from ide.tasks.archive import create_archive, do_import_archive
from ide.tasks.build import run_compile
from ide.tasks.gist import import_gist
from ide.tasks.git import do_import_github
from ide.utils.alloy_templates import list_alloy_templates, build_template_archive
from ide.utils.c_templates import list_c_templates, build_c_template_archive
from utils.td_helper import send_td_event
from utils.jsonview import json_view, BadRequest

__author__ = 'katharine'
logger = logging.getLogger(__name__)

NATIVE_DEFAULT_TEMPLATE = """\
#include <pebble.h>

static Window *s_main_window;
static TextLayer *s_text_layer;

static void select_click_handler(ClickRecognizerRef recognizer, void *context) {
  text_layer_set_text(s_text_layer, "Select");
}

static void up_click_handler(ClickRecognizerRef recognizer, void *context) {
  text_layer_set_text(s_text_layer, "Up");
}

static void down_click_handler(ClickRecognizerRef recognizer, void *context) {
  text_layer_set_text(s_text_layer, "Down");
}

static void click_config_provider(void *context) {
  window_single_click_subscribe(BUTTON_ID_SELECT, select_click_handler);
  window_single_click_subscribe(BUTTON_ID_UP, up_click_handler);
  window_single_click_subscribe(BUTTON_ID_DOWN, down_click_handler);
}

static void main_window_load(Window *window) {
  Layer *window_layer = window_get_root_layer(window);
  GRect bounds = layer_get_bounds(window_layer);

  s_text_layer = text_layer_create(GRect(0, 72, bounds.size.w, 20));
  text_layer_set_text(s_text_layer, "Press a button");
  text_layer_set_text_alignment(s_text_layer, GTextAlignmentCenter);
  layer_add_child(window_layer, text_layer_get_layer(s_text_layer));
}

static void main_window_unload(Window *window) {
  text_layer_destroy(s_text_layer);
}

static void init(void) {
  s_main_window = window_create();
  window_set_click_config_provider(s_main_window, click_config_provider);
  window_set_window_handlers(s_main_window, (WindowHandlers) {
    .load = main_window_load,
    .unload = main_window_unload,
  });
  window_stack_push(s_main_window, true);
}

static void deinit(void) {
  window_destroy(s_main_window);
}

int main(void) {
  init();
  app_event_loop();
  deinit();
}
"""

ALLOY_C_TEMPLATE = """\
#include <pebble.h>

int main(void) {
  Window *w = window_create();
  window_stack_push(w, true);

  moddable_createMachine(NULL);

  window_destroy(w);
}
"""

ALLOY_JS_TEMPLATE = """\
import Poco from "commodetto/Poco";

console.log("Hello, Watchface.");

let render = new Poco(screen);

const font = new render.Font("Bitham-Black", 30);
const black = render.makeColor(0, 0, 0);
const white = render.makeColor(255, 255, 255);

function draw() {
\trender.begin();
\trender.fillRectangle(white, 0, 0, render.width, render.height);
\t
\tconst msg = (new Date).toTimeString().slice(0, 8);
\tconst width = render.getTextWidth(msg, font);

\trender.drawText(msg, font, black,
\t\t(render.width - width) / 2, (render.height - font.height) / 2);

\trender.end();
}

Pebble.addEventListener('secondchange', draw);
"""

ALLOY_MANIFEST_TEMPLATE = """\
{
 \t"include":  [
\t\t"$(MODDABLE)/examples/manifest_mod.json"
\t],
\t"modules": {
\t\t"*": "./main.js"
\t}
}
"""

ALLOY_ANALOG_JS_TEMPLATE = """\
import Poco from "commodetto/Poco";

const render = new Poco(screen);

// Colors
const darkGray = render.makeColor(40, 40, 40);
const white = render.makeColor(255, 255, 255);
const red = render.makeColor(255, 60, 60);
const gold = render.makeColor(255, 215, 0);
const lightBlue = render.makeColor(100, 149, 237);

// Helper: Convert time fraction to radians
function fractionToRadians(fraction) {
    return fraction * 2 * Math.PI;
}

// Draw a clock hand from center outward
function drawHand(cx, cy, angle, length, color, thickness) {
    const x2 = cx + Math.sin(angle) * length;
    const y2 = cy - Math.cos(angle) * length;
    render.drawLine(cx, cy, x2, y2, color, thickness);
}

function draw(event) {
    const now = event.date;
    const hours = now.getHours() % 12;
    const minutes = now.getMinutes();

    // Calculate center and hand length
    const cx = render.width / 2;
    const cy = render.height / 2;
    const maxLength = (Math.min(render.width, render.height) - 30) / 2;

    render.begin();

    // Dark background
    render.fillRectangle(darkGray, 0, 0, render.width, render.height);

    // Draw hour markers
    for (let i = 0; i < 12; i++) {
        const angle = fractionToRadians(i / 12);
        const isMainHour = (i % 3 === 0);
        const innerRadius = isMainHour ? maxLength - 15 : maxLength - 8;
        const outerRadius = maxLength;
        const color = isMainHour ? gold : white;
        const thickness = isMainHour ? 3 : 2;

        // Cache trig values to avoid redundant computation
        const sinAngle = Math.sin(angle);
        const cosAngle = Math.cos(angle);

        const x1 = cx + sinAngle * innerRadius;
        const y1 = cy - cosAngle * innerRadius;
        const x2 = cx + sinAngle * outerRadius;
        const y2 = cy - cosAngle * outerRadius;

        render.drawLine(x1, y1, x2, y2, color, thickness);
    }

    // Calculate hand angles
    const minuteFraction = minutes / 60;
    const hourFraction = (hours + minuteFraction) / 12;
    const minuteAngle = fractionToRadians(minuteFraction);
    const hourAngle = fractionToRadians(hourFraction);

    // Draw hands - gold hour, light blue minute
    drawHand(cx, cy, hourAngle, maxLength * 0.5, gold, 6);
    drawHand(cx, cy, minuteAngle, maxLength * 0.75, lightBlue, 4);

    // Center dot
    render.drawCircle(red, cx, cy, 6, 0, 360);
    render.drawCircle(white, cx, cy, 3, 0, 360);

    render.end();
}

// Update every minute
// Time events fire immediately when registered, so no explicit startup draw is needed
Pebble.addEventListener('minutechange', draw);
"""

ALLOY_WEATHER_JS_TEMPLATE = """\
import Poco from "commodetto/Poco";
import Message from "pebble/message";

const render = new Poco(screen);

// Colors - teal and orange theme
const teal = render.makeColor(0, 128, 128);
const white = render.makeColor(255, 255, 255);
const yellow = render.makeColor(255, 215, 0);
const orange = render.makeColor(255, 140, 0);

// Fonts - Leco for big digits, Gothic-Bold for weather
const timeFont = new render.Font("Leco-Regular", 42);
const weatherFont = new render.Font("Gothic-Bold", 28);
const conditionsFont = new render.Font("Gothic-Regular", 24);

// Weather and location data
let weather = null;
let latitude = null;
let longitude = null;
let fetching = false;
let lastFetch = 0;

// Set up messaging to receive location from phone
const message = new Message({
    input: 256,
    output: 256,
    keys: new Map([
        ["LATITUDE", 0],
        ["LONGITUDE", 1],
        ["REQUEST_LOCATION", 2]
    ]),
    onReadable() {
        const msg = this.read();
        if (!msg) return;

        if (msg.has("LATITUDE") && msg.has("LONGITUDE")) {
            latitude = msg.get("LATITUDE") / 10000;
            longitude = msg.get("LONGITUDE") / 10000;
            console.log("Got location: " + latitude + ", " + longitude);
            fetchWeather();
        }
    },
    onWritable() {
        if (!this.requested) {
            this.requested = true;
            console.log("Requesting location...");
            this.write(new Map([["REQUEST_LOCATION", 1]]));
        }
    }
});

// Map Open-Meteo weather codes to descriptions
function getWeatherDescription(code) {
    if (code === 0) return "Clear";
    if (code <= 3) return "Cloudy";
    if (code <= 49) return "Fog";
    if (code <= 59) return "Drizzle";
    if (code <= 69) return "Rain";
    if (code <= 79) return "Snow";
    if (code <= 99) return "Thunderstorm";
    return "Unknown";
}

function drawWeather() {
    const tempStr = `${weather.temp}\\u00b0C`;
    let width = render.getTextWidth(tempStr, weatherFont);
    render.drawText(tempStr, weatherFont, yellow,
        (render.width - width) / 2, 20);

    width = render.getTextWidth(weather.conditions, conditionsFont);
    render.drawText(weather.conditions, conditionsFont, orange,
        (render.width - width) / 2, render.height - conditionsFont.height - 20);
}

function draw(event) {
    const now = event?.date ?? new Date();

    render.begin();
    render.fillRectangle(teal, 0, 0, render.width, render.height);

    // Draw time in white
    const hours = now.getHours().toString().padStart(2, "0");
    const minutes = now.getMinutes().toString().padStart(2, "0");
    const timeStr = `${hours}:${minutes}`;

    let width = render.getTextWidth(timeStr, timeFont);
    render.drawText(timeStr, timeFont, white,
        (render.width - width) / 2,
        (render.height - timeFont.height) / 2);

    // Draw weather if available
    if (weather) {
        drawWeather();
    } else {
        const msg = "Loading...";
        width = render.getTextWidth(msg, conditionsFont);
        render.drawText(msg, conditionsFont, white,
            (render.width - width) / 2, 20);
    }

    render.end();
}

async function fetchWeather() {
    if (latitude === null || longitude === null) return;
    if (fetching) return;

    const now = Date.now();
    if (lastFetch && now - lastFetch < 1800000) return; // 30 min cooldown

    fetching = true;
    lastFetch = now;

    try {
        const url = new URL("http://api.open-meteo.com/v1/forecast");
        url.search = new URLSearchParams({
            latitude,
            longitude,
            current: "temperature_2m,weather_code"
        });

        console.log("Fetching weather...");
        const response = await fetch(url);
        const data = await response.json();

        weather = {
            temp: Math.round(data.current.temperature_2m),
            conditions: getWeatherDescription(data.current.weather_code)
        };

        console.log("Weather: " + weather.temp + "C, " + weather.conditions);
        draw();

    } catch (e) {
        console.log("Weather fetch error: " + e);
        lastFetch = 0; // Allow retry on error
    } finally {
        fetching = false;
    }
}

// Time updates (fires immediately when registered)
Pebble.addEventListener('minutechange', function(event) {
    draw(event);
    fetchWeather(); // Will no-op unless 30 min have passed
});
"""

ALLOY_WEATHER_PKJS_TEMPLATE = """\
const moddableProxy = require("@moddable/pebbleproxy");

Pebble.addEventListener('appmessage', function(e) {
    if (moddableProxy.appMessageReceived(e))
        return;

    // Key 2 = REQUEST_LOCATION
    if (e.payload[2] !== undefined) {
        console.log("Location requested");
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                console.log("Got location: " + pos.coords.latitude + ", " + pos.coords.longitude);
                Pebble.sendAppMessage({
                    0: Math.round(pos.coords.latitude * 10000),
                    1: Math.round(pos.coords.longitude * 10000)
                });
            },
            function(err) {
                console.log("Location error: " + err.message);
            },
            { timeout: 15000, maximumAge: 60000 }
        );
    }
});

Pebble.addEventListener("ready", function(e) {
    console.log("PebbleKit JS ready");
    moddableProxy.readyReceived(e);
});
"""


@require_safe
@login_required
@json_view
def project_info(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    source_files = SourceFile.objects.filter(project=project).order_by('file_name')
    resources = ResourceFile.objects.filter(project=project).order_by('file_name')
    return {
        'type': project.project_type,
        'name': project.name,
        'last_modified': str(project.last_modified),
        'app_uuid': project.app_uuid or '',
        'app_company_name': project.app_company_name,
        'app_short_name': project.app_short_name,
        'app_long_name': project.app_long_name,
        'app_version_label': project.app_version_label,
        'app_is_watchface': project.app_is_watchface,
        'app_is_hidden': project.app_is_hidden,
        'app_keys': json.loads(project.app_keys),
        'parsed_app_keys': project.get_parsed_appkeys(),
        'app_is_shown_on_communication': project.app_is_shown_on_communication,
        'app_capabilities': project.app_capabilities,
        'app_jshint': project.app_jshint,
        'app_dependencies': project.get_dependencies(include_interdependencies=False),
        'interdependencies': [p.id for p in project.project_dependencies.all()],
        'app_platforms': project.app_platforms,
        'app_modern_multi_js': project.app_modern_multi_js,
        'menu_icon': project.menu_icon.id if project.menu_icon else None,
        'source_files': [{
                             'name': f.file_name,
                             'id': f.id,
                             'target': f.target,
                             'file_path': f.project_path,
                             'is_binary': f.is_binary_source,
                             'is_editable': f.is_editable_text,
                             'lastModified': time.mktime(f.last_modified.utctimetuple())
                         } for f in source_files],
        'resources': [{
                          'id': x.id,
                          'file_name': x.file_name,
                          'kind': x.kind,
                          'identifiers': [y.resource_id for y in x.identifiers.all()],
                          'extra': {y.resource_id: y.get_options_dict(with_id=False) for y in x.identifiers.all()},
                          'variants': [y.get_tags() for y in x.variants.all()],
                      } for x in resources],
        'github': {
            'repo': "github.com/%s" % project.github_repo if project.github_repo is not None else None,
            'branch': project.github_branch if project.github_branch is not None else None,
            'last_sync': str(project.github_last_sync) if project.github_last_sync is not None else None,
            'last_commit': project.github_last_commit,
            'auto_build': project.github_hook_build,
            'auto_pull': project.github_hook_uuid is not None
        },
        'supported_platforms': project.supported_platforms,
        'has_embeddedjs': project.has_embeddedjs_files,
        'published_media': _serialize_published_media(project),
    }


@require_POST
@login_required
@json_view
def compile_project(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    build = BuildResult.objects.create(project=project)
    task = run_compile.delay(build.id)
    return {"build_id": build.id, "task_id": task.task_id}


def _serialize_build(build, project):
    if getattr(settings, 'AWS_S3_ENDPOINT_URL', None):
        download_file = 'package.tar.gz' if project.project_type == 'package' else 'watchface.pbw'
        download = '/ide/project/%d/build/%d/download/%s' % (project.id, build.id, download_file)
        log = '/ide/project/%d/build/%d/log' % (project.id, build.id)
    else:
        download = build.package_url if project.project_type == 'package' else build.pbw_url
        log = build.build_log_url
    return {
        'uuid': build.uuid,
        'state': build.state,
        'started': str(build.started),
        'finished': str(build.finished) if build.finished else None,
        'id': build.id,
        'download': download,
        'log': log,
        'build_dir': build.get_url(),
        'sizes': build.get_sizes(),
    }


@require_safe
@login_required
@json_view
def last_build(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    try:
        build = project.builds.order_by('-started')[0]
    except (IndexError, BuildResult.DoesNotExist):
        return {"build": None}
    else:
        b = _serialize_build(build, project)
        return {"build": b}


@require_safe
@login_required
@json_view
def build_history(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    try:
        builds = project.builds.order_by('-started')[:10]
    except (IndexError, BuildResult.DoesNotExist):
        return {"build": None}

    out = []
    for build in builds:
        out.append(_serialize_build(build, project))
    return {"builds": out}


@require_safe
@login_required
@json_view
def build_log(request, project_id, build_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    build = get_object_or_404(BuildResult, project=project, pk=build_id)

    log = build.read_build_log()

    send_td_event('cloudpebble_view_build_log', data={
        'data': {
            'build_state': build.state
        }
    }, request=request, project=project)

    return {"log": log}


@require_safe
@login_required
@json_view
def build_info(request, project_id, build_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    build = get_object_or_404(BuildResult, project=project, pk=build_id)
    return {"build": _serialize_build(build, project)}


DOWNLOAD_CONTENT_TYPES = {
    'watchface.pbw': 'application/octet-stream',
    'package.tar.gz': 'application/gzip',
}


@require_safe
@login_required
def build_download(request, project_id, build_id, filename):
    """Proxy build artifact downloads from S3/R2 to avoid CORS issues."""
    import utils.s3 as s3
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    build = get_object_or_404(BuildResult, project=project, pk=build_id)

    if filename == 'watchface.pbw':
        s3_path = build.pbw
    elif filename == 'package.tar.gz':
        s3_path = build.package
    else:
        return HttpResponse(status=404)

    content_type = DOWNLOAD_CONTENT_TYPES.get(filename, 'application/octet-stream')
    data = s3.read_file('builds', s3_path)
    response = HttpResponse(data, content_type=content_type)
    response['Content-Disposition'] = 'attachment; filename="%s"' % filename
    return response


@require_safe
@login_required
def export_download(request, export_key):
    filename = os.path.basename(export_key) or 'cloudpebble-export.zip'

    if settings.AWS_ENABLED:
        import utils.s3 as s3
        data = s3.read_file('export', export_key)
        response = HttpResponse(data, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="%s"' % filename
        return response

    export_root = os.path.abspath(settings.EXPORT_DIRECTORY)
    export_path = os.path.abspath(os.path.join(export_root, export_key))
    if not export_path.startswith(export_root + os.sep):
        return HttpResponse(status=404)
    if not os.path.exists(export_path):
        return HttpResponse(status=404)
    with open(export_path, 'rb') as f:
        response = HttpResponse(f.read(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="%s"' % filename
    return response


@require_POST
@login_required
@json_view
def create_project(request):
    name = request.POST['name']
    template_value = request.POST.get('template', None)
    template_id = None
    c_template = None
    if template_value is not None:
        try:
            template_id = int(template_value)
        except (TypeError, ValueError):
            c_template = template_value
    project_type = request.POST.get('type', 'native')
    template_name = None
    try:
        with transaction.atomic():
            app_keys = '[]'
            imported_from_archive = False
            project = Project.objects.create(
                name=name,
                owner=request.user,
                app_company_name=request.user.username,
                app_short_name=name,
                app_long_name=name,
                app_version_label='1.0',
                app_is_watchface=False,
                app_capabilities='',
                project_type=project_type,
                app_keys=app_keys,
                app_platforms='emery,gabbro' if project_type == 'alloy' else None
            )
            if project_type == 'native' and template_id == -1:
                f = SourceFile.objects.create(project=project, file_name="main.c")
                f.save_text(NATIVE_DEFAULT_TEMPLATE)
            elif project_type == 'native' and c_template:
                available_c_templates = {x['id'] for x in list_c_templates()}
                if c_template in available_c_templates:
                    try:
                        bundle = build_c_template_archive(c_template)
                        do_import_archive(project.id, bundle, delete_project=True)
                        imported_from_archive = True
                        template_name = c_template
                    except Exception as e:
                        raise BadRequest(_('Failed to import C SDK template: %s') % str(e))
                else:
                    raise BadRequest(_('Unknown C SDK template id: %s') % c_template)
            elif template_id is not None and template_id != 0:
                template = TemplateProject.objects.get(pk=template_id)
                template_name = template.name
                template.copy_into_project(project)
            elif project_type == 'simplyjs':
                f = SourceFile.objects.create(project=project, file_name="app.js")
                f.save_text(open('{}/src/html/demo.js'.format(settings.SIMPLYJS_ROOT)).read())
            elif project_type == 'alloy':
                alloy_template = request.POST.get('alloy_template', '0')
                available_alloy_templates = {x['id'] for x in list_alloy_templates()}
                if alloy_template in available_alloy_templates:
                    try:
                        bundle = build_template_archive(alloy_template)
                        do_import_archive(project.id, bundle, delete_project=True)
                        imported_from_archive = True
                    except Exception as e:
                        raise BadRequest(_('Failed to import JavaScript SDK template: %s') % str(e))
                else:
                    if alloy_template not in {'0', '1', '2'}:
                        logger.warning('Unknown alloy template id "%s", falling back to default', alloy_template)
                    f = SourceFile.objects.create(project=project, file_name="mdbl.c", target='app')
                    f.save_text(ALLOY_C_TEMPLATE)
                    if alloy_template == '2':
                        js_template = ALLOY_WEATHER_JS_TEMPLATE
                    elif alloy_template == '1':
                        js_template = ALLOY_ANALOG_JS_TEMPLATE
                    else:
                        js_template = ALLOY_JS_TEMPLATE
                    f = SourceFile.objects.create(project=project, file_name="main.js", target='embeddedjs')
                    f.save_text(js_template)
                    f = SourceFile.objects.create(project=project, file_name="manifest.json", target='embeddedjs')
                    f.save_text(ALLOY_MANIFEST_TEMPLATE)
                    if alloy_template == '2':
                        f = SourceFile.objects.create(project=project, file_name="index.js", target='pkjs')
                        f.save_text(ALLOY_WEATHER_PKJS_TEMPLATE)
                        project.app_keys = '["LATITUDE", "LONGITUDE", "REQUEST_LOCATION"]'
                        project.app_is_watchface = True
                        project.app_capabilities = 'location'
                        project.set_dependencies({'@moddable/pebbleproxy': '^0.1.3'})
            elif project_type == 'pebblejs':
                f = SourceFile.objects.create(project=project, file_name="app.js")
                f.save_text(open('{}/src/js/app.js'.format(settings.PEBBLEJS_ROOT)).read())
            if imported_from_archive:
                # do_import_archive() persists imported metadata (including targetPlatforms) using its own Project instance.
                # Refresh to avoid writing stale defaults back over imported values.
                project.refresh_from_db()
                # Templates ship with a fixed UUID in their manifest. Generate a new one
                # so every project created from the same template gets its own unique UUID.
                project.app_uuid = str(uuid_module.uuid4())
                # Upstream imported JS templates may intentionally use style that fails legacy JSHint defaults.
                # Keep creation/build parity with source templates by disabling JSHint on imported Alloy projects.
                if project_type == 'alloy':
                    project.app_jshint = False
                    # Some imported templates still use object-style appKeys.
                    # Normalize to array format required by Alloy project validation.
                    app_keys = json.loads(project.app_keys)
                    if isinstance(app_keys, dict):
                        if all(isinstance(v, int) for v in app_keys.values()):
                            app_keys = [k for k, _ in sorted(app_keys.items(), key=lambda item: item[1])]
                        else:
                            app_keys = list(app_keys.keys())
                        project.app_keys = json.dumps(app_keys)
            project.full_clean()
            project.save()
    except IntegrityError as e:
        raise BadRequest(str(e))
    else:
        tracked_template_id = c_template if c_template else template_id
        send_td_event('cloudpebble_create_project', {'data': {'template': {'id': tracked_template_id, 'name': template_name}}},
                      request=request, project=project)

        return {"id": project.id}


@require_POST
@login_required
@json_view
def save_project_settings(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    try:
        with transaction.atomic():

            project.name = request.POST['name']
            project.app_uuid = request.POST['app_uuid']
            project.app_company_name = request.POST['app_company_name']
            project.app_short_name = request.POST['app_short_name']
            project.app_long_name = request.POST['app_long_name']
            project.app_version_label = request.POST['app_version_label']
            project.app_is_watchface = bool(int(request.POST['app_is_watchface']))
            project.app_is_hidden = bool(int(request.POST['app_is_hidden']))
            project.app_is_shown_on_communication = bool(int(request.POST['app_is_shown_on_communication']))
            project.app_capabilities = request.POST['app_capabilities']
            project.app_keys = request.POST['app_keys']
            project.app_jshint = False
            app_platforms = request.POST['app_platforms']
            if app_platforms and project.has_embeddedjs_files:
                unsupported = set(app_platforms.split(',')) - {'emery', 'gabbro', 'flint'}
                if unsupported:
                    raise BadRequest(
                        _("Projects with Embedded JS files can only target Emery, Gabbro, and Flint. "
                          "Remove unsupported platforms: %s") % ', '.join(sorted(unsupported))
                    )
            project.app_platforms = app_platforms
            project.app_modern_multi_js = bool(int(request.POST['app_modern_multi_js']))

            menu_icon = request.POST['menu_icon']
            old_icon = project.menu_icon
            if menu_icon != '':
                menu_icon = int(menu_icon)
                if old_icon is not None:
                    old_icon.is_menu_icon = False
                    old_icon.save()
                icon_resource = project.resources.filter(id=menu_icon)[0]
                icon_resource.is_menu_icon = True
                icon_resource.save()
            elif old_icon is not None:
                old_icon.is_menu_icon = False
                old_icon.save()

            project.save()
    except IntegrityError as e:
        return BadRequest(str(e))
    else:
        send_td_event('cloudpebble_save_project_settings', request=request, project=project)


@require_POST
@login_required
@json_view
def regenerate_uuid(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    new_uuid = str(uuid_module.uuid4())
    project.app_uuid = new_uuid
    project.save(update_fields=['app_uuid'])
    return {'uuid': new_uuid}


@require_POST
@login_required
@json_view
def save_project_dependencies(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    try:
        project.set_dependencies(json.loads(request.POST['dependencies']))
        project.set_interdependencies([int(x) for x in json.loads(request.POST['interdependencies'])])
        return {'dependencies': project.get_dependencies()}
    except (IntegrityError, ValueError) as e:
        raise BadRequest(str(e))
    else:
        send_td_event('cloudpebble_save_project_settings', request=request, project=project)

@require_POST
@login_required
@json_view
def save_published_media(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)

    if project.project_type != 'package':
        raise BadRequest(_("Published media is only supported for package projects."))

    try:
        entries = json.loads(request.POST['published_media'])
    except (KeyError, json.JSONDecodeError) as e:
        raise BadRequest(str(e))

    if not isinstance(entries, list):
        raise BadRequest(_("published_media must be a list"))

    seen_names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise BadRequest(_("Each published media entry must be an object."))

        try:
            name = (entry.get('name') or '').strip()
        except AttributeError:
            raise BadRequest(_("Invalid name field."))
        if not name:
            raise BadRequest(_("Each published media entry must have a name."))
        if name in seen_names:
            raise BadRequest(_("Duplicate published media name: '%s'") % name)
        seen_names.add(name)

        try:
            glance = (entry.get('glance') or '').strip() or None
            timeline_tiny = (entry.get('timeline_tiny') or '').strip() or None
            timeline_small = (entry.get('timeline_small') or '').strip() or None
            timeline_large = (entry.get('timeline_large') or '').strip() or None
        except AttributeError:
            raise BadRequest(_("Invalid field value in entry '%s'.") % name)

        if not glance and not timeline_tiny and not timeline_small and not timeline_large:
            raise BadRequest(_("Entry '%s' must have at least one of glance or timeline fields.") % name)

        if glance and timeline_tiny and glance != timeline_tiny:
            raise BadRequest(
                _("Entry '%s': when both glance and timeline tiny are set, they must reference the same resource.") % name
            )

    try:
        with transaction.atomic():
            project.published_media.all().delete()
            for entry in entries:
                PublishedMedia.objects.create(
                    project=project,
                    name=(entry.get('name') or '').strip(),
                    glance=(entry.get('glance') or '').strip() or None,
                    timeline_tiny=(entry.get('timeline_tiny') or '').strip() or None,
                    timeline_small=(entry.get('timeline_small') or '').strip() or None,
                    timeline_large=(entry.get('timeline_large') or '').strip() or None,
                )
    except IntegrityError as e:
        raise BadRequest(str(e))

    return {'published_media': _serialize_published_media(project)}


def _serialize_published_media(project):
    return [
        {
            'name': pm.name,
            'glance': pm.glance or '',
            'timeline_tiny': pm.timeline_tiny or '',
            'timeline_small': pm.timeline_small or '',
            'timeline_large': pm.timeline_large or '',
        }
        for pm in project.published_media.all()
    ]


@require_POST
@login_required
@json_view
def delete_project(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    if not bool(request.POST.get('confirm', False)):
        raise BadRequest(_("Not confirmed"))
    project.delete()
    send_td_event('cloudpebble_delete_project', request=request, project=project)


@login_required
@require_POST
@json_view
def begin_export(request, project_id):
    project = get_object_or_404(Project, pk=project_id, owner=request.user)
    result = create_archive.delay(project.id)
    return {'task_id': result.task_id}


@login_required
@require_safe
@json_view
def get_projects(request):
    """ Gets a list of all projects owned by the user.

    Accepts one possible filter: '?libraries=[id]'. If given, the list of projects
    is limited to packages, and each returned package includes a 'depended_on' attribute
    which is true if it is depended on by the project where pk=[id].
    """
    filters = {
        'owner': request.user
    }
    exclusions = {}
    parent_project = None

    libraries_for_project = int(request.GET['libraries']) if 'libraries' in request.GET else None
    if libraries_for_project:
        filters['project_type'] = 'package'
        parent_project = get_object_or_404(Project, pk=libraries_for_project, owner=request.user)
        parent_project_dependencies = parent_project.project_dependencies.all()
        exclusions['pk'] = libraries_for_project

    projects = Project.objects.filter(**filters).exclude(**exclusions)

    def process_project(project):
        data = {
            'name': project.name,
            'package_name': project.npm_name,
            'id': project.id,
            'app_version_label': project.app_version_label,
            'latest_successful_build': None
        }
        try:
            data['latest_successful_build'] = str(BuildResult.objects.filter(project=project, state=BuildResult.STATE_SUCCEEDED).latest('id').finished)
        except BuildResult.DoesNotExist:
            pass
        if parent_project:
            data['depended_on'] = project in parent_project_dependencies
        return data

    return {
        'projects': [process_project(project) for project in projects]
    }


@login_required
@require_POST
@json_view
def import_zip(request):
    zip_file = request.FILES['archive']
    name = request.POST['name']
    try:
        project = Project.objects.create(owner=request.user, name=name)
    except IntegrityError as e:
        raise BadRequest(str(e))
    task = do_import_archive.delay(project.id, zip_file.read(), delete_project=True)

    return {'task_id': task.task_id, 'project_id': project.id}


@login_required
@require_POST
@json_view
def import_github(request):
    name = request.POST['name']
    repo = request.POST['repo']
    branch = request.POST['branch']
    add_remote = (request.POST['add_remote'] == 'true')
    match = re.match(r'^(?:https?://|git@|git://)?(?:www\.)?github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git|/|$)', repo)
    if match is None:
        raise BadRequest(_("Invalid Github URL."))

    github_user = match.group(1)
    github_project = match.group(2)

    try:
        project = Project.objects.create(owner=request.user, name=name)
    except IntegrityError as e:
        raise BadRequest(str(e))

    if add_remote:
        project.github_repo = "%s/%s" % (github_user, github_project)
        project.github_branch = branch
        project.save()

    task = do_import_github.delay(project.id, github_user, github_project, branch, delete_project=True)
    return {'task_id': task.task_id, 'project_id': project.id}


@login_required
@require_POST
@json_view
def do_import_gist(request):
    task = import_gist.delay(request.user.id, request.POST['gist_id'])
    return {'task_id': task.task_id}
