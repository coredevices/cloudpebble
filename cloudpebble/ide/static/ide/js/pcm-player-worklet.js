/**
 * AudioWorklet processor for the WebSocket audio fallback path.
 *
 * Receives Float32Array chunks of mono samples via port.postMessage and
 * plays them through the audio output. Loaded by qemu.js's
 * setupAudioWebSocket() when WebRTC ICE fails to establish a direct path.
 */
class PCMPlayer extends AudioWorkletProcessor {
    constructor() {
        super();
        this.queue = [];
        this.port.onmessage = (e) => {
            this.queue.push(e.data);
        };
    }

    process(inputs, outputs) {
        const out = outputs[0][0];
        let i = 0;
        while (i < out.length && this.queue.length > 0) {
            const head = this.queue[0];
            const take = Math.min(head.length, out.length - i);
            for (let j = 0; j < take; j++) {
                out[i + j] = head[j];
            }
            i += take;
            if (take === head.length) {
                this.queue.shift();
            } else {
                this.queue[0] = head.subarray(take);
            }
        }
        while (i < out.length) {
            out[i++] = 0;
        }
        return true;
    }
}

registerProcessor('pcm-player', PCMPlayer);
