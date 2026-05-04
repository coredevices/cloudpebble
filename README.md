# CloudPebble

A web-based IDE for developing Pebble smartwatch applications. Write C or JavaScript, compile, and test on an in-browser emulator — all from the browser.

Try it out at https://cloudpebble.repebble.com

## Self-hosting instructions

```bash
git clone https://github.com/coredevices/cloudpebble.git
cd cloudpebble
# .env ships with working defaults — review and customise as needed
docker compose build
docker compose up
# Open http://localhost:8080 and register an account
```

All runtime configuration lives in `.env`. Edit it before building:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PEBBLE_SDK_VERSION` | `4.9.169` | SDK version installed in all containers (build fails if unset) |
| `NODE_VERSION_WEB` | `20.11.0` | Node.js version in web/celery images |
| `NODE_VERSION_YCMD` | `16.20.2` | Node.js version in ycmd image |
| `NGINX_PORT` | `8080` | Host port nginx binds to |
| `PUBLIC_URL` | `http://localhost:8080` | Public-facing URL (see note below) |
| `EXPECT_SSL` | `no` | Set to `yes` for HTTPS deployments |
| `EMULATOR_FIXED_LIMIT` | `90` | Max concurrent emulators |
| `LIBPEBBLE_PROXY` | `wss://cloudpebble-proxy.repebble.com/tool` | libpebble proxy WebSocket URL |
| `CLOUDPEBBLE_PROXY` | `wss://cloudpebble-proxy.repebble.com/tool` | CloudPebble proxy WebSocket URL |
| `PEBBLE_AUTH_URL` | `https://auth.rebble.io` | Rebble Auth endpoint |
| `FIREBASE_PROJECT_ID` | `coreapp-ce061` | Firebase project for push notifications |
| `POSTGRES_HOST_AUTH_METHOD` | `trust` | PostgreSQL auth method (**change for production**) |
| `NGINX_IMAGE` | `nginx:alpine` | nginx container image |
| `REDIS_IMAGE` | `redis:7` | Redis container image |
| `POSTGRES_IMAGE` | `postgres:16` | PostgreSQL container image |

> **Note:** `PUBLIC_URL` tells Django how the outside world reaches the site (used for generating callback URLs, media paths, etc.). `NGINX_PORT` controls which host port nginx binds to. In dev, they typically match; in production behind a reverse proxy, `PUBLIC_URL` is the external URL and `NGINX_PORT` may differ.

### Test GitHub Repo Sync locally

The `GitHub Repo Sync` card changes based on `PUBLIC_URL`, not the browser hostname.

To verify the localhost behavior:

```bash
# No extra env needed — defaults in .env already set localhost:8080
docker compose up -d --build --force-recreate web nginx
# Open http://localhost:8080/ide/settings
```

Expected in `GitHub Repo Sync`: `Install GitHub app` and `Link your GitHub account`.

To complete the localhost GitHub Repo Sync flow:

1. In the localhost `GitHub Repo Sync` card, click `Install GitHub app`.
2. Complete the GitHub App installation in GitHub.
3. After installation, GitHub currently redirects to the production callback URL instead of back to localhost.
4. Close that production tab or window.
5. Return to your existing localhost `Settings` page and click `Link your GitHub account` in the `GitHub Repo Sync` card to complete the local auth step.

In short: on localhost, `Install GitHub app` handles the GitHub-side installation, then `Link your GitHub account` finishes the local CloudPebble auth flow.

In production, the `Install GitHub app` button handles the full Repo Sync flow: it installs the GitHub App, authorizes it, and redirects back to the production `Settings` page with the user linked for `GitHub Repo Sync`.

To verify the prod-like behavior locally:

```bash
# Override PUBLIC_URL to simulate a production hostname
sed -i 's|^PUBLIC_URL=.*|PUBLIC_URL=http://prod-preview:8080|' .env
docker compose up -d --build --force-recreate web nginx
# Restore when done
sed -i 's|^PUBLIC_URL=.*|PUBLIC_URL=http://localhost:8080|' .env
```

Expected in `GitHub Repo Sync`: `Install GitHub app` only.

