#!/usr/bin/env python3
"""Live API test for the CloudPebble agent chat routes.

Runs against a real deployed instance over HTTPS, exactly like a browser would --
no Django test client, no fixtures, nothing mocked. Everything it asserts is
observable from outside the box.

    CP_PASSWORD=... python3 tests/agent_api_test.py
    CP_PASSWORD=... python3 tests/agent_api_test.py --base-url https://cloudpebble-dev.exe.xyz --project-id 6

Credentials come from CP_USERNAME / CP_PASSWORD (or --username / --password).
No working password ships in this repo.

What it covers:
  1. login, and the project is reachable with the session cookie
  2. agent/start, agent/message, agent/stream, agent/cancel
  3. every SSE event that comes down the stream matches the envelope contract
     (AGENT_PLAN "SSE event envelope": {seq, role, type, data})
  4. the scoped agent token boundary, from the outside
  5. a build-only turn (no emulator attached) terminates instead of hanging

Exits non-zero if any check fails. One PASS/FAIL/SKIP line per check.

--- On --agent-token ---

Agent tokens are minted server-side per turn and never leave Django, so the
strongest form of check 4 needs one handed in. Grab a live one off the dev box
while a turn is running (they have a 30 minute TTL and are revoked when the turn
ends), then pass it with --agent-token:

    ssh cloudpebble-dev.exe.xyz \\
      "docker compose exec -T redis redis-cli --scan --pattern 'agent-token-*'"
    # -> agent-token-<secret>; the part after the prefix is the token

The token must be scoped to --project-id. Without it the boundary checks still
run using a forged token (a well-formed secret that was never minted), which
proves the routes reject unknown tokens but not that scoping works; those checks
report SKIP so nobody mistakes one for the other.
"""

import argparse
import json
import os
import secrets
import sys
import threading
import time

import requests

DEFAULT_BASE = 'https://cloudpebble-dev.exe.xyz'
DEFAULT_USER = os.environ.get('CP_USERNAME', 'testuser')
# No working password in the repo, by design. Supply it out of band:
#   CP_PASSWORD=... python3 tests/agent_api_test.py
# or --password. Empty means main() bails with a clear message rather than
# letting a copy-paste run fail confusingly at login.
DEFAULT_PASSWORD = os.environ.get('CP_PASSWORD', '')
HTTP_TIMEOUT = 30

# The SSE envelope contract: type -> keys that must be present in `data`.
# Extra keys are fine (the relay carries sdk_session_id along on some events).
REQUIRED_DATA_KEYS = {
    'text': ('text',),
    'tool_use': ('tool', 'args'),
    'tool_result': ('tool', 'ok', 'summary'),
    'file_edit': ('path', 'file_id', 'diff'),
    'project_changed': ('what',),
    # Sent once per stream, after the replay: the server's own view of whether a
    # turn is running. Never persisted, so it carries no seq.
    'sync': ('status',),
    'build': ('build_id', 'state', 'log_url'),
    'error': ('message', 'kind'),
    'done': ('turn_count',),
}
# The envelope contract lists assistant|tool|system; 'user' is here too because
# Django echoes the submitted message back down the stream as a user event.
ROLES = {'user', 'assistant', 'tool', 'system'}
# Error kinds that end a turn, per ide/api/agent.py:FATAL_ERROR_KINDS.
FATAL_ERROR_KINDS = {'relay', 'timeout', 'cancelled', 'usage_limit', 'auth'}

RESULTS = []


# ---------------------------------------------------------------------------
# reporting


def _record(status, name, detail=''):
    RESULTS.append((status, name, detail))
    print('%-4s %s%s' % (status, name, ' -- %s' % detail if detail else ''), flush=True)


def check(name, ok, detail=''):
    _record('PASS' if ok else 'FAIL', name, detail)
    return bool(ok)


def skip(name, why):
    _record('SKIP', name, why)


def failures():
    return [r for r in RESULTS if r[0] == 'FAIL']


# ---------------------------------------------------------------------------
# http helpers


def csrf(session):
    return session.cookies.get('csrftoken')


