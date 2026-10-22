#!/usr/bin/env python3
"""Browser e2e for the CloudPebble AI chat panel.

Drives a real Chromium against a running CloudPebble instance: logs in, opens a
native project, asserts the chat column renders, sends a prompt and asserts the
turn streams back assistant text and at least one tool card.

Selectors come from ide/templates/ide/project.html + ide/static/ide/js/agent.js:
    #chat-wrapper #chat-rail #chat-log #chat-input #chat-send #chat-cancel
    #chat-thinking #chat-collapse
    .chat-msg-user .chat-msg-assistant .chat-card-tool .chat-card-result
    .chat-card-file .chat-chip .chat-error

Run it through run.sh — this host cannot launch Chromium (see README.md).
Everything is configured by env var; nothing is hardcoded.
"""

import os
import re
import sys
import pathlib

from playwright.sync_api import sync_playwright, expect, Error as PlaywrightError

def env(name, default=''):
    """run.sh passes unset options through as empty strings — treat those as unset."""
    return os.environ.get(name, '').strip() or default


BASE_URL = env('CP_BASE_URL', 'https://cloudpebble-dev.exe.xyz').rstrip('/')
USERNAME = env('CP_USERNAME')
PASSWORD = env('CP_PASSWORD')
PROJECT_ID = env('CP_PROJECT_ID', '6')
PROMPT = env('CP_PROMPT', 'List the source files in this project, then stop.')

# The IDE is a big jQuery page over a slow-ish dev box; a turn is an LLM round trip.
UI_TIMEOUT_MS = int(env('CP_UI_TIMEOUT_MS', '30000'))
TURN_TIMEOUT_MS = int(env('CP_TURN_TIMEOUT_MS', '180000'))

ARTIFACTS = pathlib.Path(env('CP_ARTIFACTS', 'artifacts'))

TOOL_CARD = '#chat-log .chat-card-tool, #chat-log .chat-card-result'
ERROR_CARD = '#chat-log .chat-error'


class Failure(Exception):
    """An assertion about the product, as opposed to a Playwright timeout."""


def shot(page, name):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / ('%s.png' % name)
    page.screenshot(path=str(path), full_page=False)
    print('    screenshot -> %s' % path)


def step(n, what):
    print('[%s] %s' % (n, what), flush=True)


