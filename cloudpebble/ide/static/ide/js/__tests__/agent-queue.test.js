import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

/**
 * The queue and the running/idle state are the two things that decide whether the
 * panel is usable mid-turn: get them wrong and the user sees no spinner, no Stop
 * button, and "the agent is already working" when they try to say anything.
 *
 * jQuery and underscore are not vendored in this repo (the IDE loads them from a
 * CDN), so this stubs the handful of calls the panel makes rather than pulling in
 * two dependencies for one test.
 */
function chainable(store) {
    const node = {
        _children: [],
        _text: '',
        _shown: true,
        empty() { node._children = []; return node; },
        children(sel) {
            if (sel === '.chat-intro') {
                return { remove() { node._removedIntro = true; } };
            }
            return { length: node._children.length };
        },
        append(child) { node._children.push(child); return node; },
        prepend(child) { node._children.unshift(child); return node; },
        text(t) { if (t === undefined) return node._text; node._text = t; return node; },
        attr() { return node; },
        addClass() { return node; },
        removeClass() { return node; },
        toggleClass() { return node; },
        html() { return node; },
        val(v) { if (v === undefined) return node._val || ''; node._val = v; return node; },
        prop() { return node; },
        focus() { return node; },
        hide() { node._shown = false; return node; },
        show() { node._shown = true; return node; },
        toggle(on) { node._shown = !!on; return node; },
        slideToggle() { return node; },
        find() { return chainable(store); },
        click(fn) { if (fn) node._click = fn; return node; },
        keydown() { return node; },
        change() { return node; },
        on() { return node; },
        length: 1,
    };
    return node;
}

function loadAgent() {
    const store = {};
    const registry = {};
    const $ = vi.fn((sel) => {
        if (typeof sel === 'function') { store.ready = sel; return chainable(store); }
        const key = String(sel);
        // '<div ...>' builds a new element every time; '#chat-queue' is a lookup
        // of the same one. Caching both would make two queue rows share a node,
        // and then share a click handler.
        if (key.charAt(0) === '<') return chainable(store);
        if (!registry[key]) registry[key] = chainable(store);
        return registry[key];
    });
    $.trim = (s) => (s || '').trim();

    global.$ = $;
    global.jQuery = $;
    global._ = {
        each: (list, fn) => (list || []).forEach(fn),
        some: (list, fn) => (list || []).some(fn),
        isFunction: (f) => typeof f === 'function',
    };
    global.gettext = (s) => s;
    global.interpolate = (s, args) => s.replace(/%s/g, () => args.shift());
    global.PROJECT_ID = 1;
    global.localStorage = { getItem: () => null, setItem: () => {} };
    global.Ajax = { Post: vi.fn(() => Promise.resolve({})), Get: vi.fn(() => Promise.resolve({})) };
    global.EventSource = vi.fn(() => ({ close: vi.fn() }));
    global.CloudPebble = {
        Sidebar: { Refresh: vi.fn() },
        Compile: { Show: vi.fn() },
    };
    global.SharedPebble = { isVirtual: () => false, getPlatformName: () => 'emery' };

    const code = readFileSync(resolve(__dirname, '..', 'agent.js'), 'utf8');
    new Function(code)();
    return { agent: global.CloudPebble.Agent, registry, $ };
}

