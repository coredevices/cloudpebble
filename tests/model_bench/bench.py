"""Run one model through a fixed watchface brief and record what it produced.

Every model gets the identical prompt, the identical follow-up, a fresh project
and a fresh emulator, so results are comparable across runs. Screenshots and the
token usage the SDK reports are written to results/<label>/.

    ./switch.sh kimi                       # point the agent VM at a model
    CP_PASSWORD=... AGENT_LABEL=kimi \
      python3 bench.py                     # run the bench against it
    python3 compare.py                     # table across all recorded runs

Notes earned the hard way, all of which this harness handles:
  * The stream replays a session from ?since=, so a new turn's events are
    indistinguishable from the last one unless you record the seq first.
  * The qemu controller reaps an emulator after 300s with no ping, and a turn
    here runs far longer, so it needs a keepalive.
  * Swapping the emulator mid-session is worse than losing it: the agent
    screenshots a watch it never installed to and has no way to know.
  * A long-lived SSE connection gets cut well before a turn ends; reconnect
    from the last seq, the way agent.js's EventSource does.
"""
import base64
import json
import threading
import os
import pathlib
import sys
import time

import requests

BASE = 'https://cloudpebble-dev.exe.xyz'
USER = os.environ.get('CP_USERNAME', 'testuser')
PW = os.environ['CP_PASSWORD']
LABEL = os.environ.get('AGENT_LABEL', 'run')
# Every run gets its own directory. Runs are the expensive part of this exercise
# -- 20+ minutes and real money each -- so nothing here ever overwrites or
# deletes a previous one. RUN_ID can be set to reproduce a path deliberately.
RUN_ID = os.environ.get('AGENT_RUN_ID') or time.strftime('%Y%m%d-%H%M%S')
OUT = pathlib.Path(__file__).parent / 'results' / ('%s-%s' % (LABEL, RUN_ID))

BRIEF = (
    "Build an ambitious outer-space watchface. I want it to feel rich and alive: a "
    "starfield, at least one planet, a moon, a spaceship and an asteroid field, with "
    "the time shown clearly and legibly on top. Animate it: every minute the scene "
    "should visibly change (things drift, rotate or move) so it never looks static. "
    "Use the full display, keep it battery-sane (no per-second redraws), and make sure "
    "nothing is clipped at the edges. Build it, install it, screenshot it, and study "
    "the screenshot before telling me it is done."
)

FOLLOWUPS = [
    "Look hard at that screenshot. The scene should feel dense and deliberate, not a "
    "few dots on black. Improve the composition: better use of the whole screen, more "
    "visual depth, and make sure the time is readable against the artwork. Confirm the "
    "scene really does advance every minute. Rebuild, reinstall, screenshot, and give "
    "me an honest critique of the final image.",
]


def login():
    s = requests.Session()
    s.get(BASE + '/', timeout=30)
    r = s.post(BASE + '/accounts/api/login', data={'username': USER, 'password': PW},
               headers={'X-CSRFToken': s.cookies.get('csrftoken'), 'Referer': BASE + '/'},
               timeout=30)
    r.raise_for_status()
    assert r.json().get('success'), r.text
    return s


def post(s, path, data):
    return s.post(BASE + path, data=data,
                  headers={'X-CSRFToken': s.cookies.get('csrftoken'), 'Referer': BASE + '/'},
                  timeout=180)


def create_project(s, name):
    r = post(s, '/ide/project/create', {'name': name, 'type': 'native', 'template': '0'})
    r.raise_for_status()
    return r.json()['id']


def launch_emulator(platform='basalt'):
    token = 'cmp%d' % time.time()
    r = requests.post(BASE + '/qemu/launch',
                      data={'token': token, 'platform': platform, 'version': '3.0',
                            'tz_offset': '0'},
                      headers={'Authorization': 'secret'}, timeout=120)
    r.raise_for_status()
    time.sleep(12)   # /launch returns before pypkjs is listening
    return {'uuid': r.json()['uuid'], 'token': token}


def keepalive(emu, stop):
    """The controller reaps an emulator after 300s without a ping, and a turn
    here runs far longer than that. Nothing in the IDE pings either, so this is
    the same gap real users hit during a long turn."""
    while not stop.wait(60):
        try:
            requests.post('%s/qemu/%s/ping' % (BASE, emu['uuid']), timeout=15)
        except requests.exceptions.RequestException:
            pass


def drain_history(s, pid, settle=3.0):
    """Last seq already on the stream, so a new turn's events are separable."""
    last = 0
    deadline = time.time() + settle
    try:
        with s.get('%s/ide/project/%s/agent/stream?since=0' % (BASE, pid),
                   stream=True, timeout=(10, settle)) as r:
            for raw in r.iter_lines(decode_unicode=True):
                if time.time() > deadline:
                    break
                if raw and raw.startswith('data:'):
                    try:
                        last = max(last, json.loads(raw[5:].strip()).get('seq', 0))
                    except ValueError:
                        pass
    except requests.exceptions.RequestException:
        pass
    return last


