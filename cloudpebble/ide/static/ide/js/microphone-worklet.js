class MicrophoneCapture extends AudioWorkletProcessor {
    constructor() {
        super();
        this.samples = [];
        this.position = 0;
    }
    process(inputs) {
        const input = inputs[0] && inputs[0][0];
        if (!input) return true;
        // Resample if the browser cannot create a 16 kHz context.
        for (; this.position < input.length; this.position += sampleRate / 16000) {
            this.samples.push(Math.max(-1, Math.min(1, input[Math.floor(this.position)])));
            if (this.samples.length === 320) {
                const buffer = new ArrayBuffer(640), view = new DataView(buffer);
                this.samples.forEach((value, i) => view.setInt16(i * 2, value * 32767, true));
                this.port.postMessage(buffer, [buffer]);
                this.samples = [];
            }
        }
        this.position -= input.length;
        return true;
    }
}
registerProcessor('microphone-capture', MicrophoneCapture);
