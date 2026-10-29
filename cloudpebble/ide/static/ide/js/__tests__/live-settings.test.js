import {describe, it, expect, vi} from 'vitest';
import {readFileSync} from 'fs';
import {resolve} from 'path';

function setup(saveFunction) {
    const events = {};
    const element = {};
    ['find', 'siblings', 'show', 'hide', 'delay', 'closest', 'insertAfter', 'children'].forEach(k => element[k] = vi.fn(() => element));
    element.bind = vi.fn();
    element.on = (event, selector, callback) => { events[event] = callback; return element; };
    const underscore = {defaults: (o, d) => Object.assign({}, d, o), isFunction: v => typeof v === 'function', isObject: v => !!v};
    const create = new Function('$', '_', readFileSync(resolve('live_settings_form.js'), 'utf8') + '; return make_live_settings_form;')(() => element, underscore);
    const onSave = vi.fn(), onError = vi.fn();
    const form = create({form: element, save_function: saveFunction, on_save: onSave, error_function: onError});
    form.init();
    return {form, events, onSave, onError};
}

describe('settings autosave', () => {
    it('does not mark edits typed during an older save as saved', async () => {
        let finish;
        const state = setup(() => new Promise(resolve => finish = resolve));
        const pending = state.form.save();
        state.events.input.call({});
        finish();
        await pending;
        expect(state.onSave).not.toHaveBeenCalled();
    });
    it('saves the latest queued edit after the in-flight request', async () => {
        let finish;
        const save = vi.fn().mockImplementationOnce(() => new Promise(resolve => finish = resolve)).mockResolvedValue(undefined);
        const state = setup(save);
        const pending = state.form.save();
        state.events.change.call({}, {});
        finish();
        await pending;
        expect(save).toHaveBeenCalledTimes(2);
        expect(state.onSave).toHaveBeenCalledTimes(1);
    });
    it('reports failure and allows a retry', async () => {
        const save = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined);
        const state = setup(save);
        await state.form.save();
        expect(state.onError).toHaveBeenCalledTimes(1);
        await state.form.save();
        expect(state.onSave).toHaveBeenCalledTimes(1);
    });
});