def run_turn(s, pid, emu, message, since, shots, turn_no, max_reconnects=8):
    """Send one message and follow the stream to its terminal event.

    A turn runs for many minutes and the long-lived SSE connection gets cut by
    the proxy well before that, so reconnect from the last seq seen -- the same
    thing agent.js's EventSource does with ?since=.
    """
    post(s, '/ide/project/%s/agent/message' % pid,
         {'message': message, 'emulator': json.dumps(emu)}).raise_for_status()

    tools, usage, t0, last_seq = [], {}, time.time(), since
    reconnects = 0
    while True:
        try:
            with s.get('%s/ide/project/%s/agent/stream?since=%s' % (BASE, pid, last_seq),
                       stream=True, timeout=(30, 600)) as r:
                r.raise_for_status()
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw or not raw.startswith('data:'):
                        continue
                    try:
                        evt = json.loads(raw[5:].strip())
                    except ValueError:
                        continue
                    last_seq = max(last_seq, evt.get('seq', 0))
                    t, d = evt.get('type'), evt.get('data', {})
                    el = int(time.time() - t0)
                    if t == 'tool_use':
                        tools.append(d.get('tool'))
                        print('  [%3ds] -> %s' % (el, d.get('tool')), flush=True)
                    elif t == 'tool_result':
                        if d.get('image_png_b64'):
                            shots[0] += 1
                            p = OUT / ('t%d-shot%02d.png' % (turn_no, shots[0]))
                            # Recreate on every write: losing a screenshot to a
                            # missing directory wastes the whole run.
                            p.parent.mkdir(parents=True, exist_ok=True)
                            p.write_bytes(base64.b64decode(d['image_png_b64']))
                            print('  [%3ds] <- screenshot -> %s' % (el, p.name), flush=True)
                    elif t == 'build':
                        print('  [%3ds] BUILD %s (%s)' % (el, d.get('state'), d.get('build_id')), flush=True)
                    elif t == 'text' and evt.get('role') == 'assistant':
                        print('  [%3ds] %s' % (el, (d.get('text') or '')[:300].replace('\n', ' ')), flush=True)
                    elif t == 'error':
                        print('  [%3ds] ERROR %s: %s' % (el, d.get('kind'), d.get('message')), flush=True)
                        if d.get('kind') in ('relay', 'timeout', 'cancelled', 'usage_limit'):
                            return last_seq, tools, usage, False
                    elif t == 'done':
                        usage = d.get('usage') or {}
                        print('  [%3ds] DONE turns=%s' % (el, d.get('turn_count')), flush=True)
                        return last_seq, tools, usage, True
        except requests.exceptions.RequestException as e:
            reconnects += 1
            if reconnects > max_reconnects:
                print('  stream lost for good after %d reconnects: %s' % (reconnects, e), flush=True)
                return last_seq, tools, usage, False
            print('  [stream dropped, reconnecting from seq %s]' % last_seq, flush=True)
            time.sleep(2)
            continue
        # Clean EOF without a terminal event: reconnect and keep following.
        reconnects += 1
        if reconnects > max_reconnects:
            return last_seq, tools, usage, False
        time.sleep(2)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = login()
    pid = create_project(s, 'space-%s-%d' % (LABEL, time.time()))
    print('=== %s === project %s -> %s/ide/project/%s' % (LABEL, pid, BASE, pid))
    emu = launch_emulator()
    print('emulator', emu['uuid'])
    post(s, '/ide/project/%s/agent/start' % pid, {}).raise_for_status()

    stop = threading.Event()
    threading.Thread(target=keepalive, args=(emu, stop), daemon=True).start()

    since = drain_history(s, pid)
    shots = [0]
    totals = {'input_tokens': 0, 'output_tokens': 0, 'cache_read_input_tokens': 0,
              'cache_creation_input_tokens': 0, 'total_cost_usd': 0.0}
    report = []

    for i, msg in enumerate([BRIEF] + FOLLOWUPS, start=1):
        print('\n--- turn %d ---' % i, flush=True)
        t0 = time.time()
        since, tools, usage, ok = run_turn(s, pid, emu, msg, since, shots, i)
        for k in totals:
            v = usage.get(k)
            if isinstance(v, (int, float)):
                totals[k] += v
        report.append({'turn': i, 'ok': ok, 'seconds': round(time.time() - t0),
                       'tools': tools, 'usage': usage})
        if not ok:
            print('turn %d did not complete cleanly' % i)

    stop.set()
    summary = {'label': LABEL, 'run_id': RUN_ID, 'project_id': pid,
               'started': time.strftime('%Y-%m-%d %H:%M:%S'),
               'screenshots': shots[0], 'turns': report, 'totals': totals}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
    print('\n=== %s totals ===' % LABEL)
    print(json.dumps(totals, indent=2))
    print('screenshots:', shots[0], '->', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
