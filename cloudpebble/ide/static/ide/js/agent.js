/**
 * CloudPebble.Agent — the AI chat panel (third column).
 *
 * Lives outside the #main-pane system on purpose: it must stay visible while
 * the user switches between the editor, Build & Run and the emulator.
 */
CloudPebble.Agent = (function() {
    var mSessionID = null;
    var mSource = null;
    var mLastSeq = 0;
    var mRunning = false;
    var mLastMessage = null;
    var mReconnectTimer = null;
    var RECONNECT_DELAY = 3000;
    var MAX_RECONNECT_DELAY = 60000;
    var mReconnectDelay = RECONNECT_DELAY;
    // Which watch the agent has been laying out for, so "Open emulator" starts
    // that one rather than guessing.
    var mEmulatorPlatform = null;
    // Messages typed while a turn is running, sent one at a time as it frees up.
    // Client-side and per session: a queued thought is worth less than the round
    // trip to store it, and losing it on a reload is what the user expects.
    var mQueue = [];
    // Kept in step with FATAL_ERROR_KINDS in ide/api/agent.py.
    var FATAL_ERROR_KINDS = ['relay', 'timeout', 'cancelled', 'usage_limit', 'auth'];

    /* ---------------------------------------------------------------- log */

    function scroll_down() {
        var log = $('#chat-log')[0];
        if (log) log.scrollTop = log.scrollHeight;
    }

    /** Whether the log is close enough to the bottom to be "following". */
    function pinned_to_bottom() {
        var log = $('#chat-log')[0];
        if (!log) return true;
        return log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    }

    function append(el) {
        $('#chat-log').children('.chat-intro').remove();
        // Read the position BEFORE inserting: a turn runs for minutes, and
        // yanking the view back every time an event lands makes it impossible to
        // read a diff or a build log while the agent works.
        var follow = pinned_to_bottom();
        $('#chat-log').append(el);
        if (follow) scroll_down();
        return el;
    }

    function bubble(role, text) {
        return $('<div class="chat-msg">').addClass('chat-msg-' + role).text(text || '');
    }

    /** A card with a clickable header that toggles its body. */
    function card(kind, header_content, body) {
        var header = $('<div class="chat-card-header">').append(header_content);
        var wrapper = $('<div class="chat-card">').addClass('chat-card-' + kind).append(header);
        if (body) {
            body.addClass('chat-card-body').hide();
            wrapper.append(body);
            header.prepend($('<span class="chat-caret">').html('&#9656;'));
            header.click(function(e) {
                if ($(e.target).is('a')) return;
                body.slideToggle(120);
                var caret = header.find('.chat-caret');
                caret.html(caret.html() === '▸' ? '&#9662;' : '&#9656;');
            });
        }
        return wrapper;
    }

    function tool_use_card(d) {
        var body = $('<pre>').text(JSON.stringify(d.args || {}, null, 2));
        return card('tool', $('<span class="chat-tool-name">').text(d.tool || gettext("tool")), body);
    }

    /**
     * The agent cannot open or reboot the emulator -- it belongs to this browser
     * tab -- so the panel does it, automatically, the moment a tool asks for one.
     *
     * A new user does not know that "no emulator is running" means Build & Run ->
     * Emery, and should not have to: both projects in the first end-to-end run
     * built on the first turn and then dead-ended there. So this starts the
     * emulator and tells the agent to carry on, without being asked.
     */
    var EMULATOR_HINTS = ['no emulator is running', 'emulator connection lost',
                          'emulator never came up', 'rejected the install'];

    function needs_emulator(summary) {
        var text = (summary || '').toLowerCase();
        return _.some(EMULATOR_HINTS, function(hint) { return text.indexOf(hint) !== -1; });
    }

    function wants_restart(summary) {
        var text = (summary || '').toLowerCase();
        return text.indexOf('rejected the install') !== -1
            || text.indexOf('connection lost') !== -1
            || text.indexOf('never came up') !== -1;
    }

    function emulator_button(summary) {
        var restart = wants_restart(summary);
        var label = restart ? gettext("Restart emulator") : gettext("Open emulator");
        return $('<button class="btn btn-small chat-emulator-open">').text(label)
            .click(function(e) {
                e.preventDefault();
                var button = $(this).prop('disabled', true).text(gettext("Starting…"));
                open_emulator(restart).then(function() {
                    button.text(gettext("Emulator ready"));
                }).catch(function(err) {
                    button.prop('disabled', false).text(label);
                    append(error_card({message: err && err.message
                        ? err.message : gettext("Could not start the emulator.")}));
                });
            });
    }

    // One automatic attempt per turn. A second failure means starting it did not
    // help, and looping the agent against a broken emulator helps nobody.
    var mAutoEmulatorTried = false;
    // True until the stream's replay of history is done. Old tool failures must
    // not launch an emulator when a tab is merely reloaded.
    var mReplaying = true;

    /**
     * Start the emulator the agent just asked for, then tell it to carry on.
     * Falls back to the button if anything here fails.
     */
    function auto_open_emulator(summary) {
        if (mReplaying || mAutoEmulatorTried) return false;
        mAutoEmulatorTried = true;
        append(bubble('system', wants_restart(summary)
            ? gettext("Restarting the emulator for you…")
            : gettext("Starting the emulator for you…")));
        open_emulator(wants_restart(summary)).then(function() {
            append(bubble('system', gettext("Emulator ready. Carrying on.")));
            // Queued if the turn is still going, sent if it has already given up.
            send(gettext("The emulator is ready now — carry on."));
        }).catch(function(err) {
            append(error_card({message: err && err.message ? err.message
                : gettext("Could not start the emulator automatically.")}));
        });
        return true;
    }

    /**
     * Start (or restart) the emulator by driving the Build & Run pane's own
     * button, so there is exactly one implementation of "run on emery" and this
     * cannot drift from it.
     */
    function open_emulator(restart) {
        try {
            if (restart && SharedPebble.isVirtual()) {
                return Promise.resolve(SharedPebble.reboot());
            }
            CloudPebble.Compile.Show();
            // Which watch to start. The buttons are in DOM order, which begins at
            // Aplite -- a 144x168 black and white screen. Picking that meant a
            // colour watchface got designed and verified on the least capable
            // watch the project targets. Prefer the one the agent is already
            // laying out for, then the richest screen available.
            var order = [mEmulatorPlatform, 'emery', 'gabbro', 'basalt', 'chalk',
                         'flint', 'diorite', 'aplite'];
            var button = null;
            _.each(order, function(platform) {
                if (button || !platform) return;
                var candidate = $('#install-in-qemu-' + platform + '-btn:visible');
                if (candidate.length) button = candidate;
            });
            if (!button) button = $('[id^=install-in-qemu-][id$=-btn]:visible').first();
            if (!button.length) {
                return Promise.reject(new Error(gettext(
                    "Build the project first, then the emulator buttons appear in Build & Run.")));
            }
            button.click();
            return Promise.resolve();
        } catch (e) {
            return Promise.reject(e);
        }
    }

    function tool_result_card(d) {
        var head = $('<span>')
            .append($('<span class="chat-status">').addClass(d.ok ? 'chat-ok' : 'chat-fail').text(d.ok ? '✓' : '✗'))
            .append($('<span class="chat-tool-name">').text(d.tool || ''))
            .append($('<span class="chat-summary">').text(d.summary || ''));
        var el = card('result', head, null);
        if (d.image_png_b64) {
            el.append($('<img class="chat-shot">').attr('src', 'data:image/png;base64,' + d.image_png_b64));
        }
        if (!d.ok && needs_emulator(d.summary) && !auto_open_emulator(d.summary)) {
            // Already tried once this turn; leave it to the user.
            el.append($('<div class="chat-card-action">').append(emulator_button(d.summary)));
        }
        return el;
    }

    function diff_body(diff) {
        var pre = $('<pre class="chat-diff">');
        _.each((diff || '').split('\n'), function(line) {
            var cls = '';
            if (line.charAt(0) === '+' && line.substr(0, 3) !== '+++') cls = 'chat-diff-add';
            else if (line.charAt(0) === '-' && line.substr(0, 3) !== '---') cls = 'chat-diff-del';
            else if (line.charAt(0) === '@') cls = 'chat-diff-hunk';
            pre.append($('<div>').addClass(cls).text(line));
        });
        return pre;
    }

    function file_edit_card(d) {
        var link = $('<a href="#">').text(d.path || gettext("file")).click(function(e) {
            e.preventDefault();
            open_file(d.file_id);
        });
        return card('file', link, diff_body(d.diff));
    }

    function build_chip(d) {
        var chip = $('<div class="chat-chip">').addClass('chat-build-' + (d.state || 'pending'));
        chip.append($('<a href="#">').text(interpolate(gettext("Build %s"), [d.state || ''])).click(function(e) {
            e.preventDefault();
            CloudPebble.Compile.Show();
        }));
        return chip;
    }

    function error_card(d) {
        var el = $('<div class="chat-error">').text(d.message || gettext("Something went wrong."));
        // Captured now: by the time this card is clicked -- or replayed on a
        // reload five turns later -- mLastMessage is somebody else's instruction.
        var failed_message = mLastMessage;
        if (failed_message && !mRunning) {
            el.append(' ').append($('<a href="#">').text(gettext("Retry")).click(function(e) {
                e.preventDefault();
                el.remove();
                send(failed_message);
            }));
        }
        return el;
    }

    /**
     * Pull the IDE back in step with what the agent just did to the project.
     *
     * Without this the user watches main.c being rewritten in the chat while
     * their editor shows the old text, and their next save is rejected as "this
     * file has been modified since you last saved it". New files never appear in
     * the sidebar, deleted ones never leave, and new resources are invisible.
     *
     * Debounced because a turn writes several files in a row and each refresh is
     * a full project/info fetch plus a sidebar rebuild. Sidebar.Refresh already
     * reloads the open buffer, and only when it is clean -- an edit in progress
     * is never clobbered.
     */
    var mRefreshTimer = null;
    var REFRESH_DELAY = 400;

    function refresh_project() {
        if (mRefreshTimer) clearTimeout(mRefreshTimer);
        mRefreshTimer = setTimeout(function() {
            mRefreshTimer = null;
            if (CloudPebble.Sidebar && _.isFunction(CloudPebble.Sidebar.Refresh)) {
                CloudPebble.Sidebar.Refresh();
            }
        }, REFRESH_DELAY);
    }

    /**
     * Open a file the agent touched in the real editor pane. If the sidebar
     * doesn't know about it yet (the agent just created it), refresh and retry.
     */
    function open_file(file_id) {
        if (!file_id) return;
        CloudPebble.Editor.GoTo({id: file_id}, 0, 0).catch(function() {
            CloudPebble.Sidebar.Refresh();
        });
    }

    /* ------------------------------------------------------------ events */

    function render(evt) {
        if (evt.seq) {
            // The stream replays from ?since=, and EventSource retries on its
            // own with a stale URL — seq dedupe makes both harmless.
            if (evt.seq <= mLastSeq) return;
            mLastSeq = evt.seq;
        }
        var d = evt.data || {};
        switch (evt.type) {
            case 'text':
                append(bubble(evt.role || 'assistant', d.text));
                break;
            case 'tool_use':
                append(tool_use_card(d));
                set_thinking_activity(interpolate(gettext("Running %s…"), [d.tool || '']));
                break;
            case 'tool_result':
                append(tool_result_card(d));
                // Otherwise the spinner keeps naming a tool that finished a
                // minute ago; render_thinking falls back to "Working…".
                set_thinking_activity('');
                break;
            case 'file_edit':
                append(file_edit_card(d));
                refresh_project();
                break;
            case 'project_changed':
                // A file or resource the agent changed without producing a diff:
                // a delete, an uploaded image, a settings write. Nothing to show
                // in the log, but the IDE is now out of date.
                refresh_project();
                break;
            case 'build':
                append(build_chip(d));
                break;
            case 'error':
                // Non-fatal kinds (a transcript mirror hiccup, a recoverable
                // assistant error) are reported but the turn carries on — same
                // list the relay uses to decide whether to stop.
                if (FATAL_ERROR_KINDS.indexOf(d.kind) !== -1) set_running(false);
                if (d.kind === 'cancelled') {
                    // The user did this on purpose. A red box offering to retry
                    // the turn they just abandoned is the wrong shape, and it
                    // replays on every reload.
                    append(bubble('system', d.message || gettext("Stopped.")));
                } else if (d.kind === 'auth') {
                    // Retrying cannot help until the credential is replaced.
                    append(reauth_notice(d));
                    load_credential();
                } else {
                    append(error_card(d));
                }
                break;
            case 'done':
                set_running(false);
                // Only a real completion releases the queue. Draining on any
                // transition to idle meant Stop launched the next queued message,
                // and an expired key burned the whole queue against the same wall.
                drain_queue();
                break;
            case 'sync':
                // Sent once per stream, after the replay: the server's own view of
                // whether a turn is running. It arrives last on purpose, so a
                // terminal event from an OLD turn cannot leave a reloaded tab
                // thinking the agent is idle when it is not. It also marks the end
                // of the replay, after which events are live and worth acting on.
                mReplaying = false;
                set_running(d.status === 'running');
                break;
            default:
                if (d.text) append(bubble('system', d.text));
        }
    }

    /* ------------------------------------------------------------ stream */

    function connect() {
        if (mSource) mSource.close();
        mReplaying = true;
        mSource = new EventSource('/ide/project/' + PROJECT_ID + '/agent/stream?since=' + mLastSeq);
        mSource.onmessage = function(e) {
            try {
                render(JSON.parse(e.data));
            } catch (err) {
                console.warn('agent: bad SSE payload', err);
            }
        };
        mSource.onopen = function() {
            mReconnectDelay = RECONNECT_DELAY;
        };
        mSource.onerror = function() {
            if (mSource.readyState !== EventSource.CLOSED) return;
            if (mReconnectTimer) clearTimeout(mReconnectTimer);
            // Backs off like sse.js: a tab left open against a dead server should
            // not spend the night issuing twenty requests a minute.
            mReconnectTimer = setTimeout(connect, mReconnectDelay);
            mReconnectDelay = Math.min(mReconnectDelay * 2, MAX_RECONNECT_DELAY);
        };
    }

    /* ------------------------------------------------------------ turns */

    /**
     * The emulator the user is currently watching, if there is one. Never
     * launches one — a turn with no emulator is build-only, which is fine.
     *
     * Only the uuid and the token: the server builds the websocket URL from
     * QEMU_PUBLIC_URL, because the agent VM dials whatever it is handed.
     * ponytail: window.emu is the only public handle SharedPebble exposes;
     * swap for a real accessor if pebble.js ever grows one.
     */
    function live_emulator() {
        if (!SharedPebble.isVirtual() || !window.emu) return null;
        try {
            var uuid = window.emu.getUUID();
            var token = window.emu.getToken();
            // The platform is what the agent lays out for: a watchface designed
            // for 144x168 is cropped on the 200x228 emery the user is watching.
            if (!uuid || !token) return null;
            mEmulatorPlatform = SharedPebble.getPlatformName();
            return {uuid: uuid, token: token, platform: mEmulatorPlatform};
        } catch (e) {
            return null;
        }
    }

    // A turn runs anywhere from 40s to several minutes, and there is a long
    // silent gap between the user's message and the first tool card. A static
    // "Working…" through that reads as a hang, so show elapsed time and
    // whatever the agent is currently doing.
    var mThinkingTimer = null;
    var mThinkingStart = 0;
    var mThinkingWhat = '';

    var SPINNER = ['✳', '✵', '✶', '✷', '✸', '✷', '✶', '✵'];
    var mSpinnerFrame = 0;

    function render_thinking() {
        var secs = Math.round((Date.now() - mThinkingStart) / 1000);
        var clock = secs < 60 ? secs + 's'
            : Math.floor(secs / 60) + 'm ' + (secs % 60) + 's';
        mSpinnerFrame = (mSpinnerFrame + 1) % SPINNER.length;
        var el = $('#chat-thinking').empty();
        el.append($('<span class="chat-spinner">').text(SPINNER[mSpinnerFrame]));
        el.append($('<span class="chat-thinking-what">')
            .text(mThinkingWhat || gettext("Working…")));
        el.append($('<span class="chat-thinking-time">').text(clock));
    }

    function set_thinking_activity(what) {
        mThinkingWhat = what || '';
        if (mRunning) render_thinking();
    }

    /**
     * Messages waiting for the current turn to finish. Rendered above the
     * composer, each removable, and drained one at a time -- the server refuses
     * a second concurrent turn, and queueing beats making the user sit and watch
     * for the moment it frees up.
     */
    function render_queue() {
        var list = $('#chat-queue').empty();
        if (!mQueue.length) return list.hide();
        _.each(mQueue, function(text, i) {
            var row = $('<div class="chat-queued">');
            row.append($('<a href="#" class="chat-queued-drop" title="'
                         + gettext("Remove from queue") + '">').text('✗')
                .click(function(e) {
                    e.preventDefault();
                    mQueue.splice(i, 1);
                    render_queue();
                }));
            row.append($('<span class="chat-queued-text">').text(text));
            list.append(row);
        });
        list.show();
    }

    /** Send the next queued message, if the agent is free to take it. */
    function drain_queue() {
        if (mRunning || !mQueue.length) return;
        var next = mQueue.shift();
        render_queue();
        send(next);
    }

    function set_running(running) {
        var was_running = mRunning;
        mRunning = running;
        // The composer stays live while the agent works: the whole point of
        // stopping is usually to say something else, and making people wait for
        // the turn to end before they can even type it is the slow way round.
        //
        // Send stays visible while running -- it queues. Hiding it left Enter as
        // the only way to reach the queue, which nothing advertises, and clicking
        // where Send used to be did nothing at all.
        $('#chat-send').text(running ? gettext("Queue") : gettext("Send"));
        $('#chat-stop').toggle(running);
        $('#chat-thinking').toggle(running);

        if (running && !was_running) {
            mThinkingStart = Date.now();
            mThinkingWhat = '';
            render_thinking();
            mThinkingTimer = setInterval(render_thinking, 1000);
        } else if (!running && mThinkingTimer) {
            clearInterval(mThinkingTimer);
            mThinkingTimer = null;
            mThinkingWhat = '';
        }
        // Only when a turn hands control back — replaying history on page load
        // ends with a 'done' too, and that must not steal focus from the editor.
        // Focus belongs to the chat only if the user was not typing elsewhere:
        // a turn ending while they type in CodeMirror must not swallow the rest
        // of the line. Body counts as ours -- clicking Send hides the button,
        // which blurs it.
        if (was_running && !running) {
            var active = document.activeElement;
            if (!active || active === document.body
                || $(active).closest('#chat-wrapper').length) {
                $('#chat-input').focus();
            }
        }
    }

    // ---- model settings -------------------------------------------------
    //
    // The secret is write-only: it is posted once and never comes back, so the
    // field always starts empty and a blank value on save means "leave it".

    var mCredential = null;
    // Whether this deployment can do Anthropic sign-in in the browser. Off unless
    // the server has a client_id configured, in which case we fall back to
    // telling the user to run `claude setup-token`.
    var mAnthropicOAuth = false;

    // Anthropic serves a known, short list, so offer it rather than making
    // people remember model ids. OpenRouter's catalogue is far too large and
    // changes constantly, so that stays free text.
    var ANTHROPIC_MODELS = [
        {id: '', name: gettext("Default (Sonnet 5)")},
        {id: 'claude-opus-5', name: 'Opus 5 — most capable'},
        {id: 'claude-sonnet-5', name: 'Sonnet 5 — balanced'},
        {id: 'claude-fable-5', name: 'Fable 5'},
        {id: 'claude-haiku-4-5-20251001', name: 'Haiku 4.5 — fastest'}
    ];

    function render_model_field(provider, current) {
        var select = $('#chat-model-select'), text = $('#chat-model-name');
        if (provider === 'anthropic') {
            select.empty();
            _.each(ANTHROPIC_MODELS, function(m) {
                select.append($('<option>').attr('value', m.id).text(m.name));
            });
            select.val(_.some(ANTHROPIC_MODELS, function(m) { return m.id === current; })
                       ? current : '');
            select.show();
            text.hide();
            $('#chat-model-hint').text(gettext("Pick the model your Claude plan or key covers."));
        } else {
            select.hide();
            text.show().val(current || '');
            $('#chat-model-hint').text(gettext(
                "Leave blank for the default. On OpenRouter use the full string, e.g. openai/gpt-5.2."));
        }
    }

    /** Whichever field is in play for the current provider. */
    function chosen_model() {
        return $('#chat-provider').val() === 'anthropic'
            ? $('#chat-model-select').val()
            : $('#chat-model-name').val().trim();
    }

    function provider_label(state) {
        if (!state) return gettext("Model");
        if (state.provider === 'free') return gettext("Free model");
        return state.model || state.provider;
    }

    function render_credential(state) {
        mCredential = state;
        if (state && typeof state.anthropic_oauth !== 'undefined') {
            mAnthropicOAuth = !!state.anthropic_oauth;
        }
        $('#chat-model').text(provider_label(state))
            .toggleClass('chat-model-broken', !!(state && state.needs_reauth));
        $('#chat-settings-status').text(state && state.description ? state.description : '');
    }

    /** A dead key is the user's to fix, so say so and open the panel for them. */
    function reauth_notice(d) {
        var el = $('<div class="chat-error">').text(
            d.message || gettext("Your model credentials are not working."));
        el.append(' ').append($('<a href="#">').text(gettext("Update credentials"))
            .click(function(e) {
                e.preventDefault();
                load_credential().then(open_settings);
            }));
        return el;
    }

    /**
     * Getting a key is the step people get stuck on, so spell it out per
     * provider rather than assuming they know where to look.
     */
    function credential_steps(provider, kind) {
        if (provider === 'anthropic' && kind === 'oauth') {
            if (mAnthropicOAuth) {
                // No terminal needed, which is the point: this works on a phone.
                return [
                    {text: gettext("Click Sign in. Anthropic opens in a new tab."),
                     anthropic_connect: true},
                    {text: gettext("Approve access, then copy the code it shows you.")},
                    {text: gettext("Paste that code below and save.")}
                ];
            }
            return [
                {text: gettext("Run this in a terminal on your own machine:"),
                 command: 'claude setup-token'},
                {text: gettext("Sign in when it opens your browser, then approve access.")},
                {text: gettext("It prints a token starting sk-ant-oat01-. Copy it.")},
                {text: gettext("Paste it below. Turns then run on your Claude plan.")}
            ];
        }
        if (provider === 'anthropic') {
            return [
                {text: gettext("Open the Anthropic console API keys page."),
                 link: 'https://platform.claude.com/settings/keys',
                 link_text: gettext("Open console")},
                {text: gettext("Create a key and copy it. It starts sk-ant-.")},
                {text: gettext("Paste it below. Usage is billed to that account.")}
            ];
        }
        if (provider === 'openrouter') {
            // OpenRouter supports OAuth, so connecting is one click and the key
            // never passes through the browser. Pasting stays available for
            // anyone who would rather use an existing key.
            return [
                {text: gettext("Click Connect. OpenRouter opens in a new tab."),
                 connect: true},
                {text: gettext("Sign in there and authorise CloudPebble.")},
                {text: gettext("You come straight back, connected. Then name any model it serves.")},
                {text: gettext("Prefer an existing key? Paste it below instead.")}
            ];
        }
        return [];
    }

    function render_steps(provider, kind) {
        var list = $('#chat-steps').empty();
        var steps = credential_steps(provider, kind);
        if (!steps.length) return list.hide();
        _.each(steps, function(step) {
            var li = $('<li>').text(step.text);
            if (step.link) {
                li.append(' ').append($('<a target="_blank" rel="noopener">')
                    .attr('href', step.link).text(step.link_text || step.link));
            }
            if (step.anthropic_connect) {
                li.append(' ').append($('<button class="btn btn-primary btn-small chat-connect">')
                    .text(gettext("Sign in with Anthropic"))
                    .click(function(e) {
                        e.preventDefault();
                        var status = $('#chat-settings-status');
                        Ajax.Post('/ide/agent/anthropic/start').then(function(data) {
                            window.open(data.url, '_blank', 'noopener');
                            status.text(gettext("Approve access, then paste the code below."));
                        }).catch(function(err) { status.text(err.message); });
                    }));
            }
            if (step.connect) {
                li.append(' ').append($('<button class="btn btn-primary btn-small chat-connect">')
                    .text(gettext("Connect OpenRouter"))
                    .click(function(e) {
                        e.preventDefault();
                        connect_openrouter($(this));
                    }));
            }
            if (step.command) {
                // One click to copy: retyping a command is where people slip.
                var code = $('<code class="chat-copy">').text(step.command)
                    .attr('title', gettext("Click to copy"))
                    .click(function() {
                        var self = $(this);
                        navigator.clipboard.writeText(step.command).then(function() {
                            var was = self.text();
                            self.text(gettext("copied!"));
                            setTimeout(function() { self.text(was); }, 1200);
                        });
                    });
                li.append($('<div class="chat-command">').append(code));
            }
            list.append(li);
        });
        list.show();
    }

    /**
     * OAuth PKCE: the server mints the URL and keeps the verifier, so the key is
     * exchanged server-side and never reaches this page.
     */
    function connect_openrouter(button) {
        var status = $('#chat-settings-status');
        status.text(gettext("Opening OpenRouter…"));
        // The button stays live on purpose. Nothing tells us the user closed the
        // auth tab, so disabling it until a callback that may never come left
        // Connect permanently dead; the pop-up has a fixed window name, so a
        // second click reuses the same window rather than stacking them.
        Ajax.Post('/ide/agent/openrouter/start').then(function(data) {
            var popup = window.open(data.url, 'cloudpebble-openrouter',
                                    'width=560,height=760');
            if (!popup) {
                status.text(gettext("Allow pop-ups for this site, then try again."));
                return;
            }
            status.text(gettext("Waiting for you to authorise in the other tab…"));
        }).catch(function(err) {
            status.text(err.message);
        });
    }

    // The callback tab tells us when it is done; re-read state rather than
    // trusting the message, which is only a nudge to refresh.
    $(window).on('message', function(e) {
        if (!e.originalEvent || e.originalEvent.origin !== window.location.origin) return;
        var d = e.originalEvent.data;
        if (!d || d.source !== 'cloudpebble-agent-oauth') return;
        load_credential().then(function() {
            $('#chat-settings-status').text(
                d.ok ? gettext("OpenRouter connected.")
                     : gettext("OpenRouter sign-in did not complete."));
            if (d.ok) close_settings();
        });
    });

    function sync_settings_fields() {
        var provider = $('#chat-provider').val();
        var anthropic = (provider === 'anthropic');
        $('#chat-kind-row').toggle(anthropic);
        $('#chat-secret-row').toggle(!!provider);
        $('#chat-model-row').toggle(!!provider);
        if (!anthropic) $('#chat-secret-kind').val('api_key');
        render_model_field(provider, chosen_model());
        render_steps(provider, $('#chat-secret-kind').val());
    }

    function open_settings() {
        $('#chat-provider').val(mCredential && mCredential.configured ? mCredential.provider : '');
        render_model_field($('#chat-provider').val(),
                           mCredential && mCredential.configured ? (mCredential.model || '') : '');
        // Browser sign-in is the path we want people on when it is available,
        // so it is the default rather than something to go looking for.
        $('#chat-secret-kind').val(
            (mCredential && mCredential.configured && mCredential.secret_kind)
            || (mAnthropicOAuth ? 'oauth' : 'api_key'));
        $('#chat-secret').val('').attr('placeholder',
            mCredential && mCredential.masked_secret
                ? interpolate(gettext("saved: %s — leave blank to keep"), [mCredential.masked_secret])
                : 'sk-…');
        sync_settings_fields();
        $('#chat-settings').show();
        $('#chat-log').hide();
    }

    function close_settings() {
        $('#chat-settings').hide();
        $('#chat-log').show();
    }

    function save_settings() {
        var provider = $('#chat-provider').val();
        var status = $('#chat-settings-status');
        if (!provider) {
            // Dropping their credential is what selects the free tier -- but only
            // when we actually know they have one. A failed GET /credentials
            // leaves the panel showing "Free shared model", and saving that would
            // delete a key the user never chose to remove.
            if (!mCredential) {
                status.text(gettext("Could not load your model settings. Reload and try again."));
                return;
            }
            return Ajax.Post('/ide/agent/credentials/delete').then(function(state) {
                render_credential(state);
                close_settings();
            }).catch(function(err) { status.text(err.message); });
        }
        // Already signed in and only the model changed: no new code to exchange,
        // so fall through to the ordinary save, which keeps the stored token.
        var signed_in = !!(mCredential && mCredential.configured
                           && mCredential.provider === provider
                           && mCredential.secret_kind === $('#chat-secret-kind').val());
        // In Anthropic OAuth mode the field holds a one-time code, not a token,
        // so it goes to the exchange endpoint instead of being stored directly.
        if (provider === 'anthropic' && mAnthropicOAuth
            && $('#chat-secret-kind').val() === 'oauth'
            && !(signed_in && !$('#chat-secret').val().trim())) {
            var code = $('#chat-secret').val().trim();
            if (!code) { status.text(gettext("Paste the code from Anthropic.")); return; }
            status.text(gettext("Exchanging code…"));
            return Ajax.Post('/ide/agent/anthropic/finish', {
                code: code, model: chosen_model()
            }).then(function(state) {
                render_credential(state);
                close_settings();
            }).catch(function(err) { status.text(err.message); });
        }

        var secret = $('#chat-secret').val().trim();
        if (!secret && !signed_in) {
            status.text(gettext("Enter your key or token."));
            return;
        }
        status.text(gettext("Saving…"));
        return Ajax.Post('/ide/agent/credentials/save', {
            provider: provider,
            secret: secret || '',
            secret_kind: $('#chat-secret-kind').val(),
            model: chosen_model()
        }).then(function(state) {
            render_credential(state);
            close_settings();
        }).catch(function(err) { status.text(err.message); });
    }

    function load_credential() {
        return Ajax.Get('/ide/agent/credentials').then(render_credential).catch(function() {
            $('#chat-model').text(gettext("Model"));
        });
    }

    function start_session() {
        if (mSessionID) return Promise.resolve(mSessionID);
        return Ajax.Post('/ide/project/' + PROJECT_ID + '/agent/start').then(function(data) {
            mSessionID = data.session_id;
            // A turn already running on the server (we reloaded mid-turn) keeps the
            // composer disabled until its terminal event arrives on the stream.
            if (data.status === 'running') set_running(true);
            connect();
            return mSessionID;
        });
    }

    function send(text) {
        if (!text) return;
        // Mid-turn, a message queues rather than interrupting: the thought is
        // usually "and then do this", not "stop". Stop is its own button for
        // when it really is the other thing.
        if (mRunning) {
            mQueue.push(text);
            render_queue();
            return;
        }
        mLastMessage = text;
        mAutoEmulatorTried = false;
        set_running(true);
        // No local echo: the user's own message comes back down the stream like
        // everything else, so history and live view are rendered by one path.
        var payload = {message: text};
        var emulator = live_emulator();
        if (emulator) payload.emulator = JSON.stringify(emulator);
        return start_session().then(function() {
            return Ajax.Post('/ide/project/' + PROJECT_ID + '/agent/message', payload);
        }).catch(function(err) {
            append(error_card({message: err.message}));
            // Not set_running(false): "the agent is already working" means a turn
            // IS running, and guessing idle here is what left the panel with no
            // spinner and no Stop button while the agent worked.
            resync();
        });
    }

    /** Ask the server what is actually happening. It is the only authority. */
    function resync() {
        return Ajax.Post('/ide/project/' + PROJECT_ID + '/agent/start')
            .then(function(data) {
                mSessionID = data.session_id;
                set_running(data.status === 'running');
            })
            .catch(function() { /* the stream's own sync will correct this */ });
    }

    function cancel() {
        return Ajax.Post('/ide/project/' + PROJECT_ID + '/agent/cancel').catch(function(err) {
            console.warn('agent: cancel failed', err);
        }).finally(function() {
            set_running(false);
        });
    }

    /* ------------------------------------------------------------ layout */

    function set_collapsed(collapsed) {
        $('body').toggleClass('chat-collapsed', collapsed);
        $('#chat-collapse').html(collapsed ? '&#9656;' : '&#9666;');
        localStorage['agentChatCollapsed'] = collapsed ? '1' : '';
    }

    /**
     * What an empty panel says. A new user opening a project sees a text box and
     * nothing else: no idea what this thing can do, how much to ask for, or that
     * it will build and run the result for them. These are the three shapes that
     * actually worked in testing -- a look, a mechanism, an app.
     */
    var EXAMPLES = [
        gettext("Make a minimal watchface: big time, day and date, dark background."),
        gettext("Build a watchface with an animation every time the minute changes."),
        gettext("Make an app that fetches something from a free web API and shows it.")
    ];

    function render_intro() {
        if ($('#chat-log').children().length) return;
        var intro = $('<div class="chat-intro">');
        intro.append($('<p>').text(gettext(
            "Describe what you want and I will write it, build it, install it on the emulator and show you a screenshot.")));
        intro.append($('<p class="chat-intro-label">').text(gettext("For example:")));
        _.each(EXAMPLES, function(text) {
            intro.append($('<a href="#" class="chat-example">').text(text)
                .click(function(e) {
                    e.preventDefault();
                    $('#chat-input').val(text).focus();
                }));
        });
        $('#chat-log').append(intro);
    }

    function init() {
        if (!$('#chat-wrapper').length) return;
        $('body').addClass('with-chat');
        set_collapsed(!!localStorage['agentChatCollapsed']);

        $('#chat-collapse, #chat-rail').click(function(e) {
            e.preventDefault();
            set_collapsed(!$('body').hasClass('chat-collapsed'));
        });

        $('#chat-send').click(function(e) {
            e.preventDefault();
            var input = $('#chat-input');
            send($.trim(input.val()));
            input.val('');
        });

        $('#chat-input').keydown(function(e) {
            // 229 and isComposing mean an IME is mid-word: Enter is accepting a
            // candidate, not sending a half-composed message.
            if (e.keyCode === 229 || (e.originalEvent && e.originalEvent.isComposing)) return;
            if (e.keyCode === 13 && !e.shiftKey) {
                e.preventDefault();
                var input = $('#chat-input');
                send($.trim(input.val()));
                input.val('');
            }
        });

        $('#chat-model').click(function(e) { e.preventDefault(); open_settings(); });
        $('#chat-settings-cancel').click(function(e) { e.preventDefault(); close_settings(); });
        $('#chat-settings-save').click(function(e) { e.preventDefault(); save_settings(); });
        $('#chat-provider').change(function() {
            // Picking Anthropic lands on browser sign-in unless the user already
            // stored an API key for it: that is the path we want them on, and
            // sync_settings_fields alone cannot tell a provider switch from a
            // redraw.
            if ($(this).val() === 'anthropic') {
                var stored = (mCredential && mCredential.configured
                              && mCredential.provider === 'anthropic'
                              && mCredential.secret_kind);
                $('#chat-secret-kind').val(stored || (mAnthropicOAuth ? 'oauth' : 'api_key'));
            }
            sync_settings_fields();
        });
        $('#chat-secret-kind').change(sync_settings_fields);
        load_credential();

        $('#chat-stop').click(function(e) {
            e.preventDefault();
            cancel();
        });

        set_running(false);
        render_intro();
        // Attach to the project's session now rather than on first send, so a reload
        // mid-turn keeps streaming and the log replays from the start.
        start_session().catch(function(err) {
            console.warn('agent: could not open the chat session', err);
        });
    }

    return {
        Init: function() {
            init();
        },
        Send: function(text) {
            return send(text);
        },
        Cancel: function() {
            cancel();
        },
        // Seams for the panel's tests: the running/idle state and the queue are
        // what decide whether it is usable mid-turn, and both are otherwise only
        // observable through the DOM.
        Render: function(evt) {
            render(evt);
        },
        Queue: function() {
            return mQueue.slice();
        },
        Running: function() {
            return mRunning;
        }
    };
})();

$(function() {
    CloudPebble.Agent.Init();
});
