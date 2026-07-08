#!/bin/bash
set -euo pipefail

# Deploy qemu + ycmd + nginx to Hetzner (production emulator + code completion)
# Uses compose.hetzner.yml — the slim stack. The full docker-compose.yml is
# for local development only and does not run on this box.
# Config is read from .env (QEMU_SERVER, QEMU_SSH_KEY)
# Usage: ./deploy_hetzner.sh [--no-cache]

NO_CACHE=""
if [[ "${1:-}" == "--no-cache" ]]; then
  NO_CACHE="--no-cache"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

: "${QEMU_SERVER:?Set QEMU_SERVER in .env (e.g. root@1.2.3.4)}"
: "${QEMU_SSH_KEY:?Set QEMU_SSH_KEY in .env (e.g. ~/.ssh/id_exe)}"

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

echo "==> Building images..."
$SSH "cd ~/cloudpebble && $DC build $NO_CACHE"

echo "==> Restarting services..."
# --remove-orphans also removes containers from the old full-stack deploy
# (web, celery, postgres, redis, s3). Volumes are left untouched.
$SSH "cd ~/cloudpebble && $DC down --remove-orphans && $DC up -d"

echo "==> Waiting for services to start..."
sleep 3

echo "==> Container status:"
$SSH "cd ~/cloudpebble && $DC ps"

echo ""
echo "==> Deploy complete."
