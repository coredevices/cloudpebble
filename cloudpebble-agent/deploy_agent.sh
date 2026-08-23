#!/bin/bash
set -euo pipefail

# Agent loop deployment script
# Syncs cloudpebble-agent/ to the loop VM and restarts the service.
# The Claude OAuth token lives only in ~/.agent-env on the target — never in the image.
#
# Usage: ./deploy_agent.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env from the repo root (same file deploy_qemu.sh reads)
if [ -f "$SCRIPT_DIR/../.env" ]; then
  set -a
  source "$SCRIPT_DIR/../.env"
  set +a
fi

AGENT_HOST="${AGENT_HOST:-cloudpebble-loop-dev.exe.xyz}"
SSH_KEY="${AGENT_SSH_KEY:-${SSH_KEY:-$HOME/.ssh/id_exe}}"
SSH="ssh -i $SSH_KEY $AGENT_HOST"

echo "==> Checking ~/.agent-env on $AGENT_HOST..."
$SSH 'test -f ~/.agent-env || { echo "MISSING ~/.agent-env — see README (claude setup-token)"; exit 1; }
      grep -q CLAUDE_CODE_OAUTH_TOKEN ~/.agent-env || { echo "~/.agent-env has no CLAUDE_CODE_OAUTH_TOKEN"; exit 1; }
      grep -q AGENT_AUTH_HEADER ~/.agent-env || {
        echo "~/.agent-env has no AGENT_AUTH_HEADER — the service will refuse every request.";
        echo "Generate one with: openssl rand -hex 32";
        echo "and set the same value as AGENT_AUTH_HEADER in CloudPebble'"'"'s .env.";
        exit 1; }'

echo "==> Syncing code to $AGENT_HOST..."
rsync -avz --delete \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='.DS_Store' \
  -e "ssh -i $SSH_KEY" \
  "$SCRIPT_DIR/" "$AGENT_HOST":~/cloudpebble-agent/

echo "==> Building and restarting agent service..."
$SSH "cd ~/cloudpebble-agent && docker compose build && docker compose up -d"

echo "==> Container status:"
$SSH "cd ~/cloudpebble-agent && docker compose ps"

echo ""
echo "==> Health check:"
$SSH "curl -fsS --max-time 10 http://127.0.0.1:8300/health" || echo "(not healthy yet — docker compose logs -f agent)"
echo ""
