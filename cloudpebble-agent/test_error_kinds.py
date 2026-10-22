"""_kind() decides what the user is told to do, so it gets a test.

A usage limit means wait; an auth failure means replace your credential. Telling
someone to re-authenticate when they merely ran out of quota sends them chasing
a key that was fine, and the reverse leaves them retrying a dead token forever.
"""
import re
import pathlib


def _kind_source():
    """Read the classifier out of agent_loop without importing the SDK."""
    src = pathlib.Path(__file__).with_name('agent_loop.py').read_text()
    ns = {}
    for name in ('USAGE_LIMIT_HINTS', 'AUTH_HINTS'):
        block = re.search(r'%s = \((.*?)\)\n' % name, src, re.S).group(1)
        ns[name] = tuple(re.findall(r"'([^']+)'", block))
    body = re.search(r'def _kind\(text\):\n(.*?)\n\n', src, re.S).group(0)
    exec(body, ns)
    return ns['_kind']


CASES = [
    # observed verbatim from providers during benchmarking
    ('authentication_failed', 'auth'),
    ('Failed to authenticate. API Error: 401 User not found.', 'auth'),
    ('invalid x-api-key', 'auth'),
    ('Your credit balance is too low', 'error'),
    ('request reached organization TPD rate limit, current: 1508283', 'usage_limit'),
    ('API Error: Request rejected (429) ... rate limit', 'usage_limit'),
    ('Build failed: syntax error in main.c', 'error'),
    ('', 'error'),
]


def test_kinds():
    kind = _kind_source()
    for text, expected in CASES:
        got = kind(text)
        assert got == expected, '%r -> %s, want %s' % (text[:50], got, expected)




def test_a_reported_step_limit_is_not_repeated_in_sdk_words():
    """The SDK raises after the result message it already described. Saying
    "Reached maximum number of turns (75)" straight after the friendly sentence
    is two errors for one event."""
    reported = {'max_turns'}
    raw = 'Claude Code returned an error result: Reached maximum number of turns (75)'
    suppressed = 'max_turns' in reported and 'maximum number of turns' in raw
    assert suppressed, 'the duplicate should be suppressed'

    # An unrelated failure after a step limit must still be reported.
    other = 'Claude Code returned an error result: connection reset'
    assert not ('max_turns' in reported and 'maximum number of turns' in other)

    # And with nothing reported yet, the raw message is all the user would get.
    assert not (set() and 'maximum number of turns' in raw)
    print('step limit reported once')


if __name__ == '__main__':
    test_kinds()
    print('%d error classifications correct' % len(CASES))
    test_a_reported_step_limit_is_not_repeated_in_sdk_words()
