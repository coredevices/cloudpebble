"""The state block is the only thing that tells the agent what it is building.

Get it wrong and the model lays out for the wrong screen or ships a watch app
believing it is a watchface -- both of which look fine in the screenshot.
"""
import project_state


INFO = {
    'type': 'native',
    'name': 'Space Face',
    'app_uuid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    'app_is_watchface': True,
    'app_platforms': 'emery,chalk',
    'supported_platforms': ['aplite', 'basalt', 'chalk', 'diorite', 'emery', 'flint', 'gabbro'],
    'app_keys': '["TEMPERATURE"]',
    'app_capabilities': 'location',
    'app_dependencies': {'@moddable/pebbleproxy': '^0.1.3'},
    'source_files': [{'file_path': 'src/c/main.c', 'target': 'app'}],
}


def test_screen_sizes_are_spelled_out_per_enabled_platform():
    block = project_state.render(INFO)
    assert '200x228' in block   # emery
    assert '180x180' in block   # chalk
    assert 'round' in block     # chalk is round, and that changes the layout
    assert '144x168' not in block  # not a target here, so not a size to design for


def test_a_watch_app_is_called_out_and_a_watchface_is_not():
    app = dict(INFO, app_is_watchface=False)
    assert 'app_is_watchface=true' in project_state.render(app)
    assert 'app_is_watchface=true' not in project_state.render(INFO)


def test_alloy_projects_are_named_as_such():
    block = project_state.render(dict(INFO, type='alloy'))
    assert 'Alloy' in block
    assert 'cannot change it' in block


def test_the_running_emulator_is_reported_with_its_size():
    block = project_state.render(INFO, {'platform': 'gabbro'})
    assert '260x260' in block


def test_no_emulator_says_so_rather_than_going_quiet():
    block = project_state.render(INFO, None)
    assert 'no emulator' in block
    assert 'build() still works' in block


def test_an_emulator_of_unknown_platform_does_not_invent_one():
    block = project_state.render(INFO, {'uuid': 'x', 'token': 'y', 'platform': ''})
    assert 'not reported' in block
    assert '200x228' in block  # from the target list, not from the emulator


def test_settings_and_files_both_survive():
    block = project_state.render(INFO)
    assert 'src/c/main.c' in block
    assert 'location' in block
    assert '@moddable/pebbleproxy@^0.1.3' in block


def test_writable_paths_are_named_so_a_refused_write_is_recoverable():
    # An agent told only "Unacceptable file extension for app file in [src/x.js]"
    # concluded it could not write pkjs at all and shipped without its weather JS.
    assert 'src/pkjs/*.js' in project_state.render(INFO)
    assert 'src/embeddedjs/main.js' in project_state.render(dict(INFO, type='alloy'))


def test_no_info_renders_nothing():
    assert project_state.render(None) == ''


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
