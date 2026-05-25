export function handlePullStart(CloudPebble) {
    CloudPebble.Sidebar.SetIcon('github', 'refresh');
    CloudPebble.GitHub.OnPullStart();
}

export function handlePullComplete(e, CloudPebble) {
    CloudPebble.Sidebar.ClearIcon('github');
    CloudPebble.GitHub.OnPullComplete(JSON.parse(e.data));
}

export function handlePullFailed(CloudPebble) {
    CloudPebble.Sidebar.ClearIcon('github');
    CloudPebble.GitHub.OnPullFailed();
}

export function handleBuildStart(e, CloudPebble) {
    var data = JSON.parse(e.data);
    CloudPebble.Sidebar.SetIcon('compile', 'refresh');
    CloudPebble.Compile.OnBuildStart(data.build_id);
}

export function handleBuildComplete(e, CloudPebble) {
    var data = JSON.parse(e.data);
    CloudPebble.Sidebar.ClearIcon('compile');
    CloudPebble.Compile.OnBuildComplete(data.build_id, data.state);
}