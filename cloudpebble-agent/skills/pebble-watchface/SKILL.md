---
name: pebble-watchface
description: Generate complete Pebble smartwatch watchfaces AND watchapps (games, tools, web-API apps), in C or Alloy (JavaScript), build PBW artifacts, and test in QEMU emulator. Use when creating watchfaces, Pebble apps, animated displays, clock faces, watch games. Produces ready-to-install PBW files and runs them in emulator.
---

# Pebble Watchface & Watchapp Generator

Generate complete, buildable Pebble watchfaces and watchapps with full PBW artifact output and QEMU testing.

**Default target platform: Emery (Pebble Time 2, 200x228 color rectangular display).**

> **Running inside CloudPebble.** Read [CloudPebble Delta](#cloudpebble-delta) first — it
> overrides every shell command, file path, and project-scaffolding instruction below.

## Step 0: Watchface or Watchapp?

The language is not yours to choose — see [CloudPebble Delta](#cloudpebble-delta). The
watchface/watchapp flag is, and it is a project setting rather than a file:

| | Watchface | Watchapp |
|---|---|---|
| CloudPebble setting | `set_app_settings(app_is_watchface=true)` | `set_app_settings(app_is_watchface=false)` |
| Purpose | Passive time display | Interactive: games, tools, viewers |
| Buttons | **None** (Up/Down = timeline, Select = launcher). Input = accelerometer tap only | Full click API: single/repeating/long/multi/raw |
| Exit | System-controlled | BACK pops window stack; app exits when empty |
| Update driver | Tick timer (MINUTE_UNIT) | Clicks + AppTimer loops (games ~33ms) |

If the request involves buttons, menus, game input, or multiple screens → watchapp. Read [reference/watchapp-guide.md](reference/watchapp-guide.md) before implementing a watchapp.

### Which language is this project in?

Not a choice — the open project already is one or the other, and you cannot convert it.
Read it off `list_files()`:

| File tree shows | Language | Write |
|---|---|---|
| `src/embeddedjs/main.js` (target=embeddedjs) | Alloy — JS on the watch (Moddable XS) | `src/embeddedjs/main.js`, `src/embeddedjs/manifest.json` |
| `src/c/main.c` and no embeddedjs files | C | `src/c/*.c` |

Alloy projects also carry `src/c/mdbl.c` — VM boot boilerplate. **Never edit or delete it.**

Read [reference/alloy-guide.md](reference/alloy-guide.md) fully before writing an Alloy
project. If the user asks for something the project's language cannot do (Alloy runs on
emery, gabbro and flint only; C has no watch-side `fetch()`), say so and offer to have them
create a new project of the other type — you cannot change `project_type`.

## CRITICAL: End-to-End Delivery

This skill MUST produce a final `.pbw` file, test it, AND visually verify it looks correct.

Every watchface request follows this complete flow:

1. **Research** → [SUBAGENT] Gather requirements, study samples and tutorials
2. **Design** → [SUBAGENT] Plan architecture and visuals
3. **Implement** → `write_file()` all project sources
4. **Build** → `build()` to compile on the CloudPebble build farm
5. **Test** → `install()`, then `screenshot()` and look at the image
6. **Iterate** → Fix issues until the screenshot looks good
7. **Deliver** → Describe the verified screenshot in chat

**Never stop until:**
- `build()` reports success
- `screenshot()` returned an image of the running watchface
- Visual verification confirms it looks correct
- A FINAL `screenshot()` of the finished result is the last thing you did before
  writing your reply. Screenshot after every install, and again after every
  visual change: the user is watching a panel that renders each one, and they are
  cheap.

## CRITICAL: Battery Efficiency

**ALWAYS use `MINUTE_UNIT` for `tick_timer_service_subscribe()`.** NEVER use `SECOND_UNIT` unless the user explicitly requests a seconds display. `SECOND_UNIT` causes the watchface to redraw every second, which drastically reduces battery life. Design all watchfaces to update on minute boundaries.

For animated watchfaces that use `app_timer_register()`, only run animations briefly (e.g., on a tap event or for a few seconds after minute change), then stop the timer. Continuous animation is acceptable only when the user explicitly requests it.

---

## CloudPebble Delta

This is a fork of `coredevices/pebble-watchface-agent-skill` running inside CloudPebble.
Where this section contradicts the rest of the file, this section wins.

**There is no bash, no filesystem, no `pebble` CLI.** Every action is a tool call. No
`mkdir`, no `cd`, no `ls`, no `python3 scripts/...`. Only `SKILL.md`, `reference/` and
`templates/` are shipped — the upstream `scripts/`, `samples/` and `tutorials/` directories
are not here, so do not try to read them. Where the text below points at a sample or
tutorial, use the templates and reference docs instead.

**You work on an existing project, not a new directory.** The project already exists with a
UUID, a name, and a source tree. Start with `list_files()`, not with scaffolding.

**You are already told the state.** Every message you get ends with a `<project-state>`
block: settings, target platforms with their screen sizes, the file tree, and which watch
the emulator is running right now. Lay out for what it says, not for a default. `list_files()`
returns the same block, refreshed — call it after changing settings or when in doubt.

**A watchface MUST be flagged as one, or it is not a watchface.** New CloudPebble projects
default to `is_watchface = false`, which builds a watch *app*: it lands in the app menu and
never appears as a face, no matter how the C code looks. The screenshot looks perfect and
the result is still wrong. So whenever the user asks for a watchface, call:

    set_app_settings(app_is_watchface=true)

Do this BEFORE the first `build()`. It is cheap and idempotent — if it is already set,
setting it again costs nothing.

**And the same in reverse.** A watch app MUST have `app_is_watchface=false`, or it installs
over the user's clock instead of appearing in the app menu they open it from. When the user
corrects you about what they are building — "this isn't a watchface, I want an app" —
rewriting the code is only half the fix: call `set_app_settings` in the same breath.
Observed: an app was rewritten correctly and left flagged as a face, so it still replaced
the watchface.

`set_app_settings` also carries the rest of the project's settings: `app_platforms`,
`app_long_name`, `app_short_name`, `app_company_name`, `app_version_label`,
`app_capabilities` (`location`, `health`, `configurable`), `app_keys`, `menu_icon`,
`app_is_hidden`, `app_is_shown_on_communication`, `app_modern_multi_js`, `name`. Only the
fields you pass change. Use it instead of hunting for a `package.json` — there isn't one.
It is scoped to this project and cannot touch anything else in the account.

**Files are addressed by `project_path`, not disk path.** `write_file("src/c/main.c", ...)`
— the same paths the file tree shows. Creating a path that does not exist creates the file.

**No `wscript`, no `package.json`.** CloudPebble generates both from project settings. They
are not in the source tree and you cannot write them. That means:

- **Target platforms come from the project's `app_platforms` setting**, not from
  `targetPlatforms` in a package.json. Emery may or may not be enabled. Read the platform
  list from the `<project-state>` block and lay out for *that*, not for emery by default.
  When in doubt, use `layer_get_bounds()` and the layout works everywhere.
- UUID, display name, SDK version, `enableMultiJS`, `capabilities` and `messageKeys` are
  project settings, and `set_app_settings` writes all of them: `app_uuid`, `app_keys`,
  `app_capabilities`, `app_platforms`, `app_dependencies`, `menu_icon` and the rest. You
  do not need to ask the user for any of it.

**The project's language is fixed.** A CloudPebble project is C or Alloy from the moment it
is created, and `project_type` is not something `set_app_settings` can change. Do not
choose between them: read `list_files()` and write in whichever the project already is —
`src/embeddedjs/main.js` present means Alloy, otherwise C. If the request needs the other
one, say so and offer to have the user create a new project.

**Dependencies are a setting.** There is no `pebble package install`, but npm packages
are yours to set: `set_app_settings(app_dependencies='{"@moddable/pebbleproxy": "^0.1.3"}')`.
It replaces the whole list, so include any that are already there.

**Images and fonts are resources.** `write_resource(file_name, kind, content_base64,
resource_ids)` adds one and gives it the id C code draws with (`RESOURCE_ID_<id>`); kinds
are `png`, `png-trans`, `bitmap`, `pbi`, `font`, `raw`. Replacing keeps the existing ids.
`delete_resource` removes one. Assets travel base64 through the tool, so keep them small --
drawing in code is usually cheaper and always sharper than a shipped bitmap.

**No subagents.** Do the research and design phases inline. Phases 1 and 2 are still worth
doing, just do them yourself.

**The emulator belongs to the user's browser tab.** You cannot start, stop or reboot it.
If `install()` or `screenshot()` returns a no-emulator error, or says the emulator
rejected the install, that is a fact about their browser and NOT a fault in your code —
the panel starts one for them automatically and tells you when it is ready. Keep going
with `build()` meanwhile, and never delete working features to bisect an emulator problem.

**Read the reference docs with `read_reference`, not `read_file`.** `read_file` only sees
project source files. `read_reference('reference/alloy-guide.md')` serves this skill's own
guides and templates; call it with no name to list them. Read the guide before guessing at
an API in a runtime you do not know.

**Phase 6 (assets) and Phase 8 (publish) do not apply.** Deliver at Phase 7: describe the
verified screenshot, and say the build is installed in their emulator.

---

## Platform Reference

| Platform | Model | Resolution | Shape | Colors |
|----------|-------|------------|-------|--------|
| **emery** | **Pebble Time 2** | **200x228** | **Rect** | **64-color** |
| gabbro | Pebble Round 2 | 260x260 | Round | 64-color |
| basalt | Pebble Time | 144x168 | Rect | 64-color |
| chalk | Pebble Time Round | 180x180 | Round | 64-color |
| aplite | Pebble Classic | 144x168 | Rect | B&W |
| diorite | Pebble 2 | 144x168 | Rect | B&W |
| flint | Pebble 2 Duo | 144x168 | Rect | 64-color |

**Emery is the default and exclusive target.** If the user wants gabbro (round) support, that should be a second pass after the emery version is finalized.

---

## Phase 1: Research [USE SUBAGENT — complex projects only]

**Skip subagents for simple projects.** If the request is covered by a template plus one reference doc (basic digital/analog face, single-screen app), read the template and relevant reference file directly and go straight to implementation. Spawn subagents only for complex projects: multi-screen apps, games with novel mechanics, heavy custom graphics, or unfamiliar API combinations.

**For complex projects, spawn a research subagent** using Agent tool with `subagent_type: "Explore"` to:

### Gather Requirements
Ask the user (use AskUserQuestion if unclear):
- **Type**: Digital, analog, animated, or artistic?
- **Elements**: Time, date, battery, weather, custom graphics?
- **Animation**: Static, subtle, or complex animations?
- **Weather/Web data**: Does it need weather or other internet data?

### Study Existing Code
The subagent should read and analyze:
- `samples/aqua-pbw/src/c/main.c` — animated watchface patterns
- `tutorials/c-watchface-tutorial/part1/` — basic time + date
- `tutorials/c-watchface-tutorial/part4/` — weather via AppMessage + pkjs

Key patterns to extract:
- Data structures for animated elements
- Animation loop structure
- Drawing functions
- Memory management patterns
- Battery-aware throttling
- Weather/AppMessage communication (if needed)

Also have subagent read relevant reference docs:
- `reference/pebble-api-reference.md`
- `reference/animation-patterns.md`
- `reference/drawing-guide.md`
- `reference/watchapp-guide.md` — if building a watchapp (buttons, menus, window stack, game loop)
- `reference/alloy-guide.md` — if building in Alloy (JS)

---

## Phase 2: Design [USE SUBAGENT — complex projects only]

For simple projects, do the layout math below inline (it is mandatory either way). **For complex projects, spawn a planning subagent** using Agent tool with `subagent_type: "Plan"` to:

### Create Design Specification
- Screen layout for **emery (200x228)** rectangular display
- Element positions and sizes
- Animation behavior and timing (intervals, speeds)
- Color scheme (64-color palette)
- Data structures needed
- Layer hierarchy
- Whether weather/web data is needed (requires pkjs)

### CRITICAL: Layout Planning to Prevent Cropping
**You MUST calculate exact pixel positions to ensure nothing is cropped.**

For emery (200x228):
```
Available space: X: 0-199, Y: 0-227
Safe margins: 2-5 pixels from edges
```

For each visual element, calculate:
1. **Y position**: Where does it start vertically?
2. **Element height**: How tall is it?
3. **Bottom edge**: Y_position + height must be < 228 (with margin)

Example layout calculation for emery:
```
SCREEN_WIDTH = 200, SCREEN_HEIGHT = 228
Time text:     Y=60,  height=50  → bottom at 110 ✓
Date text:     Y=115, height=26  → bottom at 141 ✓
Weather:       Y=145, height=24  → bottom at 169 ✓
Battery bar:   Y=0,   height=3   → bottom at 3   ✓
```

**FAIL CONDITIONS to check in design:**
- Element bottom edge >= SCREEN_HEIGHT (228 for emery)
- Element right edge >= SCREEN_WIDTH (200 for emery)
- GPath points with negative offsets that extend beyond anchor point
- Elements positioned relative to SCREEN_HEIGHT without accounting for element size

### GPath Positioning Guide
GPaths use **relative coordinates from an anchor point**. Calculate carefully:

```c
// GPath points are RELATIVE to where you move_to
static GPoint castle_points[] = {
    {-35, 0},    // 35px LEFT of anchor, AT anchor Y
    {-35, -40},  // 35px left, 40px ABOVE anchor
    {35, 0},     // 35px RIGHT of anchor
};

// Anchor positioning calculation:
// If castle_points go from Y=0 to Y=-40 (40px tall, extending UP)
// And you want bottom of castle at Y=223 (5px margin from 228)
// Then anchor Y = 223 (the base of the castle)
gpath_move_to(castle_path, GPoint(SCREEN_WIDTH/2, 223));
```

### Architecture Planning
- What structs are needed?
- How many animated elements?
- Update interval (MINUTE_UNIT for tick, 50ms for brief animations)
- Memory pre-allocation strategy
- Does it need pkjs for weather/web data?

---

## Phase 3: Implementation

**Do this directly** (not a subagent) — write all files:

### Write ALL Required Files

**1. Project settings** — not files. UUID, display name, SDK version, target platforms,
`enableMultiJS`, `capabilities` and `messageKeys` all live in CloudPebble's project
settings, and there is no `package.json` or `wscript` in the source tree to write. If the
watchface needs `messageKeys` or the `location` capability, say so in chat and ask the
user to set it in Settings.

**2. Platform bounds** — the `<project-state>` block lists the enabled platforms and their
screen sizes. Lay out for those. `layer_get_bounds()` works everywhere.

**3. src/c/main.c** (REQUIRED)
Write complete watchface code following the design from Phase 2.

Use templates as starting points:
- [templates/animated-watchface.c](templates/animated-watchface.c) — animated watchfaces
- [templates/static-watchface.c](templates/static-watchface.c) — static/analog watchfaces
- [templates/weather-watchface.c](templates/weather-watchface.c) — watchfaces with weather data

**4. src/pkjs/index.js** (REQUIRED if weather/web data needed)
Use [templates/pkjs-weather.js](templates/pkjs-weather.js) as starting point.

The pkjs file runs on the phone and handles:
- GPS location via `navigator.geolocation.getCurrentPosition()`
- HTTP requests via `XMLHttpRequest` to web APIs
- Sending data to watch via `Pebble.sendAppMessage()`
- Receiving requests from watch via `appmessage` event

**Open-Meteo API** (free, no API key):
```
https://api.open-meteo.com/v1/forecast?latitude=LAT&longitude=LON&current=temperature_2m,weather_code
```

### Code Requirements
- `#include <pebble.h>`
- Implement `main()`, `init()`, `deinit()`
- Window with load/unload handlers
- `tick_timer_service_subscribe(MINUTE_UNIT, tick_handler)` — **ALWAYS MINUTE_UNIT**
- For brief animations: `app_timer_register()` with 50ms interval
- Pre-allocate GPath in window_load
- Destroy all resources in unload handlers
- Fixed-point math only (sin_lookup/cos_lookup)
- Use `layer_get_bounds()` for screen dimensions — don't hardcode sizes
- Register AppMessage callbacks BEFORE calling `app_message_open()`

### Watchapp Differences (C)

For watchapps (`set_app_settings(app_is_watchface=false)`), see [reference/watchapp-guide.md](reference/watchapp-guide.md). Deltas from the watchface flow:
- Add `window_set_click_config_provider()` — buttons work
- Multi-screen: one Window per screen, push/pop on the window stack
- Games: AppTimer loop at ~33ms calling `layer_mark_dirty()`, raw click subscriptions for held buttons, cancel timer in window disappear
- MenuLayer/ScrollLayer call their own `*_set_click_config_onto_window()`
- Save state with `persist_*` in window disappear
- No MINUTE_UNIT constraint — apps redraw on input/timer, but still cancel timers when idle

### Alloy Implementation (when the project is an Alloy project)

See [reference/alloy-guide.md](reference/alloy-guide.md) — read it fully before writing
files. CloudPebble already created the scaffolding; you edit these:

```
src/embeddedjs/main.js        # all watch logic — start from templates/alloy-watchface.js
src/embeddedjs/manifest.json  # register every extra module and font here
src/pkjs/index.js             # ONLY if networking (pebbleproxy) or Clay settings
src/c/mdbl.c                  # VM boot stub, already present — NEVER touch
```

There is no `package.json` and no `wscript` to write — CloudPebble generates both.

Key rules:
- Platforms come from `app_platforms`; Alloy builds for emery, gabbro and flint only
- Watchface: subscribe to `minutechange` — it fires immediately on registration, so that IS
  the initial draw. CloudPebble's own Alloy templates use `Pebble.addEventListener(...)`
  while the guide shows `watch.addEventListener(...)`; `read_file()` the project's existing
  `main.js` and keep whichever form is already there
- Watchapp buttons: `import Button from "pebble/button"` (apps only)
- Networking: the `@moddable/pebbleproxy` dependency plus a 3-line pkjs shim, then watch-side `fetch()` works. You cannot add dependencies — ask the user to add it in the Dependencies pane
- Animation: `setInterval(draw, 33)` for ~30fps; stop when done
- Extra JS module files MUST be registered in manifest.json `modules`

---

## Phase 4: Build PBW

### Run the Build
Call `build()`. It compiles on the CloudPebble build farm and returns the build status
plus the full compiler log. A failed compile is a normal result, not an error — read the
log and fix the code.

### Handle Build Errors
If the build fails:
1. Read the compiler errors in the returned log
2. Fix the C code (syntax, types, missing includes)
3. Call `build()` again
4. Repeat until it succeeds

---

## Phase 5: Test in QEMU Emulator

**REQUIRED** — Must test AND visually verify before delivering.

### Step 1: Install
Call `install()`. It pushes the last successful build into the emulator the user has open
in their browser. If it returns a no-emulator error, that is not a build failure — tell
the user to open the emulator, and carry on with `build()`.

Give it a couple of seconds to load and render before screenshotting.

### Emulator Hygiene (common failure modes)

- **Screenshot shows a different app, an old watchface, or the watchface picker** → the
  emulator is not showing what you just installed. `install()` again and re-screenshot. Do
  NOT debug your code from a screenshot of something else.
- **Screenshot shows the launcher with your app highlighted but not running** → either it
  was never launched, or it crashed. `install()` again, then check `logs()`.
- **Install or screenshot times out** → the emulator is wedged or gone. It belongs to the
  user's browser tab: ask them to restart it from Build & Run, and keep using `build()`
  meanwhile.

### Step 2: Capture Screenshot (MANDATORY)
Call `screenshot()`. The image comes back to you directly — there is no file to read.

### Step 3: Visual Verification (MANDATORY)

Look at the image `screenshot()` returned.

**CRITICAL: Perform thorough visual verification using this detailed checklist.**

#### A. Cropping Check (FAIL if any element is cut off)
- [ ] **All visual elements fully visible** — No element should be cut off at screen edges
- [ ] **Key graphics not clipped** — Main visual elements must be 100% within 200x228 bounds
- [ ] **No overflow at bottom** — Elements near y=228 must have margin
- [ ] **No overflow at sides** — Elements near x=0 or x=200 must have margin
- [ ] **Text not truncated** — All text fits within its designated area

#### B. Positioning Check (FAIL if layout doesn't match design)
- [ ] **Time in correct position** — Matches the designed location
- [ ] **Visual elements properly placed** — Each element appears where designed
- [ ] **Proportional spacing** — Elements have appropriate margins
- [ ] **Center alignment** — Centered elements are actually centered (x=100 center)

#### C. Color Scheme Check (FAIL if colors don't match design)
- [ ] **Primary colors correct** — Main colors match design spec
- [ ] **Contrast sufficient** — Text and elements are readable

#### D. Design Intent Check (FAIL if doesn't match user request)
- [ ] **Theme recognizable** — Watchface represents the requested theme
- [ ] **Key features prominent** — Main visual features are visible
- [ ] **Overall composition balanced** — Layout looks intentional

**STOP AND FIX if ANY check fails.** Do not proceed to delivery with visual issues.

### Step 4: Fix Issues and Re-test

If visual verification fails:

#### Fixing Cropping Issues
- **Bottom cropping**: Reduce Y coordinates, use `bounds.size.h - H - margin` formula
- **Side cropping**: Use `bounds.size.w / 2 - element_width / 2` for centering
- **Common mistake**: Hardcoding 144x168 values instead of using `layer_get_bounds()`

#### Iteration Process:
1. Identify which check(s) failed
2. Apply the specific fix
3. Rebuild: `build()`
4. Reinstall: `install()`
5. New screenshot: `screenshot()`
6. Re-verify by looking at the new image
7. **Repeat until ALL checks pass**

### Step 5: Check Logs for Errors
Call `logs(seconds)` to drain app logs from the emulator. Logs only start flowing once the
app is running, so call it after `install()`; a crash may only show up after a reinstall.

Look for:
- APP_LOG errors
- Crashes or exceptions
- Memory warnings

---

## Phase 6: Generate Assets — not applicable

App icons, preview GIFs and the `scripts/` directory are not available here. Skip
straight to Phase 7.

---

## Phase 7: Deliver

### Report to User
After successful build AND visual verification:

1. **A final screenshot.** Take a fresh `screenshot()` of the finished result,
   after the last build and install — not one from earlier in the turn. The chat
   panel shows it to the user, and it is the only proof they have that the thing
   works. Ending without one is an incomplete turn.

2. **Build**: say which build id succeeded — the user can open it in Build & Run

3. **Visual Confirmation**: describe what that final screenshot shows

4. **Installed**: say the build is installed in the emulator they are watching

5. **Round support**: suggest a second pass for gabbro (260x260) if the user wants it

---

## Phase 8: Publish to Pebble App Store — not applicable

Publishing is not available here. There is no `pebble` CLI and no login.

---

## Weather Watchface Architecture

When a watchface needs weather or other web data, use the **AppMessage + PebbleKit JS** pattern:

```
Watch (C code) ←AppMessage→ Phone (PebbleKit JS) ←HTTP→ Web API
```

### Required Files
1. **src/c/main.c** — C code with AppMessage handlers
2. **src/pkjs/index.js** — JavaScript running on phone

### Required Project Settings
`enableMultiJS`, the `location` capability and the `messageKeys`
(`TEMPERATURE`, `CONDITIONS`, `REQUEST_WEATHER`) are project settings, not files. Ask the
user to set them in Settings — you cannot.

### C Side Pattern
```c
// In init(), register callbacks BEFORE opening:
app_message_register_inbox_received(inbox_received_callback);
app_message_open(128, 128);

// Receive weather data:
static void inbox_received_callback(DictionaryIterator *iterator, void *context) {
    Tuple *temp_tuple = dict_find(iterator, MESSAGE_KEY_TEMPERATURE);
    Tuple *cond_tuple = dict_find(iterator, MESSAGE_KEY_CONDITIONS);
    // Update display...
}

// Request refresh every 30 minutes from tick_handler:
if (tick_time->tm_min % 30 == 0) {
    DictionaryIterator *iter;
    AppMessageResult result = app_message_outbox_begin(&iter);
    if (result == APP_MSG_OK) {
        dict_write_uint8(iter, MESSAGE_KEY_REQUEST_WEATHER, 1);
        app_message_outbox_send();
    }
}
```

### JS Side Pattern (src/pkjs/index.js)
```javascript
// Use Open-Meteo API (free, no API key)
function getWeather() {
    navigator.geolocation.getCurrentPosition(function(pos) {
        var url = 'https://api.open-meteo.com/v1/forecast?' +
            'latitude=' + pos.coords.latitude +
            '&longitude=' + pos.coords.longitude +
            '&current=temperature_2m,weather_code';
        // Fetch and send via Pebble.sendAppMessage()...
    });
}

Pebble.addEventListener('ready', function() { getWeather(); });
Pebble.addEventListener('appmessage', function(e) {
    if (e.payload['REQUEST_WEATHER']) getWeather();
});
```

See `tutorials/c-watchface-tutorial/part4/` for a complete working example.

### Visual Weather Reactions (C Side)

The pkjs sends weather as human-readable strings ("Clear", "Cloudy", "Rain", etc.). To change visuals based on weather (sky color, particles, accessories), reverse-map the string to a numeric code on the C side:

```c
static int s_weather_code = -1;  // -1 = no data yet

// In inbox_received_callback, after reading CONDITIONS:
const char *c = cond_tuple->value->cstring;
if (strcmp(c, "Clear") == 0) s_weather_code = 0;
else if (strcmp(c, "Cloudy") == 0) s_weather_code = 2;
else if (strcmp(c, "Rain") == 0 || strcmp(c, "Showers") == 0) s_weather_code = 63;
else if (strcmp(c, "Snow") == 0) s_weather_code = 73;
else if (strcmp(c, "Fog") == 0) s_weather_code = 45;
else if (strcmp(c, "T-Storm") == 0) s_weather_code = 95;
else s_weather_code = 2;

// Then in draw functions, branch on s_weather_code:
if (s_weather_code == 0) { /* draw sun, blue sky */ }
else if (s_weather_code >= 61) { /* draw rain drops */ }
else if (s_weather_code >= 71) { /* draw snowflakes, white ground */ }
```

### Battery-Efficient Visual Variety

Even with `MINUTE_UNIT` updates (no animation timer), you can create visual variety by using deterministic math tied to the minute counter. Each minute tick increments a frame counter, and drawing functions use it to offset positions:

```c
static int s_frame = 0;  // incremented in tick_handler

// In draw function — "animated" rain/snow without a timer:
int rx = (i * 37 + s_frame * 7) % bounds.size.w;
int ry = 40 + (i * 23 + s_frame * 11) % sky_height;
```

This gives a different scene each minute without burning battery on sub-second redraws.

---

## Tutorial Reference

Complete working tutorial examples are in `tutorials/c-watchface-tutorial/`:

| Part | What It Teaches |
|------|-----------------|
| part1 | Basic time + date display with system fonts |
| part4 | Weather via AppMessage + PebbleKit JS + Open-Meteo API |
| part6 | User settings via Clay configuration framework |

These are sourced from [coredevices/c-watchface-tutorial](https://github.com/coredevices/c-watchface-tutorial).

The Alloy equivalent is [coredevices/alloy-watchface-tutorial](https://github.com/coredevices/alloy-watchface-tutorial) (part1 basic Poco face → part2 custom fonts → part3 battery/BT → part4 weather via watch-side fetch → part5 Quick View → part6 Clay settings + localStorage). Its part1 is captured verbatim in `templates/alloy-*`.

---

## Subagent Summary

| Phase | Subagent Type | Purpose |
|-------|---------------|---------|
| Research | `Explore` | Read samples, tutorials, extract patterns |
| Design | `Plan` | Create implementation plan for emery (200x228) |
| Implement | Direct | `write_file()` all project sources |
| Build | Direct | `build()` |
| Test | Direct | `install()`, `screenshot()`, look at the image |
| Iterate | Direct | Fix code until the screenshot looks correct |
| Deliver | Direct | Describe the verified screenshot in chat |

---

## Quick Reference

### Emery Screen Dimensions (Default Target)
| Property | Value |
|----------|-------|
| Width | 200 px |
| Height | 228 px |
| Shape | Rectangular |
| Colors | 64-color |
| Center X | 100 |
| Center Y | 114 |

### All Platform Dimensions
| Platform | Resolution | Shape | Color |
|----------|------------|-------|-------|
| emery    | 200x228    | Rect  | 64-color |
| gabbro   | 260x260    | Round | 64-color |
| basalt   | 144x168    | Rect  | 64-color |
| chalk    | 180x180    | Round | 64-color |
| aplite   | 144x168    | Rect  | B&W |
| diorite  | 144x168    | Rect  | B&W |
| flint    | 144x168    | Rect  | 64-color |

### Key APIs
```c
// Drawing
graphics_fill_circle(ctx, center, radius);
graphics_draw_line(ctx, start, end);
graphics_fill_rect(ctx, rect, corner_radius, corners);
graphics_draw_arc(ctx, rect, scale_mode, angle_start, angle_end);
graphics_fill_radial(ctx, rect, scale_mode, inset, angle_start, angle_end);

// Fixed-point trig (NO FLOATS!)
sin_lookup(angle);  // 0 to TRIG_MAX_ANGLE (65536)
cos_lookup(angle);  // returns -TRIG_MAX_RATIO to +TRIG_MAX_RATIO
DEG_TO_TRIGANGLE(degrees);  // macro for conversion

// Time — ALWAYS USE MINUTE_UNIT
tick_timer_service_subscribe(MINUTE_UNIT, tick_handler);

// Screen dimensions — use dynamically, don't hardcode
Layer *window_layer = window_get_root_layer(window);
GRect bounds = layer_get_bounds(window_layer);
// bounds.size.w = 200 on emery, bounds.size.h = 228 on emery

// AppMessage (for weather/web data)
app_message_register_inbox_received(callback);
app_message_open(128, 128);
```

### Build & Test Commands

There is no shell. These are tools, called directly.

| Tool | Does |
|------|------|
| `build()` | Compile the project on the CloudPebble build farm, returns status + build log |
| `install()` | Install the last successful build into the user's running emulator |
| `screenshot()` | Capture the emulator screen, returned to you as an image |
| `press(button, hold_ms)` | up / select / down / back / shake — drive the app and screenshot the result |
| `logs(seconds)` | Drain app logs from the watch and console.log from the phone-side JS |
| `list_files()` | The project's current state: settings, platforms and their screen sizes, files, emulator |
| `write_resource(...)` | Add or replace an image, font or blob the app loads by resource id |
| `delete_resource(file_name)` | Remove a resource |
| `write_binary_file(path, content_base64)` | Alloy assets under `src/embeddedjs` (.png, .pdc, .ttf) |
| `set_app_settings(...)` | Change this project's settings. `app_is_watchface=true` is REQUIRED for a face |
| `read_file(path)` / `write_file(path, content)` / `delete_file(path)` | Edit sources by `project_path` |

Preview GIFs, app icons, device deploys, `pebble login` and `pebble publish` are not
available in v1. Skip Phase 6 and Phase 8 entirely.

### Emulator Interaction

`press(button, hold_ms)` drives the watch: `up`, `select`, `down`, `back`, or `shake`
(an accelerometer tap). `hold_ms` defaults to 120; use ~700 for a long press.

An interactive app is not verified until you have driven it — open it, scroll it, play a
turn — screenshotting as you go. A watchface has no buttons at all, so `shake` is its only
input.

Touch is not available: emery and gabbro have touchscreens, but touch reaches the emulator
over VNC rather than the control channel these tools use.

---

## Constraints

1. **No Floating Point** — Use sin_lookup/cos_lookup only
2. **Pre-allocate Memory** — Create GPath in window_load for static shapes (clock hands, fixed elements). Small dynamic shapes that change position each frame (e.g. character silhouettes at computed coordinates) can use create/destroy in draw functions — this is acceptable for paths with ~3-6 points
3. **MINUTE_UNIT Only** — Never use SECOND_UNIT unless explicitly requested
4. **Clean Resources** — Destroy in unload handlers
5. **NULL Checks** — Verify pointers before use
6. **Overflow Protection** — Use modulo on counters
7. **Dynamic Bounds** — Use `layer_get_bounds()` not hardcoded screen sizes
8. **Register Before Open** — AppMessage callbacks must be registered before `app_message_open()`

---

## File Checklist

Before building (C project):
- [ ] `set_app_settings(app_is_watchface=...)` — true for a face, false for an app
- [ ] `src/c/main.c` with complete code
- [ ] `src/pkjs/index.js` (if weather/web data needed)
- [ ] Any needed project settings asked for in chat (platforms, messageKeys, capabilities)

Before building (Alloy project):
- [ ] `set_app_settings(app_is_watchface=...)`
- [ ] `src/embeddedjs/main.js` with complete code
- [ ] `src/embeddedjs/manifest.json` — every extra module and font registered
- [ ] `src/c/mdbl.c` left exactly as it is
- [ ] `src/pkjs/index.js` with the pebbleproxy shim (if networking)
- [ ] `@moddable/pebbleproxy` — ask the user to add it in Dependencies (if networking)

Build: `build()`
Test: `install()`
Screenshot: `screenshot()`
