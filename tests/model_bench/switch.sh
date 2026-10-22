#!/bin/bash
# Point the agent VM at one of the model configurations in models.json.
#
#   MOONSHOT_API_KEY=... ./switch.sh kimi
#   ./switch.sh claude
#   DEEPSEEK_API_KEY=... OPENROUTER_API_KEY=... ./switch.sh deepseek
#
# Keys come from the environment, never from this repo. The vision describer is
# configured for every mode but only consulted when the main model has no vision
# of its own (see cloudpebble-agent/vision.py).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${AGENT_HOST:-cloudpebble-loop-dev.exe.xyz}"
MODE="${1:?usage: switch.sh <model-name>   (see models.json)}"

ENV_BLOCK=$(python3 - "$HERE/models.json" "$MODE" <<'PY'
import json, os, sys
cfg = json.load(open(sys.argv[1]))
name = sys.argv[2]
models = cfg['models']
if name not in models:
    sys.exit("unknown model %r. Known: %s" % (name, ', '.join(sorted(models))))

def key_for(entry, what):
    env = entry.get('key_env')
    if not env:
        return ''
    val = os.environ.get(env, '')
    if not val:
        sys.exit("%s needs %s in the environment" % (what, env))
    return val

m = models[name]
v = cfg['vision_describer']
lines = [
    'AGENT_MODEL=%s' % m['model'],
    'AGENT_API_BASE=%s' % m.get('api_base', ''),
    'AGENT_API_KEY=%s' % key_for(m, name),
    'AGENT_MODEL_VISION=%s' % ('1' if m.get('vision', True) else '0'),
    'AGENT_VISION_API_BASE=%s' % v['api_base'],
    'AGENT_VISION_API_KEY=%s' % key_for(v, 'vision describer'),
    'AGENT_VISION_MODEL=%s' % v['model'],
]
print('\n'.join(lines))
PY
)

ssh -o BatchMode=yes "$HOST" "
python3 - <<'EOF'
drop = ('AGENT_MODEL=','AGENT_API_BASE=','AGENT_API_KEY=','AGENT_MODEL_VISION=',
        'AGENT_VISION_API_BASE=','AGENT_VISION_API_KEY=','AGENT_VISION_MODEL=')
keep = [l for l in open('/home/exedev/.agent-env').read().splitlines()
        if not l.startswith(drop)]
open('/home/exedev/.agent-env','w').write('\n'.join(keep + '''$ENV_BLOCK'''.splitlines()) + '\n')
EOF
chmod 600 ~/.agent-env
cd ~/cloudpebble-agent
# Rebuild, don't just recreate: --force-recreate alone reuses the existing
# image, so agent code changes silently never ship. Cost is a few seconds when
# nothing changed.
docker compose build -q >/dev/null 2>&1
docker compose up -d --force-recreate >/dev/null 2>&1
sleep 6
curl -s --max-time 10 http://127.0.0.1:8000/health
docker compose exec -T agent sh -c 'echo \" model=\$AGENT_MODEL base=[\$AGENT_API_BASE] vision=\$AGENT_MODEL_VISION describer=\$AGENT_VISION_MODEL\"'
"