def post(session, base_url, path, data=None, **kwargs):
    kwargs.setdefault('timeout', HTTP_TIMEOUT)
    kwargs.setdefault('allow_redirects', False)
    # '' rather than None for the cookie-less sessions used in the rejection checks:
    # requests refuses to send a None header value.
    return session.post('%s%s' % (base_url, path), data=data or {},
                        headers={'X-CSRFToken': csrf(session) or '',
                                 'Referer': '%s/' % base_url},
                        **kwargs)


def get(session, base_url, path, **kwargs):
    kwargs.setdefault('timeout', HTTP_TIMEOUT)
    kwargs.setdefault('allow_redirects', False)
    return session.get('%s%s' % (base_url, path), **kwargs)


def body(response):
    """Parsed JSON, or {} for the HTML error pages Django serves on 403/500."""
    try:
        return response.json()
    except ValueError:
        return {}


def describe(response):
    return 'HTTP %s %s' % (response.status_code, response.text[:160].replace('\n', ' '))


def login(session, base_url, username, password):
    session.get('%s/' % base_url, timeout=HTTP_TIMEOUT)
    resp = post(session, base_url, '/accounts/api/login',
                {'username': username, 'password': password})
    return body(resp).get('success') is True, resp


# ---------------------------------------------------------------------------
# SSE


def envelope_problems(event):
    """Contract violations in one SSE event. Empty list means it's well-formed."""
    if not isinstance(event, dict):
        return ['event is not an object']
    problems = []
    if not isinstance(event.get('seq'), int) or isinstance(event.get('seq'), bool):
        problems.append('seq is %r, want int' % (event.get('seq'),))
    if event.get('role') not in ROLES:
        problems.append('role is %r, want one of %s' % (event.get('role'), sorted(ROLES)))
    data = event.get('data')
    if not isinstance(data, dict):
        problems.append('data is %r, want object' % (data,))
        data = {}
    type_ = event.get('type')
    if type_ not in REQUIRED_DATA_KEYS:
        problems.append('type is %r, not in the contract' % (type_,))
    else:
        missing = [k for k in REQUIRED_DATA_KEYS[type_] if k not in data]
        if missing:
            problems.append('type %s is missing data.%s' % (type_, ', data.'.join(missing)))
    return problems


