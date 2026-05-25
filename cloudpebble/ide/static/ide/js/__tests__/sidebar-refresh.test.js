import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

function makeJqueryMock() {
    var elements = {};
    var $ = function(selector) {
        if (typeof selector === 'function') {
            selector();
            return $;
        }
        var el = elements[selector] || {
            empty: vi.fn(() => el),
            append: vi.fn(() => el),
            remove: vi.fn(() => el),
            data: vi.fn(() => undefined),
            find: vi.fn(() => $),
            children: vi.fn(() => []),
            addClass: vi.fn(() => el),
            removeClass: vi.fn(() => el),
            detach: vi.fn(() => el),
            text: vi.fn((v) => v !== undefined ? (el._text = v, el) : (el._text || '')),
            attr: vi.fn(() => el),
            click: vi.fn(() => el),
            siblings: vi.fn(() => $),
            slideToggle: vi.fn(),
            closest: vi.fn(() => $),
            length: 0
        };
        elements[selector] = el;
        return el;
    };
    $.Deferred = vi.fn(() => {
        var callbacks = { done: [], fail: [], always: [] };
        var promise = {
            done: vi.fn((cb) => { callbacks.done.push(cb); return promise; }),
            fail: vi.fn((cb) => { callbacks.fail.push(cb); return promise; }),
            always: vi.fn((cb) => { callbacks.always.push(cb); return promise; }),
            then: vi.fn((successCb, failCb) => {
                if (successCb) callbacks.done.push(successCb);
                if (failCb) callbacks.fail.push(failCb);
                return promise;
            }),
            promise: vi.fn(() => promise)
        };
        var deferred = {
            resolve: vi.fn((...args) => {
                callbacks.done.forEach(cb => cb(...args));
                callbacks.always.forEach(cb => cb());
            }),
            reject: vi.fn((...args) => {
                callbacks.fail.forEach(cb => cb(...args));
                callbacks.always.forEach(cb => cb());
            }),
            promise: vi.fn(() => promise),
            then: promise.then,
            done: promise.done,
            fail: promise.fail,
            always: promise.always
        };
        return deferred;
    });
    $.each = vi.fn((arr, fn) => {
        if (Array.isArray(arr)) arr.forEach((v, i) => fn(i, v));
        else if (typeof arr === 'object') Object.keys(arr).forEach(k => fn(k, arr[k]));
    });
    $._elements = elements;
    return $;
}

function makeCloudPebble() {
    return {
        Editor: {
            GetUnsavedFiles: vi.fn(() => 3),
            Add: vi.fn()
        },
        Resources: {
            Add: vi.fn(),
            AddAlloyAsset: vi.fn()
        },
        ProjectInfo: { type: 'native' },
        TargetNames: { app: 'App', pkjs: 'PKJS' }
    };
}

function loadSidebarModule(CloudPebble, $, Ajax) {
    global.PROJECT_ID = 1;
    global.CloudPebble = CloudPebble;
    global.$ = $;
    global.jQuery = $;
    global.Ajax = Ajax;
    global._ = { each: vi.fn((arr, fn) => arr.forEach(fn)) };

    var sidebarPath = resolve(__dirname, '..', 'sidebar.js');
    var code = readFileSync(sidebarPath, 'utf8');
    var fn = new Function(code);
    fn();

    return CloudPebble.Sidebar;
}

describe('Sidebar.Refresh', () => {
    let CloudPebble;
    let Sidebar;
    let originalGetUnsavedFiles;
    let $;
    let deferred;

    beforeEach(() => {
        $ = makeJqueryMock();
        CloudPebble = makeCloudPebble();
        originalGetUnsavedFiles = CloudPebble.Editor.GetUnsavedFiles;
        deferred = $.Deferred();
        var Ajax = {
            Get: vi.fn(() => deferred.promise())
        };
        Sidebar = loadSidebarModule(CloudPebble, $, Ajax);
    });

    it('temporarily overrides GetUnsavedFiles to return 0 during refresh', () => {
        Sidebar.Refresh();
        expect(CloudPebble.Editor.GetUnsavedFiles()).toBe(0);
    });

    it('restores GetUnsavedFiles after successful ajax response', () => {
        Sidebar.Refresh();
        expect(CloudPebble.Editor.GetUnsavedFiles()).toBe(0);

        deferred.resolve({
            type: 'native',
            source_files: [],
            resources: []
        });

        expect(CloudPebble.Editor.GetUnsavedFiles).toBe(originalGetUnsavedFiles);
    });

    it('restores GetUnsavedFiles even when ajax request fails', () => {
        Sidebar.Refresh();
        expect(CloudPebble.Editor.GetUnsavedFiles()).toBe(0);

        deferred.reject();

        expect(CloudPebble.Editor.GetUnsavedFiles).toBe(originalGetUnsavedFiles);
    });

    it('restores GetUnsavedFiles when done callback throws', () => {
        CloudPebble.Editor.Add = vi.fn(() => { throw new Error('boom'); });

        Sidebar.Refresh();
        try {
            deferred.resolve({
                type: 'native',
                source_files: [{ target: 'app', name: 'main.c' }],
                resources: []
            });
        } catch (e) {}

        expect(CloudPebble.Editor.GetUnsavedFiles).toBe(originalGetUnsavedFiles);
    });

    it('updates ProjectInfo from ajax response', () => {
        var newData = { type: 'pebblejs', source_files: [], resources: [] };
        Sidebar.Refresh();
        deferred.resolve(newData);
        expect(CloudPebble.ProjectInfo).toBe(newData);
    });

    it('adds source files from response', () => {
        Sidebar.Refresh();
        deferred.resolve({
            type: 'native',
            source_files: [{ target: 'app', name: 'main.c' }],
            resources: []
        });
        expect(CloudPebble.Editor.Add).toHaveBeenCalled();
    });

    it('adds resources from response', () => {
        Sidebar.Refresh();
        deferred.resolve({
            type: 'native',
            source_files: [],
            resources: [{ id: 1, file_name: 'icon.png' }]
        });
        expect(CloudPebble.Resources.Add).toHaveBeenCalledWith({ id: 1, file_name: 'icon.png' });
    });
});