This prod-like mode is for checking button visibility only. Do not click the GitHub buttons in this mode unless that non-local `PUBLIC_URL` is actually reachable.

You can confirm the running value with:

```bash
docker compose exec web /usr/local/bin/python manage.py shell -c "from django.conf import settings; import urllib.parse; print(settings.PUBLIC_URL); print(urllib.parse.urlsplit(settings.PUBLIC_URL).hostname)"
```

Use a hard refresh or private window if the old button state is still shown.

For HTTPS behind a reverse proxy:

```bash
# Edit .env:
#   PUBLIC_URL=https://your-domain.com
#   EXPECT_SSL=yes
docker compose build
docker compose up -d
```

## Host it easily on exe.dev

Use this to bootstrap a brand-new `exe.dev` VM and get CloudPebble running.

### 1. Prepare local repo + env

```bash
git clone https://github.com/coredevices/cloudpebble.git
cd cloudpebble
# .env ships with working defaults — override for your deployment:
sed -i 's|^PUBLIC_URL=.*|PUBLIC_URL=https://YOURDOMAIN.exe.xyz|' .env
sed -i 's|^EXPECT_SSL=.*|EXPECT_SSL=yes|' .env
sed -i 's|^NGINX_PORT=.*|NGINX_PORT=8000|' .env
```

### 2. Create/prepare the exe.dev VM

From your machine:

```bash
ssh -i ~/.ssh/id_pub YOURDOMAIN.exe.xyz
```

On the VM:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
mkdir -p ~/cloudpebble
exit
```

Reconnect after the `docker` group change:

```bash
ssh -i ~/.ssh/id_pub YOURDOMAIN.exe.xyz
docker --version
docker compose version
exit
```

### 3. Sync code to VM

From your machine:

```bash
rsync -avz --delete --exclude='.git' --exclude='.env' \
  -e "ssh -i ~/.ssh/id_exe" \
  /path/to/cloudpebble/ YOURDOMAIN.exe.xyz:~/cloudpebble/
```

### 4. Build and start services

```bash
ssh -i ~/.ssh/id_exe YOURDOMAIN.exe.xyz "
  cd ~/cloudpebble &&
  docker compose build &&
  docker compose up -d
"
```

### 5. Verify

```bash
curl -I https://YOURDOMAIN.exe.xyz/
ssh -i ~/.ssh/id_exe YOURDOMAIN.exe.xyz "cd ~/cloudpebble && docker compose ps"
ssh -i ~/.ssh/id_exe YOURDOMAIN.exe.xyz "cd ~/cloudpebble && docker compose logs web --tail 100"
```

### 6. Create a test user (optional)

```bash
ssh -i ~/.ssh/id_exe YOURDOMAIN.exe.xyz "
  cd ~/cloudpebble &&
  docker compose exec -T web /usr/local/bin/python manage.py shell -c \"
from django.contrib.auth.models import User;
User.objects.create_user('testuser', 'test@example.com', 'testpass123')
\"
"
```

## Architecture

```
Browser → nginx:$NGINX_PORT → web:80       (Django app)
                              → qemu:80      (emulator, WebSocket/VNC)
                              → ycmd:80      (code completion, WebSocket)
                              → s3:4569      (build artifacts via /s3builds/)

web ←→ postgres      (database)
    ←→ redis         (Celery broker)
    ←→ s3            (source files, builds)

