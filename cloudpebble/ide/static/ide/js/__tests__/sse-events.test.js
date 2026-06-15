import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

function makeCloudPebble() {
    return {
        Sidebar: {
            ShowPending: vi.fn(),
            HidePending: vi.fn()
        },
        GitHub: {
            OnPullStart: vi.fn(),
            OnPullComplete: vi.fn(),
            OnPullFailed: vi.fn()
        },
        Compile: {
            OnBuildStart: vi.fn(),
            OnBuildComplete: vi.fn()
        }
    };
}

function loadSseModule(CloudPebble) {
    global.PROJECT_ID = 1;
    global.CloudPebble = CloudPebble;
    global.EventSource = vi.fn().mockImplementation(() => ({
        addEventListener: vi.fn(),
        close: vi.fn(),
        readyState: 0
    }));

    const ssePath = resolve(__dirname, '..', 'sse.js');
    const code = readFileSync(ssePath, 'utf8');
    const fn = new Function(code);
    fn();

    return CloudPebble.Events;
}

describe('sse event handlers', () => {
    let CloudPebble;
    let events;

    beforeEach(() => {
        CloudPebble = makeCloudPebble();
        events = loadSseModule(CloudPebble);
        vi.clearAllMocks();
    });

    describe('handlePullStart', () => {
        it('shows pending pill with Pulling text and calls OnPullStart', () => {
            events.handlePullStart();
            expect(CloudPebble.Sidebar.ShowPending).toHaveBeenCalledWith('github', 'Pulling');
            expect(CloudPebble.GitHub.OnPullStart).toHaveBeenCalled();
        });
    });

    describe('handlePullComplete', () => {
        it('hides pending pill and calls OnPullComplete with parsed data', () => {
            const event = { data: JSON.stringify({ github_last_commit: 'abc123' }) };
            events.handlePullComplete(event);
            expect(CloudPebble.Sidebar.HidePending).toHaveBeenCalledWith('github');
            expect(CloudPebble.GitHub.OnPullComplete).toHaveBeenCalledWith({ github_last_commit: 'abc123' });
        });

        it('handles pull_complete with empty data', () => {
            const event = { data: JSON.stringify({}) };
            events.handlePullComplete(event);
            expect(CloudPebble.GitHub.OnPullComplete).toHaveBeenCalledWith({});
        });
    });

    describe('handlePullFailed', () => {
        it('hides pending pill and calls OnPullFailed', () => {
            events.handlePullFailed();
            expect(CloudPebble.Sidebar.HidePending).toHaveBeenCalledWith('github');
            expect(CloudPebble.GitHub.OnPullFailed).toHaveBeenCalled();
        });
    });

    describe('handleBuildStart', () => {
        it('shows pending pill with Building text and calls OnBuildStart with build_id', () => {
            const event = { data: JSON.stringify({ build_id: 42 }) };
            events.handleBuildStart(event);
            expect(CloudPebble.Sidebar.ShowPending).toHaveBeenCalledWith('compile', 'Building');
            expect(CloudPebble.Compile.OnBuildStart).toHaveBeenCalledWith(42);
        });

        it('parses build_id as integer from JSON data', () => {
            const event = { data: JSON.stringify({ build_id: 99 }) };
            events.handleBuildStart(event);
            expect(CloudPebble.Compile.OnBuildStart).toHaveBeenCalledWith(99);
        });
    });

    describe('handleBuildComplete', () => {
        it('hides pending pill and calls OnBuildComplete with build_id and state', () => {
            const event = { data: JSON.stringify({ build_id: 42, state: 'succeeded' }) };
            events.handleBuildComplete(event);
            expect(CloudPebble.Sidebar.HidePending).toHaveBeenCalledWith('compile');
            expect(CloudPebble.Compile.OnBuildComplete).toHaveBeenCalledWith(42, 'succeeded');
        });

        it('passes failed state correctly', () => {
            const event = { data: JSON.stringify({ build_id: 7, state: 'failed' }) };
            events.handleBuildComplete(event);
            expect(CloudPebble.Compile.OnBuildComplete).toHaveBeenCalledWith(7, 'failed');
        });
    });
});