import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

// project_list.js is one $(function(){...}) block; the jQuery mock runs the
// callback immediately, so loading the file executes the deep-link prefill.
// Every jQuery method is a chainable no-op except val(), which records per
// selector — enough to assert what lands in the import dialog's fields.
function makeJqueryMock(attrs) {
    var elements = {};
    var $ = function(selector) {
        if (typeof selector === 'function') {
            selector();
            return $;
        }
        if (!elements[selector]) {
            var store = { value: undefined, text: '', clickHandler: null };
            var el = new Proxy(store, {
                get: function(target, prop) {
                    if (prop === 'val') {
                        return function(v) {
                            if (v === undefined) return target.value;
                            target.value = v;
                            return el;
                        };
                    }
                    if (prop === 'text') {
                        return function(v) {
                            if (v === undefined) return target.text;
                            target.text = v;
                            return el;
                        };
                    }
                    if (prop === 'click') {
                        return function(fn) {
                            if (typeof fn === 'function') target.clickHandler = fn;
                            else if (target.clickHandler) target.clickHandler();
                            return el;
                        };
                    }
                    if (prop === 'find') return function(sel) { return $(sel); };
                    if (prop === 'attr') {
                        return function(name) {
                            if ((attrs || {})[selector]) return attrs[selector][name];
                            return el;
                        };
                    }
                    if (prop === 'is') return function() { return false; };
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

function load(pathname, attrs) {
    var code = readFileSync(resolve(__dirname, '..', 'project_list.js'), 'utf8');
    var $ = makeJqueryMock(attrs);
    var chain = { then: function() { return chain; }, catch: function() { return chain; } };
    var ajax = { Post: vi.fn(function() { return chain; }), PollTask: vi.fn() };
    var fn = new Function(
        '$', 'jQuery', 'gettext', 'jquery_csrf_setup', 'ga', 'Ajax', 'CloudPebble', 'location',
        code
    );
    fn($, $, function(s) { return s; }, vi.fn(), vi.fn(), ajax, {}, { pathname: pathname });
    return { $: $, ajax: ajax };
}

function loadWithPath(pathname) {
    var h = load(pathname);
    return {
        name: h.$('#import-github-name').val(),
        url: h.$('#import-github-url').val(),
        branch: h.$('#import-github-branch').val()
    };
}

// Drives the real import dialog: the active tab claims to be the GitHub
// pane, fields are set, and the Run button's captured handler is fired.
function submitGithubImport(fields) {
    var h = load('/ide/', { '#import-prompt .tab-pane.active': { id: 'import-github' } });
    h.$('#import-github-name').val(fields.name);
    h.$('#import-github-url').val(fields.url);
    h.$('#import-github-branch').val(fields.branch);
    h.$('#run-import').click();
    return h;
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

    it('decodes the suggested name but keeps the URL encoded', () => {
        var fields = loadWithPath('/ide/import/github/user/repo/tree/main/my%20dir');
        expect(fields.url).toBe('github.com/user/repo/tree/main/my%20dir');
        expect(fields.name).toBe('my dir');
    });

    it('keeps the legacy /<user>/<repo>/<branch> deep-link contract', () => {
        var fields = loadWithPath('/ide/import/github/user/repo/dev');
        expect(fields.url).toBe('github.com/user/repo');
        // parts[3] is the USERNAME — a pre-existing upstream quirk, kept
        // bug-compatible on purpose (this PR only preserves the contract).
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


describe('GitHub import submit handler', () => {
    it('submits an empty branch untouched (no master fallback)', () => {
        var h = submitGithubImport({ name: 'proj', url: 'github.com/user/repo', branch: '' });
        expect(h.ajax.Post).toHaveBeenCalledWith('/ide/import/github', {
            name: 'proj', repo: 'github.com/user/repo', branch: '', add_remote: false
        });
    });

    it('lets /tree/ URLs through the prefix check to the server', () => {
        var h = submitGithubImport({
            name: 'sloth', url: 'github.com/user/repo/tree/main/faces/slothvec', branch: ''
        });
        expect(h.ajax.Post).toHaveBeenCalledWith('/ide/import/github', {
            name: 'sloth', repo: 'github.com/user/repo/tree/main/faces/slothvec',
            branch: '', add_remote: false
        });
    });

    it('rejects a non-GitHub URL before posting', () => {
        var h = submitGithubImport({ name: 'p', url: 'gitlab.com/user/repo', branch: '' });
        expect(h.ajax.Post).not.toHaveBeenCalled();
        expect(h.$('.errors').text()).toContain('GitHub');
    });
});
