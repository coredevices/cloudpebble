import {describe, it, expect} from 'vitest';
import {readFileSync} from 'fs';
import {resolve} from 'path';

function capture(rate) {
    let Processor;
    const packets = [];
    class Base { constructor() { this.port = {postMessage: data => packets.push(data)}; } }
    new Function('AudioWorkletProcessor', 'sampleRate', 'registerProcessor',
        readFileSync(resolve('microphone-worklet.js'), 'utf8'))(Base, rate, (_, value) => Processor = value);
    return {processor: new Processor(), packets};
}

describe('browser microphone PCM framing', () => {
    it('batches 20 ms frames, clamps amplitude and emits little-endian PCM', () => {
        const {processor, packets} = capture(16000);
        processor.process([[new Float32Array(128).fill(2)]]);
        expect(packets).toHaveLength(0);
        processor.process([[new Float32Array(192).fill(-2)]]);
        expect(packets).toHaveLength(1);
        const view = new DataView(packets[0]);
        expect(view.byteLength).toBe(640);
        expect(view.getInt16(0, true)).toBe(32767);
        expect(view.getInt16(256, true)).toBe(-32767);
    });
    it('preserves sample timing across 48 kHz render blocks', () => {
        const {processor, packets} = capture(48000);
        for (let i = 0; i < 15; i++) processor.process([[new Float32Array(128).fill(0.25)]]);
        expect(packets).toHaveLength(2);
        expect(new DataView(packets[1]).getInt16(638, true)).toBe(8191);
    });
    it('waits safely when the browser has no audio input', () => {
        const {processor, packets} = capture(16000);
        expect(processor.process([])).toBe(true);
        expect(packets).toHaveLength(0);
    });
});
