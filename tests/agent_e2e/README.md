# Agent chat panel — browser e2e

One Playwright script that drives a real Chromium against a running CloudPebble and
asserts the AI chat column works end to end: log in → open a native project →
chat panel renders → send a prompt → assistant text streams back → a tool card
appears → the composer re-enables.

```
e2e_agent.py   the test
run.sh         runs it in the official Playwright docker image
artifacts/     screenshots, trace.zip, console.log  (gitignored)
```

## Why docker

**Chromium cannot launch on this dev host.** AppArmor here restricts unprivileged
user namespaces, so the Chromium sandbox fails to start and `--no-sandbox` is not
something to bake into a test. The browser therefore always runs inside the
official Playwright image, which ships a matching Chromium and the right
seccomp/userns setup.

**The loop box is the runner.** `cloudpebble-loop-dev.exe.xyz` has docker 29 and
reaches `cloudpebble-dev.exe.xyz` over public HTTPS. `run.sh` also works on any
other machine that grows a working docker — nothing in it is host-specific.

## Running it

```bash
# on cloudpebble-loop-dev
CP_USERNAME=testuser CP_PASSWORD=... tests/agent_e2e/run.sh
```

or drop a gitignored `.env` next to `run.sh`:

```
CP_USERNAME=testuser
CP_PASSWORD=<the test account password, not stored in this repo>
```

Secrets are never in the repo — `run.sh` refuses to start without the two
credential vars and passes everything to the container as env.

| Var | Default | |
|---|---|---|
| `CP_BASE_URL` | `https://cloudpebble-dev.exe.xyz` | target instance |
| `CP_USERNAME` / `CP_PASSWORD` | — | **required** |
| `CP_PROJECT_ID` | `6` | a native C project owned by that user |
| `CP_PROMPT` | "List the source files in this project, then stop." | cheap prompt that still forces a tool call |
| `CP_UI_TIMEOUT_MS` | `30000` | page/widget waits |
| `CP_TURN_TIMEOUT_MS` | `180000` | waits on the agent turn |
| `PLAYWRIGHT_IMAGE` | `mcr.microsoft.com/playwright/python:v1.49.0-jammy` | bump to the current tag freely |

Exit code 0 pass, 1 fail, 2 misconfiguration.

## Artifacts

A screenshot per milestone (`01-project-loaded` … `07-turn-done`, plus
`99-failure` on a fail), a Playwright trace (`trace.zip`, open with
`npx playwright show-trace`) and every browser console line (`console.log`).
The trace is the point of this being remote-friendly: you can debug a run you
never watched.

## Notes

- The prompt is deliberately trivial. This tests the plumbing — panel, POST,
  SSE relay, event rendering — not watchface quality. It still spends real
  Claude tokens against Eric's subscription, so don't loop it.
- If it fails with *"no #chat-wrapper"*, the panel is behind the feature flag:
  the user's id must be in `AGENT_ENABLED_USERS` on the server.
- Login goes to `/accounts/login/?next=…` rather than `LOGIN_URL` (`/#login`,
  a JS modal on the landing page) — the plain Django form is the stable thing
  to drive.
- Selectors are read from `ide/templates/ide/project.html` and
  `ide/static/ide/js/agent.js`. If those ids/classes change, this breaks loudly,
  which is the intent.
