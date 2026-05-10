import { describe, it, expect, vi, beforeEach } from 'vitest';
import { JSDOM } from 'jsdom';
import vm from 'vm';
import fs from 'fs';
import path from 'path';

function createEnv() {
    const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', { url: 'http://localhost' });
    const w = dom.window;

    w.CloudPebble = {};

    const $ = vi.fn();
    $.fn = {};
    w.$ = w.jQuery = $;

    return { window: w, $ };
}

function loadCompileReboot(window) {
    const code = fs.readFileSync(path.resolve(__dirname, '../compile-reboot.js'), 'utf8');
    vm.runInNewContext(code, window);
}

describe('CloudPebble.CompileReboot.shouldShowPrompt', () => {
    let shouldShowPrompt;

    beforeEach(() => {
        const { window } = createEnv();
        loadCompileReboot(window);
        shouldShowPrompt = window.CloudPebble.CompileReboot.shouldShowPrompt;
    });

    it('returns true when error message contains "rebooting" and device is virtual', () => {
        expect(shouldShowPrompt(new Error('Phone is rebooting'), true)).toBe(true);
    });

    it('returns true for substring match on "rebooting"', () => {
        expect(shouldShowPrompt(new Error('The watch is rebooting now'), true)).toBe(true);
    });

    it('returns false when device is not virtual', () => {
        expect(shouldShowPrompt(new Error('Phone is rebooting'), false)).toBe(false);
    });

    it('returns false when error is null', () => {
        expect(shouldShowPrompt(null, true)).toBe(false);
    });

    it('returns false when error message does not contain "rebooting"', () => {
        expect(shouldShowPrompt(new Error('Connection timed out'), true)).toBe(false);
    });

    it('returns false when error has no message property', () => {
        expect(shouldShowPrompt({}, true)).toBe(false);
    });

    it('returns false when message is empty string', () => {
        expect(shouldShowPrompt(new Error(''), true)).toBe(false);
    });
});

describe('CloudPebble.CompileReboot.showRebootPrompt', () => {
    let $, window;

    beforeEach(() => {
        const env = createEnv();
        $ = env.$;
        window = env.window;
        loadCompileReboot(window);
    });

    function makeModal() {
        const errorMsgEl = { text: vi.fn() };
        const retryBtn = { off: vi.fn(() => retryBtn), on: vi.fn(() => retryBtn) };
        const modal = {
            find: vi.fn((sel) => {
                if (sel === '.reboot-error-message') return errorMsgEl;
                if (sel === '#reboot-retry-btn') return retryBtn;
                return null;
            }),
            modal: vi.fn()
        };
        return { modal, errorMsgEl, retryBtn };
    }

    it('sets the error message text on the modal', () => {
        const { modal, errorMsgEl } = makeModal();
        const rebootFn = vi.fn(() => Promise.resolve());
        const installFn = vi.fn(() => Promise.resolve());

        window.CloudPebble.CompileReboot.showRebootPrompt(
            'Phone is rebooting', 'basalt', { id: 1 }, rebootFn, installFn, modal
        );

        expect(errorMsgEl.text).toHaveBeenCalledWith('Phone is rebooting');
        expect(modal.modal).toHaveBeenCalledWith('show');
    });

    it('unbinds previous click handlers and binds new one', () => {
        const { modal, retryBtn } = makeModal();
        const rebootFn = vi.fn(() => Promise.resolve());
        const installFn = vi.fn(() => Promise.resolve());

        window.CloudPebble.CompileReboot.showRebootPrompt(
            'err', 'basalt', { id: 1 }, rebootFn, installFn, modal
        );

        expect(retryBtn.off).toHaveBeenCalledWith('click');
        expect(retryBtn.on).toHaveBeenCalledWith('click', expect.any(Function));
    });

    it('retry click hides modal, calls rebootFn, then installFn', async () => {
        const { modal, retryBtn } = makeModal();
        let clickHandler = null;
        retryBtn.on = vi.fn((evt, fn) => {
            if (evt === 'click') clickHandler = fn;
            return retryBtn;
        });

        const rebootFn = vi.fn(() => Promise.resolve());
        const installFn = vi.fn(() => Promise.resolve());
        const build = { id: 42, download: '/build/42' };

        window.CloudPebble.CompileReboot.showRebootPrompt(
            'rebooting', 'basalt', build, rebootFn, installFn, modal
        );

        await clickHandler();

        expect(modal.modal).toHaveBeenCalledWith('hide');
        expect(rebootFn).toHaveBeenCalled();
        expect(installFn).toHaveBeenCalledWith('basalt', build);
    });
});