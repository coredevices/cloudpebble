#!/bin/bash
set -euo pipefail

# Deploy qemu + ycmd + nginx to Hetzner (production emulator + code completion)
# Uses compose.hetzner.yml — the slim stack. The full docker-compose.yml is
# for local development only and does not run on this box.
# Config is read from .env, then .env.local (put QEMU_SERVER / QEMU_SSH_KEY in
# .env.local — it is gitignored and never rsynced).
# Usage: ./deploy_hetzner.sh [--no-cache]

NO_CACHE=""
if [[ "${1:-}" == "--no-cache" ]]; then
  NO_CACHE="--no-cache"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for f in .env .env.local; do
  if [ -f "$SCRIPT_DIR/$f" ]; then
    set -a
    source "$SCRIPT_DIR/$f"
    set +a
  fi
done

: "${QEMU_SERVER:?Set QEMU_SERVER in .env.local (e.g. root@1.2.3.4)}"
: "${QEMU_SSH_KEY:?Set QEMU_SSH_KEY in .env.local (e.g. ~/.ssh/id_exe)}"
: "${PEBBLE_SDK_VERSION:?Set PEBBLE_SDK_VERSION in .env}"

SSH="ssh -i $QEMU_SSH_KEY $QEMU_SERVER"

echo "==> Syncing code to $QEMU_SERVER..."
rsync -avz --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='.DS_Store' \
  -e "ssh -i $QEMU_SSH_KEY" \
  "$SCRIPT_DIR/" "$QEMU_SERVER":~/cloudpebble/

DC="docker compose -f compose.hetzner.yml"

# The server's .env is never rsynced, so its copies of the build pins go stale and
# silently rebuild an old SDK. Pass them from this repo instead — a shell env var
# beats the remote .env in compose.
BUILD_PINS=$(printf 'PEBBLE_SDK_VERSION=%q NODE_VERSION_YCMD=%q' \
  "$PEBBLE_SDK_VERSION" "${NODE_VERSION_YCMD:-16.20.2}")

echo "==> Building images (SDK $PEBBLE_SDK_VERSION)..."
$SSH "cd ~/cloudpebble && $BUILD_PINS $DC build $NO_CACHE"

echo "==> Restarting services..."
# --remove-orphans also removes containers from the old full-stack deploy
# (web, celery, postgres, redis, s3). Volumes are left untouched.
$SSH "cd ~/cloudpebble && $DC down --remove-orphans && $DC up -d"

echo "==> Waiting for services to start..."
sleep 3

echo "==> Container status:"
$SSH "cd ~/cloudpebble && $DC ps"

echo ""
echo "==> Deploy complete (SDK $PEBBLE_SDK_VERSION)."
