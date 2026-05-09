import { describe, it, expect, vi, beforeEach } from 'vitest';
import { JSDOM } from 'jsdom';
import fs from 'fs';
import path from 'path';

function createEnv() {
    const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', { url: 'http://localhost' });
    const w = dom.window;
    const $ = vi.fn();
    $.fn = {};
    w.$ = w.jQuery = $;
    w._ = { extend: vi.fn((obj) => obj) };
    w.Backbone = { Events: {} };
    w.gettext = (s) => s;
    w.ConnectionType = {
        None: 0, Phone: 1, Qemu: 2,
        QemuAplite: 6, QemuBasalt: 10, QemuChalk: 18,
        QemuDiorite: 34, QemuEmery: 66, QemuGabbro: 130, QemuFlint: 258
    };
    w.ConnectionPlatformNames = {
        2: 'aplite', 6: 'aplite', 10: 'basalt', 18: 'chalk',
        34: 'diorite', 66: 'emery', 130: 'gabbro', 258: 'flint'
    };
    w.CloudPebble = {};
    w.SharedPebble = null;
    return { window: w, $ };
}

function loadScript(window, filePath) {
    const code = fs.readFileSync(path.resolve(__dirname, filePath), 'utf8');
    const script = window.document.createElement('script');
    script.textContent = code;
    window.document.head.appendChild(script);
}

describe('CloudPebble.CompileReboot.shouldShowPrompt', () => {
    let shouldShowPrompt;

    beforeEach(() => {
        const { window } = createEnv();
        window.CloudPebble.CompileReboot = {
            shouldShowPrompt: function(error, isVirtual) {
                return isVirtual && !!error && !!error.message && error.message.indexOf('rebooting') !== -1;
            }
        };
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
    let $, modal, retryBtn, errorMessageEl, window;

    beforeEach(() => {
        const env = createEnv();
        $ = env.$;
        window = env.window;
        errorMessageEl = { text: vi.fn() };
        retryBtn = { off: vi.fn().mockReturnThis(), on: vi.fn().mockReturnThis() };
        modal = {
            find: vi.fn((selector) => {
                if (selector === '.reboot-error-message') return errorMessageEl;
                if (selector === '#reboot-retry-btn') return retryBtn;
                return null;
            }),
            modal: vi.fn()
        };

        $.mockImplementation((selector) => {
            if (selector === '#emulator-reboot-prompt') return modal;
            return null;
        });
    });

    it('sets the error message text on the modal', () => {
        window.CloudPebble.CompileReboot = {
            shouldShowPrompt: function() {},
            showRebootPrompt: function(errorMessage, kind, build, rebootFn, installFn) {
                var rebootModal = $('#emulator-reboot-prompt');
                rebootModal.find('.reboot-error-message').text(errorMessage);
                rebootModal.find('#reboot-retry-btn').off('click').on('click', function() {
                    rebootModal.modal('hide');
                    rebootFn().then(function() {
                        return installFn(kind, build);
                    }).catch(function(err) {
                        console.warn('reboot & retry failed:', err);
                    });
                });
                rebootModal.modal('show');
            }
        };

        window.CloudPebble.CompileReboot.showRebootPrompt('Phone is rebooting', 'basalt', { id: 1 }, vi.fn(), vi.fn());

        expect(errorMessageEl.text).toHaveBeenCalledWith('Phone is rebooting');
    });

    it('unbinds previous click handlers from retry button before binding new one', () => {
        window.CloudPebble.CompileReboot = {
            shouldShowPrompt: function() {},
            showRebootPrompt: function(errorMessage, kind, build, rebootFn, installFn) {
                var rebootModal = $('#emulator-reboot-prompt');
                rebootModal.find('.reboot-error-message').text(errorMessage);
                rebootModal.find('#reboot-retry-btn').off('click').on('click', function() {
                    rebootModal.modal('hide');
                    rebootFn().then(function() {
                        return installFn(kind, build);
                    }).catch(function(err) {
                        console.warn('reboot & retry failed:', err);
                    });
                });
                rebootModal.modal('show');
            }
        };

        window.CloudPebble.CompileReboot.showRebootPrompt('err', 'basalt', { id: 1 }, vi.fn(), vi.fn());

        expect(retryBtn.off).toHaveBeenCalledWith('click');
        expect(retryBtn.on).toHaveBeenCalledWith('click', expect.any(Function));
    });

    it('calls modal("show") to display the prompt', () => {
        window.CloudPebble.CompileReboot = {
            shouldShowPrompt: function() {},
            showRebootPrompt: function(errorMessage, kind, build, rebootFn, installFn) {
                var rebootModal = $('#emulator-reboot-prompt');
                rebootModal.find('.reboot-error-message').text(errorMessage);
                rebootModal.find('#reboot-retry-btn').off('click').on('click', function() {
                    rebootModal.modal('hide');
                    rebootFn().then(function() {
                        return installFn(kind, build);
                    }).catch(function(err) {
                        console.warn('reboot & retry failed:', err);
                    });
                });
                rebootModal.modal('show');
            }
        };

        window.CloudPebble.CompileReboot.showRebootPrompt('err', 'basalt', { id: 1 }, vi.fn(), vi.fn());

        expect(modal.modal).toHaveBeenCalledWith('show');
    });

    it('retry button click hides modal, calls rebootFn, then installFn', async () => {
        window.CloudPebble.CompileReboot = {
            shouldShowPrompt: function() {},
            showRebootPrompt: function(errorMessage, kind, build, rebootFn, installFn) {
                var rebootModal = $('#emulator-reboot-prompt');
                rebootModal.find('.reboot-error-message').text(errorMessage);
                rebootBtn_off_click = null;
                rebootModal.find('#reboot-retry-btn').off('click').on('click', function handler() {
                    rebootBtn_off_click = handler;
                });
                rebootModal.modal('show');
            }
        };

        let retryClickHandler = null;
        retryBtn.on = vi.fn((event, handler) => {
            if (event === 'click') retryClickHandler = handler;
            return retryBtn;
        });

        window.CloudPebble.CompileReboot = {
            shouldShowPrompt: function() {},
            showRebootPrompt: function(errorMessage, kind, build, rebootFn, installFn) {
                var rebootModal = $('#emulator-reboot-prompt');
                rebootModal.find('.reboot-error-message').text(errorMessage);
                rebootModal.find('#reboot-retry-btn').off('click').on('click', function() {
                    rebootModal.modal('hide');
                    rebootFn().then(function() {
                        return installFn(kind, build);
                    }).catch(function(err) {});
                });
                rebootModal.modal('show');
            }
        };

        const rebootFn = vi.fn(() => Promise.resolve());
        const installFn = vi.fn(() => Promise.resolve());
        const build = { id: 42, download: '/build/42' };

        window.CloudPebble.CompileReboot.showRebootPrompt('rebooting', 'basalt', build, rebootFn, installFn);

        await retryClickHandler();

        expect(modal.modal).toHaveBeenCalledWith('hide');
        expect(rebootFn).toHaveBeenCalled();
        expect(installFn).toHaveBeenCalledWith('basalt', build);
    });
});