class Stream(object):
    """Reads project/<id>/agent/stream in a background thread.

    The stream is deliberately long-lived server-side (it stays open across turns
    and heartbeats every 15s), so it is never waited on to end -- only for
    particular events to show up.
    """

    def __init__(self, session, base_url, project_id, since=0):
        self.events = []
        self.problems = []
        self.error = None
        self._lock = threading.Lock()
        self._response = session.get(
            '%s/ide/project/%s/agent/stream' % (base_url, project_id),
            params={'since': since}, stream=True, timeout=(10, 60))
        self._response.raise_for_status()
        self._thread = threading.Thread(target=self._read, name='agent-sse', daemon=True)
        self._thread.start()

    def _read(self):
        try:
            for line in self._response.iter_lines(decode_unicode=True):
                if not line or not line.startswith('data:'):
                    continue  # blank separator or ': keepalive'
                payload = line[len('data:'):].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except ValueError:
                    with self._lock:
                        self.problems.append('unparseable payload: %r' % payload[:120])
                    continue
                problems = envelope_problems(event)
                with self._lock:
                    self.events.append(event)
                    self.problems += ['seq=%s: %s' % (event.get('seq'), p) for p in problems]
        except Exception as e:  # connection reset, read timeout, close()
            self.error = e

    def snapshot(self):
        with self._lock:
            return list(self.events), list(self.problems)

    def wait_for(self, predicate, timeout):
        """First event satisfying predicate, or None if the deadline passes."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for event in self.snapshot()[0]:
                if predicate(event):
                    return event
            if self.error is not None:
                return None
            time.sleep(0.5)
        return None

    def close(self):
        try:
            self._response.close()
        except Exception:
            pass


def is_terminal(event):
    return (event.get('type') == 'done'
            or (event.get('type') == 'error'
                and (event.get('data') or {}).get('kind') in FATAL_ERROR_KINDS))


# ---------------------------------------------------------------------------
# the checks


def check_token_boundary(base_url, project_id, other_project_id, token, real):
    """The security test: what a scoped agent token may and may not reach.

    Every request here uses a cookie-less session, so the only credential in play
    is the bearer token.
    """
    label = 'real token' if real else 'forged token'
    bearer = requests.Session()
    bearer.headers['Authorization'] = 'Bearer %s' % token

    covered = '/ide/project/%s/info' % project_id
    cross = '/ide/project/%s/info' % other_project_id
    uncovered_get = '/ide/project/%s/build/history' % project_id
    uncovered_post = '/ide/project/%s/save_settings' % project_id  # save_project_settings

    # A real token must work on a covered route, or the negatives below prove nothing.
    resp = get(bearer, base_url, covered)
    if real:
        check('agent token reaches its own project (%s)' % covered,
              resp.status_code == 200 and body(resp).get('success') is True, describe(resp))
    else:
        check('unminted token rejected on %s' % covered,
              resp.status_code != 200, describe(resp))

    # Scoped to one project: same user, different project, must still be refused.
    resp = get(bearer, base_url, cross)
    rejected = resp.status_code in (401, 403)
    if real:
        check('agent token refused on a project it does not cover (%s)' % cross,
              rejected, describe(resp))
    else:
        skip('agent token refused on a project it does not cover',
             'needs --agent-token; unminted token got %s' % describe(resp))
        check('unminted token rejected on %s' % cross, resp.status_code != 200, describe(resp))

    # Accepted by a hand-picked handful of views only. These two are not on the list.
    # The GET is the load-bearing one: no CSRF is involved, so a rejection can only
    # come from the token not being accepted there. The POST would also be stopped by
    # CSRF, which is a second lock on the same door rather than proof of the first.
    resp = get(bearer, base_url, uncovered_get)
    check('agent token refused on an uncovered route (%s)%s'
          % (uncovered_get, '' if real else ' [%s]' % label),
          resp.status_code != 200, describe(resp))

    resp = post(bearer, base_url, uncovered_post, {
        'name': 'pwned', 'app_uuid': '00000000-0000-0000-0000-000000000000',
        'app_company_name': 'x', 'app_short_name': 'x', 'app_long_name': 'x',
        'app_version_label': '1.0', 'app_is_watchface': '1', 'app_is_hidden': '0',
        'app_is_shown_on_communication': '0', 'app_capabilities': '',
        'app_keys': '{}', 'app_platforms': '',
    })
    check('agent token refused on save_project_settings (%s)%s'
          % (uncovered_post, '' if real else ' [%s]' % label),
          resp.status_code != 200, describe(resp))


def self_test():
    """The validator is the only real logic here, so it gets to be checked offline."""
    good = {'seq': 3, 'role': 'tool', 'type': 'tool_result',
            'data': {'tool': 'build', 'ok': True, 'summary': 'ok', 'extra': 1}}
    assert envelope_problems(good) == [], envelope_problems(good)
    assert envelope_problems({'seq': 1, 'role': 'assistant', 'type': 'text',
                              'data': {'text': 'hi'}}) == []
    assert envelope_problems({'seq': '1', 'role': 'assistant', 'type': 'text',
                              'data': {'text': 'hi'}})  # seq must be an int
    assert envelope_problems({'seq': True, 'role': 'assistant', 'type': 'text',
                              'data': {'text': 'hi'}})  # bools are not seqs
    assert envelope_problems({'seq': 1, 'role': 'wizard', 'type': 'text',
                              'data': {'text': 'hi'}})
    assert envelope_problems({'seq': 1, 'role': 'system', 'type': 'vibes', 'data': {}})
    assert envelope_problems({'seq': 1, 'role': 'assistant', 'type': 'build',
                              'data': {'build_id': 7}})  # missing state, log_url
    assert envelope_problems({'seq': 1, 'role': 'assistant', 'type': 'text', 'data': 'hi'})
    assert is_terminal({'type': 'done', 'data': {'turn_count': 1}})
    assert is_terminal({'type': 'error', 'data': {'kind': 'relay', 'message': 'x'}})
    assert not is_terminal({'type': 'error', 'data': {'kind': 'mirror_error', 'message': 'x'}})
    assert not is_terminal({'type': 'text', 'data': {'text': 'x'}})
    print('self-test OK')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--project-id', default='6', help='project the agent works on')
    parser.add_argument('--other-project-id', default='7',
                        help='another project the same user owns, for the scoping check')
    parser.add_argument('--username', default=DEFAULT_USER)
    parser.add_argument('--password', default=DEFAULT_PASSWORD)
    parser.add_argument('--agent-token', default=None,
                        help='a live agent token scoped to --project-id (see module docstring)')
    parser.add_argument('--turn-timeout', type=float, default=300,
                        help='how long a build-only turn may take before it counts as hung')
    parser.add_argument('--message', default='Build the project and tell me whether it '
                                             'compiles. Do not change any files.')
    parser.add_argument('--self-test', action='store_true',
                        help='check the envelope validator offline and exit')
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if not args.password:
        print('error: no password. Set CP_PASSWORD in the environment or pass '
              '--password. There is deliberately no working credential in this repo.',
              file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip('/')
    pid = args.project_id
    session = requests.Session()

    ok, resp = login(session, base_url, args.username, args.password)
    if not check('login as %s' % args.username, ok, describe(resp)):
        return summarize()

    resp = get(session, base_url, '/ide/project/%s/info' % pid)
    if not check('project %s reachable with the session cookie' % pid,
                 resp.status_code == 200, describe(resp)):
        return summarize()

    # The scoping check is only meaningful if the other project exists and is ours.
    resp = get(session, base_url, '/ide/project/%s/info' % args.other_project_id)
    other_ok = check('project %s reachable with the session cookie (scoping control)'
                     % args.other_project_id, resp.status_code == 200, describe(resp))

    # --- agent/start ---
    resp = post(session, base_url, '/ide/project/%s/agent/start' % pid)
    data = body(resp)
    if resp.status_code == 403:
        check('agent/start', False,
              'forbidden -- is this user in AGENT_ENABLED_USERS? %s' % describe(resp))
        return summarize()
    started = check('agent/start returns a session_id',
                    resp.status_code == 200 and isinstance(data.get('session_id'), int),
                    describe(resp))
    session_id = data.get('session_id')

    # --- input rejections ---
    # agent/message fails closed with a 500 when AGENT_URL/AGENT_AUTH_HEADER are unset,
    # before it ever looks at the body -- so say that plainly instead of failing on a 400.
    def reject_check(name, resp):
        if resp.status_code == 500:
            skip(name, 'agent service not configured on this instance (%s)' % describe(resp))
        else:
            check(name, resp.status_code == 400, describe(resp))

    reject_check('agent/message rejects an empty message',
                 post(session, base_url, '/ide/project/%s/agent/message' % pid,
                      {'message': '  '}))
    reject_check('agent/message rejects a malformed emulator param',
                 post(session, base_url, '/ide/project/%s/agent/message' % pid,
                      {'message': 'hi', 'emulator': 'not json'}))

    anon = requests.Session()
    resp = post(anon, base_url, '/ide/project/%s/agent/start' % pid)
    check('agent/start rejects an unauthenticated caller',
          resp.status_code != 200, describe(resp))

    if not started:
        return summarize()

    # --- a build-only turn: no emulator param at all ---
    turn_started = time.time()
    resp = post(session, base_url, '/ide/project/%s/agent/message' % pid,
                {'message': args.message, 'session_id': session_id})
    accepted = check('agent/message accepts a build-only turn (no emulator)',
                     resp.status_code == 200 and body(resp).get('ok') is True, describe(resp))

    stream = None
    try:
        # Opened after the POST, so the catch-up rows flush headers immediately;
        # since=0 replays the whole session, so nothing is missed by starting late.
        stream = Stream(session, base_url, pid, since=0)
        check('agent/stream connects', True, 'text/event-stream')
    except Exception as e:
        check('agent/stream connects', False, repr(e))

    if stream is not None and not accepted:
        # No turn to watch, but cancel and the envelope checks below still mean
        # something -- run them against whatever the session already has.
        skip('the user message is replayed on the stream', 'the turn was not accepted')
        skip('the turn terminates rather than hanging', 'the turn was not accepted')
        skip('the build-only turn completes cleanly', 'the turn was not accepted')

    if stream is not None and accepted:
        echo = stream.wait_for(
            lambda e: e.get('role') == 'user' and e.get('type') == 'text'
            and (e.get('data') or {}).get('text') == args.message, timeout=30)
        check('the user message is replayed on the stream', echo is not None)

        terminal = stream.wait_for(is_terminal, timeout=args.turn_timeout)
        elapsed = time.time() - turn_started
        check('the turn terminates rather than hanging',
              terminal is not None,
              'no done/fatal-error event in %.0fs' % elapsed if terminal is None
              else 'after %.0fs' % elapsed)

        if terminal is not None:
            kind = (terminal.get('data') or {}).get('kind')
            check('the build-only turn completes cleanly',
                  terminal.get('type') == 'done',
                  'ended with error kind=%r: %s' % (kind, (terminal.get('data') or {}).get('message'))
                  if terminal.get('type') == 'error' else 'type=done')

        events, _ = stream.snapshot()
        builds = [e for e in events if e.get('type') == 'build']
        if builds:
            states = sorted({str((e.get('data') or {}).get('state')) for e in builds})
            check('a build event was emitted', True, 'states seen: %s' % ', '.join(states))
        else:
            skip('a build event was emitted', 'the agent did not run a build this turn')

        screenshots = [e for e in events if e.get('type') == 'tool_result'
                       and (e.get('data') or {}).get('tool') in ('screenshot', 'install')]
        if screenshots:
            check('emulator tools report failure instead of hanging, with no emulator',
                  all((e.get('data') or {}).get('ok') is False for e in screenshots),
                  '%d emulator tool results' % len(screenshots))

    if stream is not None:
        # --- agent/cancel, checked through the same open stream ---
        resp = post(session, base_url, '/ide/project/%s/agent/cancel' % pid,
                    {'session_id': session_id})
        check('agent/cancel returns ok',
              resp.status_code == 200 and body(resp).get('ok') is True, describe(resp))
        cancelled = stream.wait_for(
            lambda e: e.get('type') == 'error' and (e.get('data') or {}).get('kind') == 'cancelled',
            timeout=30)
        check('agent/cancel emits a cancelled event on the stream', cancelled is not None)

        events, problems = stream.snapshot()
        check('every SSE event matches the envelope contract (%d events)' % len(events),
              not problems, '; '.join(problems[:5]))
        seqs = [e.get('seq') for e in events if isinstance(e.get('seq'), int)]
        check('SSE seq is strictly increasing',
              seqs == sorted(set(seqs)) and len(seqs) == len(events),
              'seqs: %s' % seqs[:20])
        types = sorted({str(e.get('type')) for e in events})
        _record('INFO', 'event types seen', ', '.join(types) or 'none')

        # ?since= must not replay what the caller already has.
        if seqs:
            resume = None
            try:
                resume = Stream(session, base_url, pid, since=max(seqs))
                time.sleep(2)
                replayed, _ = resume.snapshot()
                check('agent/stream?since=N skips events already delivered',
                      all(e.get('seq') > max(seqs) for e in replayed),
                      '%d events after seq %s' % (len(replayed), max(seqs)))
            except Exception as e:
                check('agent/stream?since=N skips events already delivered', False, repr(e))
            finally:
                if resume is not None:
                    resume.close()

    if stream is not None:
        stream.close()

    # --- the security boundary ---
    if not other_ok:
        skip('scoped token boundary', 'control project %s is not reachable' % args.other_project_id)
    else:
        token = args.agent_token or secrets.token_urlsafe(32)
        check_token_boundary(base_url, pid, args.other_project_id, token,
                             real=bool(args.agent_token))

    return summarize()


def summarize():
    counts = {}
    for status, _name, _detail in RESULTS:
        counts[status] = counts.get(status, 0) + 1
    print('\n%s' % ('-' * 60))
    print('%d passed, %d failed, %d skipped'
          % (counts.get('PASS', 0), counts.get('FAIL', 0), counts.get('SKIP', 0)))
    for _status, name, detail in failures():
        print('  FAIL %s%s' % (name, ' -- %s' % detail if detail else ''))
    return 1 if failures() else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
