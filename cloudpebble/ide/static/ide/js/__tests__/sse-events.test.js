import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

function makeCloudPebble() {
    return {
        Sidebar: {
            SetIcon: vi.fn(),
            ClearIcon: vi.fn()
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
        it('sets github sidebar icon to refresh and calls OnPullStart', () => {
            events.handlePullStart();
            expect(CloudPebble.Sidebar.SetIcon).toHaveBeenCalledWith('github', 'refresh');
            expect(CloudPebble.GitHub.OnPullStart).toHaveBeenCalled();
        });
    });

    describe('handlePullComplete', () => {
        it('clears github icon and calls OnPullComplete with parsed data', () => {
            const event = { data: JSON.stringify({ github_last_commit: 'abc123' }) };
            events.handlePullComplete(event);
            expect(CloudPebble.Sidebar.ClearIcon).toHaveBeenCalledWith('github');
            expect(CloudPebble.GitHub.OnPullComplete).toHaveBeenCalledWith({ github_last_commit: 'abc123' });
        });

        it('handles pull_complete with empty data', () => {
            const event = { data: JSON.stringify({}) };
            events.handlePullComplete(event);
            expect(CloudPebble.GitHub.OnPullComplete).toHaveBeenCalledWith({});
        });
    });

    describe('handlePullFailed', () => {
        it('clears github icon and calls OnPullFailed', () => {
            events.handlePullFailed();
            expect(CloudPebble.Sidebar.ClearIcon).toHaveBeenCalledWith('github');
            expect(CloudPebble.GitHub.OnPullFailed).toHaveBeenCalled();
        });
    });

    describe('handleBuildStart', () => {
        it('sets compile sidebar icon to refresh and calls OnBuildStart with build_id', () => {
            const event = { data: JSON.stringify({ build_id: 42 }) };
            events.handleBuildStart(event);
            expect(CloudPebble.Sidebar.SetIcon).toHaveBeenCalledWith('compile', 'refresh');
            expect(CloudPebble.Compile.OnBuildStart).toHaveBeenCalledWith(42);
        });

        it('parses build_id as integer from JSON data', () => {
            const event = { data: JSON.stringify({ build_id: 99 }) };
            events.handleBuildStart(event);
            expect(CloudPebble.Compile.OnBuildStart).toHaveBeenCalledWith(99);
        });
    });

    describe('handleBuildComplete', () => {
        it('clears compile icon and calls OnBuildComplete with build_id and state', () => {
            const event = { data: JSON.stringify({ build_id: 42, state: 'succeeded' }) };
            events.handleBuildComplete(event);
            expect(CloudPebble.Sidebar.ClearIcon).toHaveBeenCalledWith('compile');
            expect(CloudPebble.Compile.OnBuildComplete).toHaveBeenCalledWith(42, 'succeeded');
        });

        it('passes failed state correctly', () => {
            const event = { data: JSON.stringify({ build_id: 7, state: 'failed' }) };
            events.handleBuildComplete(event);
            expect(CloudPebble.Compile.OnBuildComplete).toHaveBeenCalledWith(7, 'failed');
        });
    });
});