celery ←→ same backends (background build tasks)
```

### Services

| Service | Image | Purpose |
|---------|-------|---------|
| **nginx** | `$NGINX_IMAGE` | Reverse proxy, WebSocket routing, S3 proxy |
| **web** | Python 3.11 + Django 4.2 | IDE frontend and REST API |
| **celery** | Same as web | Background build tasks |
| **qemu** | Python 3.11 + QEMU | Pebble emulator with VNC |
| **ycmd** | Python 3.11 + ycmd/clang | C code completion |
| **redis** | `$REDIS_IMAGE` | Celery task broker |
| **postgres** | `$POSTGRES_IMAGE` | Database |
| **s3** | kuracloud/fake-s3 | S3-compatible object storage |

### Three Codebases

| Directory | Service | Framework |
|-----------|---------|-----------|
| `cloudpebble/` | web + celery | Django 4.2 + Celery 5.x |
| `cloudpebble-qemu-controller/` | qemu | Flask + gevent |
| `cloudpebble-ycmd-proxy/` | ycmd | Flask + gevent |

The web and celery containers share the same Docker image. `RUN_WEB=yes` starts Django; `RUN_CELERY=yes` starts the Celery worker.

## How It Works

### Building Apps

1. User clicks "Run" in the browser
2. Django creates a `BuildResult` and queues a Celery task
3. Celery assembles source files from S3, runs `pebble build`
4. Compiled `.pbw` is uploaded to S3
5. Browser polls for build status and shows results

### Emulator

1. Browser POSTs to `/qemu/launch` via nginx
2. QEMU controller spawns a QEMU ARM emulator + pypkjs (JS runtime)
3. Browser connects via WebSocket for VNC display
4. Emulators auto-kill after 5 minutes without a ping

Platforms: aplite (Pebble), basalt (Time), chalk (Time Round), diorite (Pebble 2), emery (Time 2), gabbro (Round 2)

### Code Completion

1. Browser POSTs to `/ycmd/spinup` to initialize a session
2. Proxy spawns a ycmd instance per target platform with Pebble SDK headers
3. Browser connects via WebSocket for real-time completions, errors, and go-to-definition

## Development

```bash
# Run tests
docker compose exec web python manage.py test

# Run a single test module
docker compose exec web python manage.py test ide.tests.test_compile

# Django shell
docker compose exec web python manage.py shell

# Database migrations
docker compose exec web python manage.py migrate

# Create a user via CLI
docker compose exec web python manage.py shell -c "
from django.contrib.auth.models import User
User.objects.create_user('username', 'email@example.com', 'password')
"
```

### Django App Structure

- `ide/api/` — REST endpoints returning JSON (project CRUD, source files, resources, builds, git, emulator, autocomplete)
- `ide/models/` — Database models: Project, SourceFile, ResourceFile, BuildResult, UserSettings
- `ide/tasks/` — Celery tasks: `build.py` (compile), `git.py` (GitHub sync), `archive.py` (import/export)
- `ide/static/ide/js/` — Frontend JavaScript (jQuery + Backbone + CodeMirror SPA)
- `auth/` — Authentication (local accounts + Pebble OAuth2)

### Environment Variables

All configuration lives in `.env` (see the full table in the self-hosting section). Key variables:

| Variable | Purpose |
|----------|---------|
| `PEBBLE_SDK_VERSION` | SDK version across all containers — single source of truth |
| `PUBLIC_URL` | Public-facing URL. In dev, port matches `NGINX_PORT`; in production behind a reverse proxy, they may differ |
| `NGINX_PORT` | Host port nginx binds to (default: `8080`) |
| `SECRET_KEY` | Django secret key (auto-generated and persisted if not set) |
| `EXPECT_SSL` | Set to `yes` for HTTPS deployments |
| `POSTGRES_HOST_AUTH_METHOD` | PostgreSQL auth — **change from `trust` for production** |

## Tech Stack

- **Backend:** Python 3.11, Django 4.2 LTS, Celery 5.x, PostgreSQL 16, Redis
- **Frontend:** jQuery 2.1, Backbone, CodeMirror 4.2, noVNC (Bower-managed)
- **Build:** pebble-tool 5.0 + SDK 4.9, ARM GCC cross-compiler
- **Emulator:** coredevices/qemu (ARM Cortex-M3/M4), pypkjs (JS runtime)
- **Code Completion:** ycm-core/ycmd with Clang completer

## Known Limitations

| Limitation | Notes |
|------------|-------|
| JSHint/linting | Project-level JS lint settings are currently not working end-to-end |
| Code completion | WIP — container builds but not yet functional end-to-end |

## Credits

- Originally created by Katharine Berry
- Later supported by [Pebble Technology](https://github.com/pebble)
- Community revival at [Rebble](https://rebble.io)
- Docker Compose setup by [iSevenDays](https://github.com/iSevenDays/cloudpebble-composed)
- 2026 modernization by Eric Migicovsky (and Claude Code!)

## License

MIT — see [LICENSE](LICENSE).
