CloudPebble.Events = (function() {
    var source = null;
    var reconnectTimer = null;
    var RECONNECT_DELAY = 3000;

    var connect = function() {
        if (source) {
            source.close();
        }

        source = new EventSource('/ide/project/' + PROJECT_ID + '/events');

        source.addEventListener('pull_start', function() {
            CloudPebble.Sidebar.SetIcon('github', 'refresh');
            CloudPebble.GitHub.OnPullStart();
        });

        source.addEventListener('pull_complete', function(e) {
            CloudPebble.Sidebar.ClearIcon('github');
            CloudPebble.GitHub.OnPullComplete(JSON.parse(e.data));
        });

        source.addEventListener('pull_failed', function() {
            CloudPebble.Sidebar.ClearIcon('github');
            CloudPebble.GitHub.OnPullFailed();
        });

        source.addEventListener('build_start', function(e) {
            var data = JSON.parse(e.data);
            CloudPebble.Sidebar.SetIcon('compile', 'refresh');
            CloudPebble.Compile.OnBuildStart(data.build_id);
        });

        source.addEventListener('build_complete', function(e) {
            var data = JSON.parse(e.data);
            CloudPebble.Sidebar.ClearIcon('compile');
            CloudPebble.Compile.OnBuildComplete(data.build_id, data.state);
        });

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
        }
    };
})();