/* Audio is sent only after an explicit developer action, never on page load. */
(function() {
    var context = null, stream = null, timer = null, generation = 0;
    function status(text) { $('.mic-status').text(text); }
    function stop() {
        generation++;
        if (timer) clearInterval(timer);
        timer = null;
        if (stream) stream.getTracks().forEach(function(track) { track.stop(); });
        stream = null;
        if (context) context.close();
        context = null;
        status(gettext('Microphone input is off.'));
    }
    $(document).on('click', '[data-mic-action]', function() {
        var action = $(this).data('mic-action');
        if (action === 'stop') { stop(); return; }
        if (!SharedPebble.isVirtual()) { status(gettext('Start an emulator first.')); return; }
        SharedPebble.getPebble().then(function(pebble) {
            if (action === 'plugins') {
                return pebble.simulator_command(0x0d, '\x02').then(function(result) {
                    $('.plugin-list').removeClass('hide').text(result.map(function(plugin) {
                        return plugin.name + ' (' + plugin.kind + ')\n  Sources: ' + (plugin.sources.join(', ') || 'none') + '\n  Actions: ' + (plugin.actions.join(', ') || 'none');
                    }).join('\n\n'));
                });
            }
            if (action === 'grant' || action === 'deny' || action === 'status') {
                var request = {permission: 'WatchMicrophone', uuid: CloudPebble.ProjectInfo.app_uuid};
                if (action !== 'status') request.state = action;
                return pebble.simulator_command(0x0f, request).then(function(result) {
                    if (action === 'deny') stop();
                    status((result.granted ? gettext('Microphone allowed: ') : gettext('Microphone denied: ')) + result.reason);
                });
            }
            stop();
            var current = generation;
            pebble.once('close', stop);
            if (action === 'tone') {
                var phase = 0;
                timer = setInterval(function() {
                    var data = new ArrayBuffer(640), view = new DataView(data);
                    for (var i = 0; i < 320; i++) view.setInt16(i * 2, Math.sin(phase++ * 2 * Math.PI * 440 / 16000) * 8000, true);
                    try { pebble.emu_microphone(data); } catch (e) { stop(); status(e.message); }
                }, 20);
                status(gettext('Sending a 440 Hz test tone. Stop audio when finished.'));
                return;
            }
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error(gettext('Browser microphone access requires HTTPS or localhost.'));
            return navigator.mediaDevices.getUserMedia({audio: true}).then(function(audioStream) {
                if (current !== generation) { audioStream.getTracks().forEach(function(track) { track.stop(); }); return; }
                stream = audioStream;
                context = new AudioContext({sampleRate: 16000});
                var audioContext = context;
                return audioContext.audioWorklet.addModule('/static/ide/js/microphone-worklet.js').then(function() {
                    if (current !== generation) return;
                    var capture = new AudioWorkletNode(audioContext, 'microphone-capture');
                    capture.port.onmessage = function(event) {
                        if (current !== generation) return;
                        try { pebble.emu_microphone(event.data); } catch (e) { stop(); status(e.message); }
                    };
                    audioContext.createMediaStreamSource(stream).connect(capture);
                    capture.connect(audioContext.destination); // worklet output is silent
                    return audioContext.resume().then(function() {
                        if (current === generation) status(gettext('Browser microphone is live. Stop audio to release it.'));
                    });
                });
            }).catch(function(error) {
                // A cancelled permission request must not stop a newer input.
                if (current === generation) throw error;
            });
        }).catch(function(error) { stop(); status(error.message || String(error)); });
    });
    window.addEventListener('pagehide', stop);
})();
