CloudPebble.Events = (function() {
    var source = null;
    var reconnectTimer = null;
    var RECONNECT_DELAY = 3000;
    var MAX_RECONNECT_DELAY = 60000;
    var reconnectDelay = RECONNECT_DELAY;

    var handlers = {
        handlePullStart: function() {
            CloudPebble.Sidebar.ShowPending('github', 'Pulling');
            CloudPebble.GitHub.OnPullStart();
        },
        handlePullComplete: function(e) {
            CloudPebble.Sidebar.HidePending('github');
            CloudPebble.GitHub.OnPullComplete(JSON.parse(e.data));
        },
        handlePullFailed: function() {
            CloudPebble.Sidebar.HidePending('github');
            CloudPebble.GitHub.OnPullFailed();
        },
        handleBuildStart: function(e) {
            var data = JSON.parse(e.data);
            CloudPebble.Sidebar.ShowPending('compile', 'Building');
            CloudPebble.Compile.OnBuildStart(data.build_id);
        },
        handleBuildComplete: function(e) {
            var data = JSON.parse(e.data);
            CloudPebble.Sidebar.HidePending('compile');
            CloudPebble.Compile.OnBuildComplete(data.build_id, data.state);
        }
    };

    var connect = function() {
        if (source) {
            source.close();
        }

        source = new EventSource('/ide/project/' + PROJECT_ID + '/events');

        // A successful connection resets the backoff so genuine transient
        // blips recover quickly.
        source.onopen = function() {
            reconnectDelay = RECONNECT_DELAY;
        };

        source.addEventListener('pull_start', handlers.handlePullStart);
        source.addEventListener('pull_complete', handlers.handlePullComplete);
        source.addEventListener('pull_failed', handlers.handlePullFailed);
        source.addEventListener('build_start', handlers.handleBuildStart);
        source.addEventListener('build_complete', handlers.handleBuildComplete);

        source.onerror = function() {
            if (source.readyState === EventSource.CLOSED) {
                if (reconnectTimer) clearTimeout(reconnectTimer);
                // Exponential backoff (capped). A permanently-failing endpoint
                // — e.g. a tab left open on a deleted project — backs off to one
                // retry per minute instead of hammering every 3s, while a real
                // outage still self-heals once onopen resets the delay.
                reconnectTimer = setTimeout(connect, reconnectDelay);
                reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
            }
        };
    };

    return {
        Init: function() {
            connect();
        },
        Close: function() {
            if (reconnectTimer) clearTimeout(reconnectTimer);
            if (source) source.close();
            source = null;
            reconnectDelay = RECONNECT_DELAY;
        },
        handlePullStart: handlers.handlePullStart,
        handlePullComplete: handlers.handlePullComplete,
        handlePullFailed: handlers.handlePullFailed,
        handleBuildStart: handlers.handleBuildStart,
        handleBuildComplete: handlers.handleBuildComplete
    };
})();