def wait_for_stream(page, selector, timeout, what):
    """Wait for `selector`, but bail out early if the panel renders an error card.

    Returns the LAST matching locator, not the first: the panel replays the whole
    session on load, so on any run after the first the earliest bubble belongs to
    an old turn. The newest match is the one this turn produced.

    Without the error race a failed turn just burns the full turn timeout and
    reports nothing useful.
    """
    try:
        page.wait_for_selector('%s, %s' % (selector, ERROR_CARD), state='visible', timeout=timeout)
    except PlaywrightError:
        raise Failure(
            'timed out after %ss waiting for %s (%s). The chat log held:\n%s'
            % (timeout // 1000, what, selector, chat_log_text(page))
        )
    errors = page.locator(ERROR_CARD)
    if errors.count() and page.locator(selector).count() == 0:
        raise Failure('the agent panel reported an error while waiting for %s: %s'
                      % (what, errors.last.inner_text().strip()))
    return page.locator(selector).last


def chat_log_text(page):
    try:
        text = page.locator('#chat-log').inner_text().strip()
    except PlaywrightError:
        return '(could not read #chat-log)'
    return text or '(empty)'


def log_in(page):
    # LOGIN_URL is '/#login' (a modal on the landing page); the plain Django form
    # at /accounts/login/ is the stable thing to drive, and it honours ?next=.
    target = '/ide/project/%s' % PROJECT_ID
    page.goto('%s/accounts/login/?next=%s' % (BASE_URL, target), wait_until='domcontentloaded')
    if page.locator('#id_username').count() == 0:
        raise Failure('no login form at %s/accounts/login/ — is CP_BASE_URL right?' % BASE_URL)
    page.fill('#id_username', USERNAME)
    page.fill('#id_password', PASSWORD)
    page.click('form.form-horizontal button[type=submit]')
    # A rejected login re-renders the same page, so check that before waiting on
    # the redirect — otherwise a wrong password reads as a mystery timeout.
    page.wait_for_load_state('domcontentloaded')
    # Only meaningful while still on the login page: the IDE itself ships hidden
    # .alert-error containers, so checking unconditionally fails a good login.
    if '/accounts/login/' in page.url and page.locator('.alert-error').count():
        raise Failure('login rejected: check CP_USERNAME / CP_PASSWORD')
    try:
        page.wait_for_url(re.compile(r'/ide/project/%s\b' % PROJECT_ID), timeout=UI_TIMEOUT_MS)
    except PlaywrightError:
        raise Failure('login did not land on the project page; ended up at %s' % page.url)


def open_chat(page):
    page.wait_for_selector('.project-container', timeout=UI_TIMEOUT_MS)
    if page.locator('#chat-wrapper').count() == 0:
        raise Failure(
            'no #chat-wrapper on project %s. The panel is behind the feature flag: '
            'user %s must be in AGENT_ENABLED_USERS on the server.' % (PROJECT_ID, USERNAME)
        )
    # localStorage['agentChatCollapsed'] persists the collapsed state; a fresh
    # context starts expanded, but do not depend on that.
    if page.locator('body.chat-collapsed').count():
        page.click('#chat-rail')
    expect(page.locator('#chat-input')).to_be_visible(timeout=UI_TIMEOUT_MS)
    expect(page.locator('#chat-send')).to_be_enabled(timeout=UI_TIMEOUT_MS)


def send_prompt(page):
    page.fill('#chat-input', PROMPT)
    page.click('#chat-send')
    # agent.js:set_running(true) fires synchronously on click, before the POST.
    expect(page.locator('#chat-thinking')).to_be_visible(timeout=UI_TIMEOUT_MS)
    expect(page.locator('#chat-input')).to_be_disabled(timeout=UI_TIMEOUT_MS)


def run(page):
    step(1, 'log in as %s and open project %s' % (USERNAME, PROJECT_ID))
    log_in(page)
    shot(page, '01-project-loaded')

    step(2, 'chat column renders')
    open_chat(page)
    shot(page, '02-chat-panel')

    step(3, 'send a prompt')
    send_prompt(page)
    shot(page, '03-prompt-sent')

    step(4, 'the prompt comes back down the SSE stream as a user bubble')
    # agent.js does no local echo: seeing this proves Django persisted the turn
    # and the browser's EventSource is live.
    user_bubble = wait_for_stream(page, '#chat-log .chat-msg-user', TURN_TIMEOUT_MS, 'the user bubble')
    expect(user_bubble).to_contain_text(PROMPT[:40], timeout=UI_TIMEOUT_MS)
    shot(page, '04-user-bubble')

    step(5, 'streamed assistant text appears')
    reply = wait_for_stream(page, '#chat-log .chat-msg-assistant', TURN_TIMEOUT_MS, 'assistant text')
    expect(reply).to_contain_text(re.compile(r'\S'), timeout=UI_TIMEOUT_MS)
    print('    assistant: %r' % reply.inner_text().strip()[:120])
    shot(page, '05-assistant-text')

    step(6, 'a tool card appears')
    tool = wait_for_stream(page, TOOL_CARD, TURN_TIMEOUT_MS, 'a tool card')
    print('    tool card: %r' % tool.inner_text().strip()[:120])
    shot(page, '06-tool-card')

    step(7, 'the turn finishes and the composer re-enables')
    expect(page.locator('#chat-input')).to_be_enabled(timeout=TURN_TIMEOUT_MS)
    expect(page.locator('#chat-thinking')).to_be_hidden(timeout=UI_TIMEOUT_MS)
    shot(page, '07-turn-done')

    print('\nPASS — %d chat entries rendered' % page.locator('#chat-log > *').count())


def main():
    if not USERNAME or not PASSWORD:
        print('error: CP_USERNAME and CP_PASSWORD must be set (see run.sh / README.md)', file=sys.stderr)
        return 2

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    console = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': 1600, 'height': 1000})
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        page.set_default_timeout(UI_TIMEOUT_MS)
        page.on('console', lambda m: console.append('%s: %s' % (m.type, m.text)))
        page.on('pageerror', lambda e: console.append('pageerror: %s' % e))

        status = 0
        try:
            run(page)
        except Failure as e:
            print('\nFAIL: %s' % e, file=sys.stderr)
            shot(page, '99-failure')
            status = 1
        except PlaywrightError as e:
            print('\nFAIL (playwright): %s' % e, file=sys.stderr)
            shot(page, '99-failure')
            status = 1
        finally:
            context.tracing.stop(path=str(ARTIFACTS / 'trace.zip'))
            (ARTIFACTS / 'console.log').write_text('\n'.join(console))
            browser.close()

    errors = [line for line in console if line.startswith(('error', 'pageerror'))]
    if errors:
        print('\n%d browser console error(s), see %s:' % (len(errors), ARTIFACTS / 'console.log'))
        for line in errors[:10]:
            print('    %s' % line)
    return status


if __name__ == '__main__':
    sys.exit(main())