describe('agent chat panel', () => {
    let agent, registry;

    beforeEach(() => {
        vi.clearAllMocks();
        ({ agent, registry } = loadAgent());
    });

    it('queues a message instead of sending it while a turn is running', async () => {
        agent.Render({ type: 'sync', data: { status: 'running' } });
        agent.Send('and then make it blue');

        expect(global.Ajax.Post).not.toHaveBeenCalledWith(
            expect.stringContaining('/agent/message'), expect.anything());
        expect(agent.Queue()).toEqual(['and then make it blue']);
    });

    it('drops a queued message when its remove control is used', () => {
        agent.Render({ type: 'sync', data: { status: 'running' } });
        agent.Send('first');
        agent.Send('second');
        expect(agent.Queue()).toEqual(['first', 'second']);

        const rows = registry['#chat-queue']._children;
        rows[0]._children[0]._click({ preventDefault() {} });
        expect(agent.Queue()).toEqual(['second']);
    });

    it('sends the next queued message when the turn ends', async () => {
        agent.Render({ type: 'sync', data: { status: 'running' } });
        agent.Send('next thing');
        agent.Render({ type: 'done', data: {} });

        expect(agent.Queue()).toEqual([]);
        expect(global.Ajax.Post).toHaveBeenCalledWith(
            expect.stringContaining('/agent/start'));
    });

    it('a sync saying running wins over a replayed terminal event', () => {
        // History replays old turns, terminal events and all. Only the sync that
        // follows the replay knows whether anything is running NOW.
        agent.Render({ seq: 1, type: 'error', data: { kind: 'auth', message: 'expired' } });
        agent.Render({ seq: 2, type: 'sync', data: { status: 'running' } });
        expect(agent.Running()).toBe(true);
    });

    it('a stopped turn does not release the queue', () => {
        // Stop means stop. Draining on any transition to idle made Stop launch
        // the next queued message, and an expired key burn the whole queue.
        agent.Render({ type: 'sync', data: { status: 'running' } });
        agent.Send('one');
        agent.Send('two');
        agent.Render({ type: 'error', data: { kind: 'cancelled', message: 'Stopped.' } });

        expect(agent.Running()).toBe(false);
        expect(agent.Queue()).toEqual(['one', 'two']);
        expect(global.Ajax.Post).not.toHaveBeenCalledWith(
            expect.stringContaining('/agent/message'), expect.anything());
    });

    it('an auth failure does not throw the queue at the same wall', () => {
        agent.Render({ type: 'sync', data: { status: 'running' } });
        agent.Send('one');
        agent.Render({ type: 'error', data: { kind: 'auth', message: 'expired' } });
        expect(agent.Queue()).toEqual(['one']);
    });

    it('pulls the IDE back in step when the agent changes the project', async () => {
        // Otherwise the editor shows stale text and the user's next save is
        // rejected as "modified since you last saved it".
        vi.useFakeTimers();
        agent.Render({ type: 'file_edit', data: { path: 'src/c/main.c', file_id: 3, diff: '' } });
        agent.Render({ type: 'project_changed', data: { what: 'resources' } });
        expect(global.CloudPebble.Sidebar.Refresh).not.toHaveBeenCalled();

        vi.advanceTimersByTime(500);
        // Debounced: a turn writes several files in a row, and each refresh is a
        // whole project/info fetch plus a sidebar rebuild.
        expect(global.CloudPebble.Sidebar.Refresh).toHaveBeenCalledTimes(1);
        vi.useRealTimers();
    });

    it('offers examples in an empty panel, and drops them once anything arrives', () => {
        // The panel binds Init on document ready, which the stub never fires.
        agent.Init();
        const log = registry['#chat-log'];
        expect(log._children.length).toBeGreaterThan(0);

        agent.Render({ type: 'text', role: 'user', data: { text: 'make me a watchface' } });
        // The intro is guidance, not transcript: it goes the moment a real
        // message lands, and never comes back on top of history.
        expect(log._removedIntro).toBe(true);
    });

    it('starts the best screen the project targets, not the first button', () => {
        // The buttons are in DOM order, which begins at Aplite: 144x168 and black
        // and white. A colour watchface got designed and verified on it.
        const clicked = [];
        const original = global.$;
        global.$ = Object.assign(function(sel) {
            const key = String(sel);
            const node = original(sel);
            if (key.indexOf('install-in-qemu-') !== -1) {
                // Only emery and aplite exist for this project.
                const has = key.indexOf('emery') !== -1 || key.indexOf('aplite') !== -1;
                return Object.assign(Object.create(node), {
                    length: has ? 1 : 0,
                    click() { clicked.push(key); return this; },
                });
            }
            return node;
        }, original);

        agent.Render({ type: 'sync', data: { status: 'running' } });
        agent.Render({ type: 'tool_result', data: {
            tool: 'install', ok: false, summary: 'no emulator is running' } });

        global.$ = original;
        expect(clicked.length).toBe(1);
        expect(clicked[0]).toContain('emery');
    });

    it('starts the emulator itself when a tool asks for one', () => {
        // A new user does not know "no emulator is running" means Build & Run ->
        // Emery, and should not have to: the panel owns the emulator, so it opens
        // it and tells the agent to carry on.
        agent.Render({ type: 'sync', data: { status: 'running' } });
        agent.Render({ type: 'tool_result', data: {
            tool: 'install', ok: false,
            summary: 'no emulator is running -- open the emulator in CloudPebble first' } });

        expect(global.CloudPebble.Compile.Show).toHaveBeenCalled();
    });

    it('does not start an emulator while replaying history', () => {
        // A reload replays every old failure; none of them should launch a VM.
        agent.Render({ type: 'tool_result', data: {
            tool: 'install', ok: false, summary: 'no emulator is running' } });
        expect(global.CloudPebble.Compile.Show).not.toHaveBeenCalled();
    });

    it('shows Stop while running, and Send becomes Queue rather than vanishing', () => {
        // Hiding Send left Enter as the only route to the queue, which nothing
        // advertises -- clicking where Send had been did nothing at all.
        agent.Render({ type: 'sync', data: { status: 'running' } });
        expect(registry['#chat-stop']._shown).toBe(true);
        expect(registry['#chat-send']._shown).toBe(true);
        expect(registry['#chat-send']._text).toBe('Queue');

        agent.Render({ type: 'done', data: {} });
        expect(registry['#chat-stop']._shown).toBe(false);
        expect(registry['#chat-send']._text).toBe('Send');
    });
});
