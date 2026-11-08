#!/bin/bash
set -euo pipefail

# Deploy to dev (cloudpebble-dev.exe.xyz)
# All services on one box: web, celery, postgres, redis, s3, qemu, nginx
# Uses local postgres — NOT Supabase
#
# Usage: ./deploy_dev.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEV_HOST="cloudpebble-dev.exe.xyz"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_exe}"
SSH="ssh -i $SSH_KEY $DEV_HOST"

echo "==> Syncing code to $DEV_HOST..."
rsync -avz --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.env.local' \
  --exclude='.DS_Store' \
  --exclude='__pycache__' \
  --exclude='cloudpebble/agent/' \
  -e "ssh -i $SSH_KEY" \
  "$SCRIPT_DIR/" "$DEV_HOST":~/cloudpebble/

# The app is web+celery. qemu and ycmd are sidecars that change rarely, and
# rebuilding them on every deploy costs ~8GB of layers -- enough to fill this
# box's 19GB disk and fail the deploy partway through. Pass --all when a sidecar
# actually changed.
if [[ "${1:-}" == "--all" ]]; then
  BUILD_TARGETS=""
  PROFILES="--profile emulator --profile codecomplete"
  echo "==> Building ALL images (including qemu + ycmd sidecars)..."
else
  BUILD_TARGETS="web celery"
  PROFILES=""
  echo "==> Building app images (web, celery). Use --all to rebuild sidecars too."
fi

# This box has a 19GB disk and each rebuild leaves the previous image layers
# behind, which has failed a deploy mid-build more than once. Reclaim first:
# dangling images and build cache only, so nothing in use is touched.
echo "==> Reclaiming disk..."
$SSH "docker image prune -f >/dev/null 2>&1; docker builder prune -af >/dev/null 2>&1; df -h / | tail -1"

$SSH "cd ~/cloudpebble && docker compose $PROFILES build $BUILD_TARGETS"

echo "==> Restarting services..."
# Recreate rather than restart: env changes and new code only take effect on a
# fresh container. nginx resolves upstreams at startup, so it must come after.
$SSH "cd ~/cloudpebble && docker compose --profile emulator --profile codecomplete up -d $BUILD_TARGETS"
$SSH "cd ~/cloudpebble && docker compose restart nginx"

echo "==> Waiting for web to start..."
sleep 8

echo "==> Applying migrations..."
$SSH "cd ~/cloudpebble && docker compose exec -T web /usr/local/bin/python /code/manage.py migrate --noinput" || true

echo "==> Container status:"
$SSH "cd ~/cloudpebble && docker compose --profile emulator --profile codecomplete ps"

echo ""
echo "==> Web logs (last 15 lines):"
$SSH "cd ~/cloudpebble && docker compose logs web --tail 15"

echo ""
echo "==> Deploy complete: https://$DEV_HOST/"
