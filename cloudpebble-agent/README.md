# cloudpebble-agent

The agent loop behind the CloudPebble chat panel. One FastAPI container running the
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/hosting). It owns no
filesystem, no compiler, no emulator, and no `bash` — every action it takes is an HTTPS
call to CloudPebble or a websocket frame to the user's emulator.

Design doc: [`../AGENT_PLAN.md`](../AGENT_PLAN.md).

## Layout

```
service.py              /turn, /cancel, /health (SSE)
tools.py                in-process MCP tools — the agent's only capabilities
cloudpebble_client.py   HTTP client for the CloudPebble API
emulator.py             qemu websocket: install, screenshot, logs
session_store.py        SessionStore → CloudPebble transcript routes
skills/pebble-watchface Forked watchface skill, baked to /opt/agent-workspace/.claude/skills/
docker-compose.yml      one service, 127.0.0.1:8300 → :8000 in the container
deploy_agent.sh         rsync + docker compose build/up
```

## Deploy

```bash
./deploy_agent.sh
```

Target defaults to `cloudpebble-loop-dev.exe.xyz`; override with `AGENT_HOST` /
`AGENT_SSH_KEY` (or `SSH_KEY`) in the repo-root `.env`. The script rsyncs this directory
to `~/cloudpebble-agent/` on the target and runs `docker compose build && up -d`.

The container binds **localhost only**. Django on `cloudpebble-dev` reaches it through
nginx + TLS on the loop box; the browser never talks to it. Point the nginx vhost at
`http://127.0.0.1:8300`, then set `AGENT_URL` and the shared secret `AGENT_AUTH_HEADER` in
CloudPebble's settings to match.

## Credentials

Everything secret lives in `~/.agent-env` on the target (mode 0600), read by compose via
`env_file: ../.agent-env`. **Nothing is baked into the image** and nothing is committed.

```
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...   # required
AGENT_AUTH_HEADER=<shared secret>          # required, must match Django's AGENT_AUTH_HEADER
AGENT_MODEL=claude-sonnet-5
```

Generate the shared secret, don't invent one — `/turn` is behind a public TLS vhost and
whoever guesses it spends the Claude Max quota:

```bash
openssl rand -hex 32
```

Both sides fail closed when it is unset: the service returns 500 and Django refuses to
relay. `deploy_agent.sh` refuses to deploy if `~/.agent-env` is missing or has no
`CLAUDE_CODE_OAUTH_TOKEN` or no `AGENT_AUTH_HEADER`.

### Rotating the OAuth token

The token is a long-lived OAuth credential from Eric's Claude Max plan and **expires after
roughly one year**. `claude setup-token` is interactive and needs a browser, so it cannot
be run on the VM:

```bash
# on a laptop with a browser
claude setup-token          # → sk-ant-oat01-...

# then, on the loop box
ssh cloudpebble-loop-dev.exe.xyz
vi ~/.agent-env             # replace CLAUDE_CODE_OAUTH_TOKEN=
cd ~/cloudpebble-agent && docker compose up -d --force-recreate
```

**Usage draws from the Claude Max subscription**, not an API key — the same pool as
interactive Claude Code. A screenshot-heavy loop is expensive (images dominate). Two
consequences to keep in mind:

- Hitting the weekly limit kills a turn mid-flight. It surfaces in chat as "Claude usage
  limit reached", distinct from a build error; don't let it retry into the wall.
- `AGENT_MAX_TURNS_PER_DAY` on the Django side is what protects the pool. Keep it low.

## Logs

```bash
ssh cloudpebble-loop-dev.exe.xyz
cd ~/cloudpebble-agent
docker compose logs -f agent          # live
docker compose logs agent --tail 200  # recent
docker compose ps                     # status
curl -fsS http://127.0.0.1:8300/health
```

## The skill

`skills/pebble-watchface/` is a fork of
[`coredevices/pebble-watchface-agent-skill`](https://github.com/coredevices/pebble-watchface-agent-skill)
(upstream `.claude/skills/pebble-watchface/`, commit `b91bf6b`, 2026-05-18), baked into the
image at `/opt/agent-workspace/.claude/skills/pebble-watchface/`. The SDK loads it via
`setting_sources=['project']` with `cwd=/opt/agent-workspace`.

Divergence from upstream, deliberately kept small so improvements can be pulled forward:

| Change | Why |
|---|---|
| New **CloudPebble Delta** section + a pointer to it at the top | No bash, no filesystem, existing projects only |
| **Build & Test Commands** table replaces the `pebble ...` shell block | `build()` `install()` `screenshot()` `logs()` are tools, not commands |
| `scripts/` not shipped | All five need a shell and a working directory; there is neither. Preview GIFs and app icons are out of scope for v1 |
| Residual `pebble ...` blocks in phases 3-8 rewritten as tool calls | Upstream's build/install/screenshot/logs/publish steps assume the CLI |
| `templates/package.json.template` and `templates/wscript.template` dropped | CloudPebble generates both from project settings; the agent cannot write them |

`reference/` is byte-identical to upstream; `templates/` keeps only the four source
templates. Everything that makes the
skill worth having is untouched: emery layout math and 2-5px margins, `MINUTE_UNIT` over
`SECOND_UNIT`, fixed-point `sin_lookup`/`cos_lookup`, `layer_get_bounds()` over hardcoded
dimensions, AppMessage callbacks registered before `app_message_open()`, and the visual
verification checklist.

To pull upstream changes:

```bash
git remote add watchface-skill https://github.com/coredevices/pebble-watchface-agent-skill.git
git fetch watchface-skill
git diff b91bf6b..watchface-skill/main -- .claude/skills/pebble-watchface/
```

Apply the diff to `skills/pebble-watchface/` and re-apply the three changes above.
