import {describe, it, expect} from 'vitest';
import {readFileSync} from 'fs';
const preview = new Function('CloudPebble', readFileSync('plugin_preview.js', 'utf8') + '; return CloudPebble.PluginPreview;')({});

const plugin = {
    script: 'plugin.js',
    sources: [
        {category: 'home', items: ['light', 'room_lights'], properties: {
            name: ['shortText'], on: ['boolean', 'shortText'], brightness: ['numericValue', 'shortText']
        }},
        {category: 'weather', items: ['location'], properties: {
            temperature: ['shortText', 'numericValue'], hourly_temperature: ['series.numericValue', 'series.shortText']
        }}
    ]
};

describe('plugin preview readings', () => {
    it('lists one reading per item and property, without series-only properties', () => {
        const readings = preview.readings(plugin);
        expect(readings.map((r) => r.key)).toEqual([
            'home/light/name', 'home/light/on', 'home/light/brightness',
            'home/room_lights/name', 'home/room_lights/on', 'home/room_lights/brightness',
            'weather/location/temperature'
        ]);
        expect(readings[2]).toEqual({
            key: 'home/light/brightness', category: 'home', item: 'light', property: 'brightness',
            shapes: ['numericValue', 'shortText']
        });
    });

    it('copes with a plugin that declares nothing', () => {
        expect(preview.readings({})).toEqual([]);
        expect(preview.readings(undefined)).toEqual([]);
        expect(preview.readings({sources: [{category: 'demo', items: ['hello']}]})).toEqual([]);
    });

    it('starts with values rather than instance names, up to the slot count', () => {
        expect(preview.defaultSelection(preview.readings(plugin))).toEqual([
            'home/light/on', 'home/light/brightness', 'home/room_lights/on', 'home/room_lights/brightness',
            'weather/location/temperature'
        ]);
        expect(preview.defaultSelection(preview.readings({sources: [
            {category: 'demo', items: ['hello'], properties: {name: ['shortText']}}
        ]}))).toEqual(['demo/hello/name']);
    });

    it('keeps a saved choice, dropping readings the plugin no longer declares', () => {
        const readings = preview.readings(plugin);
        expect(preview.restoreSelection(readings, ['home/light/name', 'gone/away/x'])).toEqual(['home/light/name']);
        expect(preview.restoreSelection(readings, [])).toEqual([]);
        expect(preview.restoreSelection(readings, ['gone/away/x'])).toEqual(preview.defaultSelection(readings));
        expect(preview.restoreSelection(readings, null)).toEqual(preview.defaultSelection(readings));
    });

    it('writes complications as the phone app serves them', () => {
        const chosen = preview.readings(plugin).filter((r) => r.key === 'weather/location/temperature' || r.key === 'home/light/on');
        expect(preview.complicationInstances(chosen)).toEqual([
            {instanceId: '0', properties: {
                category: {shortText: {text: 'home'}}, item: {shortText: {text: 'light'}},
                index: {numericValue: {value: 0}}, property: {shortText: {text: 'on'}}
            }},
            {instanceId: '1', properties: {
                category: {shortText: {text: 'weather'}}, item: {shortText: {text: 'location'}},
                index: {numericValue: {value: 0}}, property: {shortText: {text: 'temperature'}}
            }}
        ]);
    });
});
