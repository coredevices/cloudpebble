#!/bin/bash
# Run the chat-panel e2e in the official Playwright image.
#
# This host cannot launch Chromium (AppArmor blocks unprivileged userns), so the
# browser always runs in docker. Works on cloudpebble-loop-dev (docker 29) and
# anywhere else docker exists.
#
#   CP_USERNAME=testuser CP_PASSWORD=... ./run.sh
#   CP_PROJECT_ID=23 ./run.sh
#
# Credentials come from the environment or from a .env file next to this script
# (gitignored). Never hardcode them here.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck disable=SC1091
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env"; set +a; }

: "${CP_BASE_URL:=https://cloudpebble-dev.exe.xyz}"
: "${CP_PROJECT_ID:=6}"
: "${PLAYWRIGHT_IMAGE:=mcr.microsoft.com/playwright/python:v1.49.0-jammy}"

if [ -z "${CP_USERNAME:-}" ] || [ -z "${CP_PASSWORD:-}" ]; then
    echo "error: set CP_USERNAME and CP_PASSWORD (env or $HERE/.env)" >&2
    exit 2
fi

# Created here, not in the container, so the artifacts are not root-owned.
mkdir -p "$HERE/artifacts"

# Empty values are passed through and treated as unset by e2e_agent.py.
exec docker run --rm --init \
    --shm-size=1g \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -e "CP_BASE_URL=$CP_BASE_URL" \
    -e "CP_USERNAME=$CP_USERNAME" \
    -e "CP_PASSWORD=$CP_PASSWORD" \
    -e "CP_PROJECT_ID=$CP_PROJECT_ID" \
    -e "CP_PROMPT=${CP_PROMPT:-}" \
    -e "CP_UI_TIMEOUT_MS=${CP_UI_TIMEOUT_MS:-}" \
    -e "CP_TURN_TIMEOUT_MS=${CP_TURN_TIMEOUT_MS:-}" \
    -e CP_ARTIFACTS=/work/artifacts \
    -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    -e PYTHONPATH=/tmp/pw/lib/python3.10/site-packages \
    -v "$HERE:/work" \
    -w /work \
    "$PLAYWRIGHT_IMAGE" \
    sh -c '
      # The python variant of this image ships the BROWSERS at /ms-playwright but
      # not the playwright pip package, so install it into a writable prefix.
      # Version must match the image tag or it will look for browsers it lacks.
      python -c "import playwright" 2>/dev/null \
        || pip install --quiet --target=/tmp/pw/lib/python3.10/site-packages playwright=='"${PLAYWRIGHT_PIP_VERSION:-1.49.0}"' >&2
      exec python e2e_agent.py "$@"
    ' -- "$@"
