# CloudPebble AI Agent — build plan

Chat panel in the CloudPebble IDE that builds Pebble watchfaces with AI, builds them
with the existing build farm, and installs them into the emulator the user is already
watching.

**Core principle: we own no agent loop.** The loop is
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/hosting). The watchface
expertise is [`coredevices/pebble-watchface-agent-skill`](https://github.com/coredevices/pebble-watchface-agent-skill).
The build system and emulator are the ones already running in production. We write glue.

Scope for v1: **watchfaces, native C, existing projects.**

---

## 0. Decisions

| | |
|---|---|
| Target environment | `cloudpebble-dev.exe.xyz` — the existing dev instance, not prod |
| Emulator | The user's live browser-launched emulator. Agent installs into what they're watching. |
| Chat UI | Straight into the IDE, third column. No throwaway standalone page. |
| Loop host | New exe.dev VM, separate from the dev instance |
| Model | Sonnet 5 default. Opus toggle deferred — A/B during dogfood, layout+screenshot work is where it would pay. |
| Auth | Eric's Claude Max subscription via `CLAUDE_CODE_OAUTH_TOKEN`. No API key. |

### Model auth

[Supported](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan):
Agent SDK usage in your own projects draws from your Claude subscription's usage limits.
Headless mechanism is a long-lived OAuth token:

```bash
claude setup-token          # once, interactively, on a machine with a browser
                            # → sk-ant-oat01-..., ~1 year validity
```

Set `CLAUDE_CODE_OAUTH_TOKEN` on the agent VM. The SDK picks it up with no other config.

Three consequences that are build-relevant, not paperwork:

- **Usage is shared with Eric's interactive Claude Code.** A screenshot-heavy agent loop
  burns the same pool he codes against — images are expensive. The per-user turn cap in §6
  is now protecting his ability to work, not a bill. Keep it low to start.
- **Limit exhaustion is a runtime failure mode.** A turn can die mid-flight when the weekly
  limit hits. Surface it in chat as "Claude usage limit reached", distinct from a build
  error, and don't let the model retry into the wall.
- **One token, one identity.** Correct for dogfood. Before this reaches other CloudPebble
  users, revisit — serving many users off one personal subscription is a different question
  than using your own plan for your own project. Phase 8+ decision, not a blocker now.

Rotation: the token expires in about a year and `claude setup-token` is interactive. Note
it in the deploy runbook so it doesn't fail silently twelve months from now.

### Emulator liveness

The user's emulator dies with their browser session (`SharedPebble.handleEmulatorDisconnected`).
So `install()` and `screenshot()` can fail mid-turn through no fault of the agent. Handle it
explicitly: the tool returns a typed "no emulator" error, the model reports it in chat as
"open the emulator to see this run" rather than treating it as a build failure and looping.
The `build()` tool never depends on the emulator, so a session with no emulator still makes
progress — it just can't visually verify.

---

## 1. Architecture

```
browser (existing IDE)              cloudpebble (prod)            agent VM (new, exe.dev)
┌───────────────────────┐          ┌────────────────────┐        ┌──────────────────────┐
│ #chat-wrapper         │──POST───▶│ /ide/agent/message │───────▶│ POST /turn           │
│  (new jQuery pane)    │          │  mints scoped token│        │  claude-agent-sdk    │
│                       │◀──SSE────│ /ide/agent/stream  │◀───────│  streams events      │
├───────────────────────┤          │                    │        │                      │
│ #sidebar-wrapper      │          │ SourceFile (DB)    │◀──HTTPS┤ tools:               │
│  emulator canvas ─────┼──ws──┐   │ Celery run_build   │◀───────┤   read/write_file    │
│  file tree            │      │   │ AgentSession       │        │   build              │
├───────────────────────┤      │   └────────────────────┘        │   install            │
│ #pane-parent (editor) │      │                                 │   screenshot         │
└───────────────────────┘      │   ┌────────────────────┐        │   logs               │
                               └──▶│ qemu-controller    │◀──ws───┤ (libpebble2)         │
                                   │  (Hetzner)         │        └──────────────────────┘
                                   └────────────────────┘
```

Three things run in three places, and only the middle one holds state:

| | Where | State |
|---|---|---|
| Chat UI | browser, existing IDE | none |
| Files, builds, sessions | CloudPebble prod | Postgres + S3 (authoritative) |
| Agent loop | new exe.dev VM | none — transcripts mirrored to CloudPebble |

The agent has **no filesystem, no compiler, no emulator, and no `bash`.** Every action it
takes is an HTTPS call to CloudPebble or a libpebble frame to the emulator. That is what
makes it stateless and what removes container-escape from the threat model.

---

## 2. The agent VM (new)

New exe.dev VM, `agent.<something>.exe.xyz`, docker + nginx + TLS, same bootstrap as the
README's exe.dev section.

One container. Python 3.11 + `claude-agent-sdk` + `libpebble2` + `requests` + FastAPI.
No Pebble SDK, no arm toolchain, no qemu. ~200 MB image.

### Endpoints

```
POST /turn        {session_id, project_id, cp_token, cp_base_url, emulator, message}
                  → SSE stream of agent events, then 200
POST /cancel      {session_id}
GET  /health
```

Auth on the VM: shared secret header from CloudPebble, `AGENT_LAUNCH_AUTH_HEADER`, exactly
like `settings.QEMU_LAUNCH_AUTH_HEADER` does for the qemu controller today. The VM is not
public.

Model credentials, VM-local only, never in Django and never in the browser:

```bash
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...   # from `claude setup-token`, see §0
AGENT_MODEL=claude-sonnet-5                # Opus toggle deferred
```

### The turn

```python
async for msg in query(
    prompt=message,
    options=ClaudeAgentOptions(
        resume=session_id,                  # None on first turn
        session_store=CloudPebbleSessionStore(cp_base_url, cp_token),
        cwd='/opt/agent-workspace',         # holds .claude/skills/, read-only, no writes
        setting_sources=['project'],        # so the skill loads
        max_turns=12,
        allowed_tools=[...],                # only our MCP tools — no Bash, no Read/Write
        mcp_servers={'cloudpebble': cp_tools(cp_base_url, cp_token, project_id, emulator)},
        env={'CLAUDE_CONFIG_DIR': per_turn_tmpdir,
             'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1'},
    ),
):
    yield sse(msg)
```

Stateless: hydrate the transcript from CloudPebble at turn start, mirror it back as it
grows, hold nothing after the response closes. The "hybrid session" pattern from the
hosting guide. Because the workspace is empty and the skill is baked into the image, the
transcript is the complete session state — nothing else to persist.

### Tools (in-process MCP server)

| Tool | CloudPebble call |
|---|---|
| `list_files()` | `GET /ide/project/<id>/info` → `source_files[]` (name, id, target, file_path) |
| `read_file(path)` | `GET /ide/project/<id>/source/<file_id>/load` |
| `write_file(path, content)` | `POST .../source/<file_id>/save`, or `POST .../create_source_file` if new |
| `delete_file(path)` | `POST .../source/<file_id>/delete` |
| `build()` | `POST /ide/project/<id>/build/run` → poll `/ide/task/<task_id>` → `GET .../build/last` + `.../build/<id>/log` |
| `install()` | `GET .../build/<id>/download/<file>` then libpebble `AppInstaller` over the emulator ws |
| `screenshot()` | libpebble `Screenshot.grab_image()` → PNG, returned to the model as an image block |
| `logs(seconds)` | libpebble app-log service, drained for N seconds |

### Emulator wire protocol — VERIFIED (spike 0, 2026-07-29)

Proven end to end from `cloudpebble-loop-dev` against `cloudpebble-dev` over public
`wss://`: launched a basalt emulator, authenticated, requested a screenshot, decoded a
144×168 PNG showing the real watch screen. No browser involved.

```
wss://cloudpebble-dev.exe.xyz/qemu/<uuid>/ws/phone
```

Frames are length-agnostic binary; **first byte is the opcode**:

| Dir | Frame | Meaning |
|---|---|---|
| → | `09 <len:B> <token>` | v1 auth. `<token>` is the emulator token from `/qemu/launch` |
| ← | `09 00` / `09 01` | auth ok / bad token |
| ← | `08 FF` / `08 00` | connected / closed remotely |
| → | `01 <size:BE16> <endpoint:BE16> <payload>` | message **to** watch |
| ← | `00 <size:BE16> <endpoint:BE16> <payload>` | message **from** watch |
| → | `04 <pbw bytes>` | install app |
| ← | `05 <status:BE32>` | install finished — this is how `install()` knows it's done |
| ← | `02 <utf-8>` | pkjs phone log — this is `logs()` |

Endpoints: `SCREENSHOT=8000`, `APP_LOGS=2006`, `LOGS=2000`, `APP_MANAGER=6000`,
`PUTBYTES=48879`. Screenshot response: 13-byte header `>B I I I` = code, version, width,
height, then raw pixels. Version 2 is 8bpp, 2 bits per channel (`(p>>4)&3, (p>>2)&3, p&3`,
×85); version 1 is 1bpp.

Three gotchas that cost time and will bite the implementation:

1. **`/qemu/launch` returns before pypkjs is listening.** Connecting immediately gets
   `ECONNREFUSED` through the relay. Sleep ~10s, then retry with backoff.
2. **Don't reconnect to an emulator that already had a client.** Reattaching to a
   previously-used or long-idle instance hangs at the auth frame with no error and no log.
   One connection per emulator lifetime; if it drops, relaunch.
3. **Inbound is `0x00`, not `0x01`.** `0x01` is outbound-only. Filtering inbound on `0x01`
   silently receives nothing forever.

Reference implementation: `spike_emulator.py` (scratchpad) — ~170 lines, `websocket-client`
only, no `libpebble2` needed. Port it into `cloudpebble-agent/emulator.py` as-is.

`screenshot()` returning a real image block is the whole reason this works — the model
sees its own watchface and fixes its own layout bugs, which is exactly what the skill's
verification checklist is for.

---

## 3. CloudPebble changes

### 3.1 Models — `ide/models/agent.py`

```python
class AgentSession(models.Model):
    project      = FK(Project, related_name='agent_sessions')
    user         = FK(settings.AUTH_USER_MODEL)
    sdk_session_id = CharField(max_length=64, blank=True)   # SDK's session id, for resume
    status       = CharField(choices=['idle','running','error','cancelled'])
    created / last_active = DateTimeField
    turn_count   = IntegerField(default=0)

class AgentMessage(models.Model):
    session  = FK(AgentSession, related_name='messages')
    seq      = IntegerField                 # monotonic, for ?since=
    role     = CharField(['user','assistant','tool','system'])
    content  = JSONField                    # rendered event, not raw transcript
    created  = DateTimeField

class AgentTranscript(models.Model):        # SessionStore backing
    sdk_session_id = CharField(unique=True, db_index=True)
    session        = FK(AgentSession)
    data           = BinaryField            # JSONL batches, append-only
```

`AgentMessage` is what the chat panel renders. `AgentTranscript` is what the SDK resumes
from. Keep them separate — one is a UI concern, one is an SDK contract.

### 3.2 API — `ide/api/agent.py`, mounted under `/ide/`

| Route | Does |
|---|---|
| `POST project/<id>/agent/start` | create `AgentSession`, return id |
| `POST project/<id>/agent/message` | mint scoped token, POST `/turn` on the VM, relay SSE into `AgentMessage` rows + redis stream |
| `GET  project/<id>/agent/stream?since=<seq>` | SSE to browser, reads redis stream, falls back to `AgentMessage` rows |
| `POST project/<id>/agent/cancel` | `POST /cancel` on the VM, mark cancelled |
| `POST agent/transcript/<sdk_session_id>` | `SessionStore` mirror sink (agent token auth) |
| `GET  agent/transcript/<sdk_session_id>` | `SessionStore` hydrate source (agent token auth) |

Written in the house style: `@login_required @json_view`, `get_object_or_404(Project, pk=..., owner=request.user)`.

The relay-through-Django choice matters: the browser never talks to the agent VM, so no
CORS, no second auth surface, no public agent endpoint. Same posture as `launch_emulator`,
which mints a token and proxies rather than exposing the controller.

### 3.3 Scoped agent token

New: `utils/agent_token.py`. Random 32-byte urlsafe token in redis,
`agent-token-<token> → {user_id, project_id, session_id}`, `ex=1800`, minted per turn.

A decorator `@agent_token_required` resolves it to `(user, project)` and is accepted **only**
by: `project_info`, source load/save/create/delete, build run/last/log/download, and the
two transcript routes. Nothing else. Precedent for the pattern is
`ide/api/qemu.py:generate_phone_token`, which already does redis-with-TTL tokens.

The token is the security boundary of this whole feature. It is scoped to one project, one
user, one session, expires in 30 minutes, and cannot touch account settings, other
projects, publishing, or GitHub.

### 3.4 Build queue separation

`ide/tasks/build.py:run_build` is a `@shared_task` on the default queue. Agent builds get
`queue='agent_builds'` and their own worker, so a looping agent can't starve human
compiles. Same task, different route.

### 3.5 Settings

```python
AGENT_URL              = _environ.get('AGENT_URL', '')          # https://agent.x.exe.xyz/
AGENT_AUTH_HEADER      = _environ.get('AGENT_AUTH_HEADER', '')
AGENT_ENABLED_USERS    = _environ.get('AGENT_ENABLED_USERS', '')  # comma ids, feature flag
AGENT_MAX_TURNS_PER_DAY = int(_environ.get('AGENT_MAX_TURNS_PER_DAY', '50'))
```

Mirrors the existing `QEMU_URLS` / `QEMU_LAUNCH_AUTH_HEADER` / `YCM_URLS` pattern.

---

## 4. Chat panel

Third column. Chat is not a pane in the `#main-pane` system — it persists across pane
switches, because you want it visible while looking at the editor.

```
.project-container .row-fluid
  #chat-wrapper     360px, collapsible, state in localStorage   ← new
  #sidebar-wrapper  emulator canvas + nav + file tree           unchanged
  #pane-parent      #main-pane                                  unchanged
```

Emulator stays at the top of the sidebar, so chat and the live watchface sit side by side.
For a watchface the preview *is* the watch — the agent installs into the emulator the user
is watching, and they see it appear.

New: `ide/static/ide/js/agent.js` (`CloudPebble.Agent`), `ide/static/ide/css/agent.css`,
markup in `ide/templates/ide/project.html`.

Event rendering:

| SDK event | Renders as |
|---|---|
| assistant text | bubble |
| `write_file` | collapsed diff card, click opens the file in the real editor pane |
| `build` | status chip, click opens the Build & Run pane |
| `screenshot` | inline image |
| `install` / `logs` | one-line status |
| error / cancel | inline error with retry |

No React. `useChat` and AI SDK UI are the wrong dependency for a bower/Backbone app; the
SDK's event stream renders fine in ~250 lines of jQuery.

File conflicts: if the user has unsaved changes in a file the agent wants to write, the
write is refused with a message in chat rather than silently clobbered. Clicking a diff
card reloads that file in the editor. No OT, no live cursors.

---

## 5. Skill

Fork `coredevices/pebble-watchface-agent-skill` into `agent-vm/skills/pebble-watchface/`,
baked into the image at `/opt/agent-workspace/.claude/skills/`.

One edit: the "Build & Test Commands" block becomes our tool names.

```
pebble build                                → build()
pebble install --emulator emery             → install()
pebble screenshot --no-open ... shot.png     → screenshot()
pebble logs --emulator emery                 → logs()
python3 scripts/create_preview_gif.py        → (dropped in v1)
```

Everything else carries over untouched, and it is the actual value: emery layout math and
2-5px safety margins, `MINUTE_UNIT` not `SECOND_UNIT`, `sin_lookup`/`cos_lookup` fixed
point only, `layer_get_bounds()` over hardcoded dimensions, AppMessage callbacks registered
before `app_message_open()`, the visual verification checklist, `reference/`, `templates/`.

Add a CloudPebble delta file: project platforms come from project settings (`app_platforms`)
rather than the skill's emery default, files are addressed by `project_path` not disk path,
and there is no `wscript`/`package.json` editing outside what the source API exposes.

Track upstream as a real remote so their improvements can be rebased in.

---

## 6. Limits, cost, failure

- **Turn cap.** `AGENT_MAX_TURNS_PER_DAY` per user in redis. Token cost dominates
  everything else "by an order of magnitude or more" — this is the only thing standing
  between a bug and a large bill.
- **`max_turns=12`** per turn bounds tool-call round trips. There is no session timeout in
  the SDK; this is the bound.
- **Transcript regrowth.** Every turn re-sends the conversation. Prompt caching absorbs
  most of it, but long sessions cost more per turn. Watch it; add compaction if needed.
- **No Celery retries on agent work.** A retried turn re-spends tokens and re-applies file
  writes. `max_retries=0`.
- **`mirror_error`.** A transcript batch the store rejects retries 3× then is **dropped
  silently** while the query continues. Log and alert, or resume will break mysteriously.
- **Feature flag.** `AGENT_ENABLED_USERS` gates the UI and the API. Ship dark.

---

## 7. Security posture

| Risk | Mitigation |
|---|---|
| Agent runs arbitrary code | It can't. No `bash`, no `Read`/`Write`, no filesystem. `allowed_tools` is our 8 tools. |
| Agent token used to reach other projects | Token is scoped to `(user, project, session)`, 30-min TTL, accepted by 8 endpoints only |
| Agent VM exposed | Not public. Shared-secret header, called only by CloudPebble. Browser never talks to it. |
| Prompt injection via project files | Blast radius is one project's own files. Approve-mode toggle on writes for the paranoid case. |
| Anthropic key leakage | Lives only on the agent VM, never in the browser, never in Django |
| Runaway build spend | Separate build queue + per-user turn cap |

The thing to keep true as this grows: **the day the agent gets `bash` back, most of this
table stops holding** and the container isolation work from the earlier sketches comes
back. Don't add `bash` casually.

---

## 8. Build order

| # | Work | Depends on | Est |
|---|---|---|---|
| 0 | ~~**Spike:** emulator ws — auth, screenshot~~ **DONE** — protocol verified, see §2. Install-a-pbw leg still unproven (needs a built pbw) | — | ✅ |
| 1 | ~~Agent VM bootstrap~~ **DONE** — `cloudpebble-loop-dev.exe.xyz` exists: docker 29, python 3.12, uv, `claude` 2.1.220, OAuth token at `~/.agent-env` (0600), reaches dev over HTTPS | — | ✅ |
| 2 | Agent service: FastAPI `/turn`, `claude-agent-sdk`, MCP tools 1-4 (files + build) against prod API with a hand-made token | 0 | 2d |
| 3 | CloudPebble: models, migration, agent token + decorator, `agent/start`/`message`/`stream`/`cancel`, transcript routes | — | 2d |
| 4 | Tools 5-8 (install, screenshot, logs) over libpebble | 0, 2 | 1d |
| 5 | Skill fork + CloudPebble delta, baked into image | 2 | 0.5d |
| 6 | Chat panel: markup, css, `agent.js`, event rendering, diff cards, inline screenshots | 3 | 3d |
| 7 | Session resume via `SessionStore`, cancel, caps, feature flag | 3 | 1.5d |
| 8 | Dogfood, prompt tuning against the 10-watchface set, fix what the screenshots reveal | all | 2d |

~13 days. Phase 0 gates 4; nothing else is blocked by unknowns.

Later, explicitly not now: prompt box on the projects page for new-project-from-description,
alloy/JS projects, preview GIFs, publish flow, `bash` + a real container,
[AI SDK `HarnessAgent`](https://ai-sdk.dev/v7/docs/ai-sdk-harnesses) to A/B Claude Code vs
Codex vs Pi.

---

## 9. Repo layout

```
cloudpebble-agent/                  new top-level dir, deployed to the exe.dev VM
  Dockerfile
  docker-compose.yml
  requirements.txt                  claude-agent-sdk, libpebble2, fastapi, requests
  service.py                        /turn, /cancel, /health, SSE
  tools.py                          MCP tool definitions
  cloudpebble_client.py             HTTP client for the CloudPebble API
  emulator.py                       libpebble2 over the qemu ws
  session_store.py                  SessionStore → CloudPebble transcript routes
  skills/pebble-watchface/          forked skill + CloudPebble delta
  deploy_agent.sh                   rsync + docker compose up, like deploy_qemu.sh

cloudpebble/ide/models/agent.py
cloudpebble/ide/api/agent.py
cloudpebble/ide/migrations/00XX_agent.py
cloudpebble/utils/agent_token.py
cloudpebble/ide/static/ide/js/agent.js
cloudpebble/ide/static/ide/css/agent.css
cloudpebble/ide/templates/ide/project.html      (edit)
cloudpebble/ide/urls.py                          (edit)
cloudpebble/cloudpebble/settings.py              (edit)
```

`deploy_agent.sh` follows `deploy_qemu.sh`: read `.env`, rsync, `docker compose up -d`.
