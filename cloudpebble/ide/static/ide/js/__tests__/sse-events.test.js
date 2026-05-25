import { describe, it, expect, vi } from 'vitest';
import {
    handlePullStart,
    handlePullComplete,
    handlePullFailed,
    handleBuildStart,
    handleBuildComplete
} from '../sse-events.js';

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

describe('handlePullStart', () => {
    it('sets github sidebar icon to refresh and calls OnPullStart', () => {
        const CloudPebble = makeCloudPebble();
        handlePullStart(CloudPebble);
        expect(CloudPebble.Sidebar.SetIcon).toHaveBeenCalledWith('github', 'refresh');
        expect(CloudPebble.GitHub.OnPullStart).toHaveBeenCalled();
    });
});

describe('handlePullComplete', () => {
    it('clears github icon and calls OnPullComplete with parsed data', () => {
        const CloudPebble = makeCloudPebble();
        const event = { data: JSON.stringify({ github_last_commit: 'abc123' }) };
        handlePullComplete(event, CloudPebble);
        expect(CloudPebble.Sidebar.ClearIcon).toHaveBeenCalledWith('github');
        expect(CloudPebble.GitHub.OnPullComplete).toHaveBeenCalledWith({ github_last_commit: 'abc123' });
    });

    it('handles pull_complete with empty data', () => {
        const CloudPebble = makeCloudPebble();
        const event = { data: JSON.stringify({}) };
        handlePullComplete(event, CloudPebble);
        expect(CloudPebble.GitHub.OnPullComplete).toHaveBeenCalledWith({});
    });
});

describe('handlePullFailed', () => {
    it('clears github icon and calls OnPullFailed', () => {
        const CloudPebble = makeCloudPebble();
        handlePullFailed(CloudPebble);
        expect(CloudPebble.Sidebar.ClearIcon).toHaveBeenCalledWith('github');
        expect(CloudPebble.GitHub.OnPullFailed).toHaveBeenCalled();
    });
});

describe('handleBuildStart', () => {
    it('sets compile sidebar icon to refresh and calls OnBuildStart with build_id', () => {
        const CloudPebble = makeCloudPebble();
        const event = { data: JSON.stringify({ build_id: 42 }) };
        handleBuildStart(event, CloudPebble);
        expect(CloudPebble.Sidebar.SetIcon).toHaveBeenCalledWith('compile', 'refresh');
        expect(CloudPebble.Compile.OnBuildStart).toHaveBeenCalledWith(42);
    });

    it('parses build_id as integer from JSON data', () => {
        const CloudPebble = makeCloudPebble();
        const event = { data: JSON.stringify({ build_id: 99 }) };
        handleBuildStart(event, CloudPebble);
        expect(CloudPebble.Compile.OnBuildStart).toHaveBeenCalledWith(99);
    });
});

describe('handleBuildComplete', () => {
    it('clears compile icon and calls OnBuildComplete with build_id and state', () => {
        const CloudPebble = makeCloudPebble();
        const event = { data: JSON.stringify({ build_id: 42, state: 'succeeded' }) };
        handleBuildComplete(event, CloudPebble);
        expect(CloudPebble.Sidebar.ClearIcon).toHaveBeenCalledWith('compile');
        expect(CloudPebble.Compile.OnBuildComplete).toHaveBeenCalledWith(42, 'succeeded');
    });

    it('passes failed state correctly', () => {
        const CloudPebble = makeCloudPebble();
        const event = { data: JSON.stringify({ build_id: 7, state: 'failed' }) };
        handleBuildComplete(event, CloudPebble);
        expect(CloudPebble.Compile.OnBuildComplete).toHaveBeenCalledWith(7, 'failed');
    });
});