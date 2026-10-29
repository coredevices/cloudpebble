import {describe, it, expect} from 'vitest';
import {readFileSync} from 'fs';
const editor = new Function('CloudPebble', readFileSync('permission_editor.js', 'utf8') + '; return CloudPebble.PermissionEditor;')({});
describe('structured permission parameters', () => {
    it('parses domain lists while preserving unrelated imported metadata', () => {
        const original = {name: 'Internet', parameters: {domains: ['old.com'], future: true}, extra: 42};
        expect(editor.withList(original, 'domains', 'api.example.com,\n example.org ')).toEqual({
            name: 'Internet', parameters: {domains: ['api.example.com', 'example.org'], future: true}, extra: 42
        });
        expect(original.parameters.domains).toEqual(['old.com']);
    });
    it('supports unscoped permissions and package lists', () => {
        expect(editor.withList('Notifications', 'packages', 'com.example.app')).toEqual({
            name: 'Notifications', parameters: {packages: ['com.example.app']}
        });
        expect(editor.withList({name: 'Internet', parameters: {domains: ['a.com']}}, 'domains', '')).toEqual({name: 'Internet'});
    });
});
