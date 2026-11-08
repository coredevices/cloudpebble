"""The allow-list and the registered tools must not drift.

permission_mode='dontAsk' denies any tool absent from allowed_tools, which is
built from TOOL_NAMES. Declaring a @tool without adding it to TOOL_NAMES means
the model sees the tool, calls it, and is silently denied -- which is exactly
what happened to set_app_settings, so the agent could not flag a project as a
watchface and quietly shipped watch apps instead.
"""
import pathlib
import re


def test_tool_names_match_declared_tools():
    src = pathlib.Path(__file__).with_name('tools.py').read_text()
    declared = set(re.findall(r"@tool\('([a-z_]+)'", src))
    listed = re.search(r'TOOL_NAMES = \[(.*?)\]', src, re.S).group(1)
    listed = {n.strip().strip("'\"") for n in listed.split(',') if n.strip()}
    listed = {n for n in listed if n and not n.startswith('#')}
    assert declared == listed, (
        'tools.py drift: declared-but-not-allowed=%s allowed-but-not-declared=%s'
        % (sorted(declared - listed), sorted(listed - declared)))

    registered = re.search(r'tools=\[(.*?)\]', src, re.S).group(1)
    registered = {n.strip() for n in registered.replace('\n', ' ').split(',') if n.strip()}
    assert registered == declared, (
        'server registration drift: %s' % sorted(registered ^ declared))




def test_reference_paths_resolve_and_stay_inside_the_skills_directory():
    """The model reaches for these by three different spellings, and must not be
    able to reach anything else."""
    import os
    import tools

    root = tools.SKILLS_ROOT
    if not os.path.isdir(root):
        print('skip: no skills directory in this checkout')
        return

    # The shapes the model actually types.
    for name in ('reference/alloy-guide.md',
                 'pebble-watchface/reference/alloy-guide.md',
                 os.path.join(root, 'pebble-watchface/reference/alloy-guide.md')):
        resolved = tools._reference_path(name)
        assert resolved.startswith(root + os.sep), (name, resolved)
        assert os.path.isfile(resolved), name

    # And the shapes an escape would use.
    for bad in ('../../../etc/passwd', '/etc/passwd', 'reference/../../../../etc/passwd'):
        try:
            tools._reference_path(bad)
        except ValueError:
            continue
        raise AssertionError('escaped the skills directory: %s' % bad)

    index = tools._reference_index()
    assert any(p.endswith('alloy-guide.md') for p in index), index
    print('reference paths resolve, escapes refused')


if __name__ == '__main__':
    test_tool_names_match_declared_tools()
    print('tool registry consistent')
    test_reference_paths_resolve_and_stay_inside_the_skills_directory()
