CloudPebble.Events = (function() {
    var source = null;
    var reconnectTimer = null;
    var RECONNECT_DELAY = 3000;

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

        source.addEventListener('pull_start', handlers.handlePullStart);
        source.addEventListener('pull_complete', handlers.handlePullComplete);
        source.addEventListener('pull_failed', handlers.handlePullFailed);
        source.addEventListener('build_start', handlers.handleBuildStart);
        source.addEventListener('build_complete', handlers.handleBuildComplete);

        source.onerror = function() {
            if (source.readyState === EventSource.CLOSED) {
                if (reconnectTimer) clearTimeout(reconnectTimer);
                reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
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
        },
        handlePullStart: handlers.handlePullStart,
        handlePullComplete: handlers.handlePullComplete,
        handlePullFailed: handlers.handlePullFailed,
        handleBuildStart: handlers.handleBuildStart,
        handleBuildComplete: handlers.handleBuildComplete
    };
})();