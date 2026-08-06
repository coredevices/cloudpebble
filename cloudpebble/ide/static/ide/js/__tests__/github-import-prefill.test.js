import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

// project_list.js is one $(function(){...}) block; the jQuery mock runs the
// callback immediately, so loading the file executes the deep-link prefill.
// Every jQuery method is a chainable no-op except val(), which records per
// selector — enough to assert what lands in the import dialog's fields.
function makeJqueryMock() {
    var elements = {};
    var $ = function(selector) {
        if (typeof selector === 'function') {
            selector();
            return $;
        }
        if (!elements[selector]) {
            var store = { value: undefined };
            var el = new Proxy(store, {
                get: function(target, prop) {
                    if (prop === 'val') {
                        return function(v) {
                            if (v === undefined) return target.value;
                            target.value = v;
                            return el;
                        };
                    }
                    if (prop === 'text') return function() { return ''; };
                    if (prop === 'length') return 0;
                    if (prop === '_isMock') return true;
                    return function() { return el; };
                }
            });
            elements[selector] = el;
        }
        return elements[selector];
    };
    $.Deferred = vi.fn();
    $.elements = elements;
    return $;
}

function loadWithPath(pathname) {
    var code = readFileSync(resolve(__dirname, '..', 'project_list.js'), 'utf8');
    var $ = makeJqueryMock();
    var fn = new Function(
        '$', 'jQuery', 'gettext', 'jquery_csrf_setup', 'ga', 'Ajax', 'CloudPebble', 'location',
        code
    );
    fn($, $, function(s) { return s; }, vi.fn(), vi.fn(), {}, {}, { pathname: pathname });
    return {
        name: $('#import-github-name').val(),
        url: $('#import-github-url').val(),
        branch: $('#import-github-branch').val()
    };
}

describe('GitHub import deep-link prefill', () => {
    it('hands a /tree/<branch>/<subdir> URL (the appstore Remix shape) to the server whole', () => {
        var fields = loadWithPath('/ide/import/github/emindeniz99/pebble-signals/tree/main/faces/slothvec');
        expect(fields.url).toBe('github.com/emindeniz99/pebble-signals/tree/main/faces/slothvec');
        expect(fields.name).toBe('slothvec');
        // The URL is authoritative for the ref — the branch box stays empty.
        expect(fields.branch).toBeUndefined();
    });

    it('suggests the repo name when a /tree/ URL has no subdirectory', () => {
        var fields = loadWithPath('/ide/import/github/user/repo/tree/main');
        expect(fields.url).toBe('github.com/user/repo/tree/main');
        expect(fields.name).toBe('repo');
        expect(fields.branch).toBeUndefined();
    });

    it('suggests the repo name for /blob/ and /commit/ URLs (tail is a file or SHA, not a name)', () => {
        var blob = loadWithPath('/ide/import/github/user/repo/blob/main/src/app.js');
        expect(blob.url).toBe('github.com/user/repo/blob/main/src/app.js');
        expect(blob.name).toBe('repo');
        var commit = loadWithPath('/ide/import/github/user/repo/commit/abc123');
        expect(commit.url).toBe('github.com/user/repo/commit/abc123');
        expect(commit.name).toBe('repo');
    });

    it('keeps the legacy /<user>/<repo>/<branch> deep-link contract', () => {
        var fields = loadWithPath('/ide/import/github/user/repo/dev');
        expect(fields.url).toBe('github.com/user/repo');
        expect(fields.name).toBe('user');
        expect(fields.branch).toBe('dev');
    });

    it('keeps legacy slashed-branch deep links', () => {
        var fields = loadWithPath('/ide/import/github/user/repo/feat/x');
        expect(fields.url).toBe('github.com/user/repo');
        expect(fields.branch).toBe('feat/x');
    });

    it('leaves the branch empty for a plain repo link (server imports the default branch)', () => {
        var fields = loadWithPath('/ide/import/github/user/repo');
        expect(fields.url).toBe('github.com/user/repo');
        expect(fields.branch).toBeUndefined();
    });

    it('does nothing outside the import deep link', () => {
        var fields = loadWithPath('/ide/');
        expect(fields.url).toBeUndefined();
        expect(fields.name).toBeUndefined();
    });
});
