"""
Tests in this file can be run with run_tests.py
"""

import json

from django.test import TestCase
from unittest import mock
import ide.git
from ide.tasks.git import (
    validate_resources_against_tree,
    parse_manifest_from_tree,
    get_root_path,
    PEBBLEJS_BUILTIN_RESOURCES,
    _infer_resource_kind_from_path,
    _strip_resource_dir_prefix,
    _fetch_file_content,
    _remove_file_by_path,
    github_pull,
    _github_pull_delta,
    _github_pull_full,
    _apply_delta_changes,
    _upsert_source_file,
    _upsert_resource_variant,
    _sync_resource_files_from_manifest,
)
from ide.utils.project import BaseProjectItem


class FakeItem(BaseProjectItem):
    def __init__(self, item_path, content):
        self._path = item_path
        self._content = content

    def read(self):
        return self._content

    @property
    def path(self):
        return self._path


class UrlToReposTest(TestCase):
    def test_basic_url_to_repo(self):
        """
        Tests that a simple repo url is correctly recognized.
        """
        username, reponame = ide.git.url_to_repo("https://github.com/pebble/cloudpebble")
        self.assertEqual("pebble", username)
        self.assertEqual("cloudpebble", reponame)

    def test_strange_url_to_repo(self):
        """
        Tests that a non-standard repo url is correctly recognized.
        """
        username, reponame = ide.git.url_to_repo("git://github.com:foo/bar.git")
        self.assertEqual("foo", username)
        self.assertEqual("bar", reponame)

    def test_bad_url_to_repo(self):
        """
        Tests that a entirely different url returns None.
        """
        self.assertEqual(None, ide.git.url_to_repo("http://www.cuteoverload.com"))


class GetRootPathTest(TestCase):
    def test_strips_tilde_variant_suffix(self):
        self.assertEqual(get_root_path('images/icon~color.png'), 'images/icon.png')

    def test_strips_multiple_tilde_variants(self):
        self.assertEqual(get_root_path('images/icon~bw~rect.png'), 'images/icon.png')

    def test_no_variant(self):
        self.assertEqual(get_root_path('images/icon.png'), 'images/icon.png')

    def test_no_extension(self):
        self.assertEqual(get_root_path('data/binary~aplite'), 'data/binary')


class ValidateResourcesAgainstTreeTest(TestCase):
    def _make_project(self, project_type='native', resources_path='resources'):
        project = mock.MagicMock()
        project.project_type = project_type
        project.resources_path = resources_path
        return project

    def test_all_resources_present_passes(self):
        paths_notags = {'resources/images/icon.png', 'src/main.c'}
        manifest = {
            'resources': {'media': [
                {'file': 'images/icon.png', 'name': 'ICON', 'type': 'png'}
            ]}
        }
        project = self._make_project()
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'ICON')
        self.assertEqual(result[0]['file'], 'images/icon.png')

    def test_multiple_resources_all_present(self):
        paths_notags = {'resources/images/icon.png', 'resources/fonts/mono.ttf', 'src/main.c'}
        manifest = {
            'resources': {'media': [
                {'file': 'images/icon.png', 'name': 'ICON', 'type': 'png'},
                {'file': 'fonts/mono.ttf', 'name': 'MONO', 'type': 'font'},
            ]}
        }
        project = self._make_project()
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 2)
        names = {r['name'] for r in result}
        self.assertEqual(names, {'ICON', 'MONO'})

    def test_missing_resource_raises(self):
        paths_notags = {'src/main.c'}
        manifest = {
            'resources': {'media': [
                {'file': 'images/icon.png', 'name': 'ICON', 'type': 'png'}
            ]}
        }
        project = self._make_project()
        with self.assertRaises(Exception) as ctx:
            validate_resources_against_tree(paths_notags, manifest, project)
        self.assertIn('images/icon.png', str(ctx.exception))

    def test_missing_resource_with_variant_in_tree_still_fails(self):
        paths_notags = {'resources/images/icon~color.png', 'src/main.c'}
        manifest = {
            'resources': {'media': [
                {'file': 'images/icon.png', 'name': 'ICON', 'type': 'png'}
            ]}
        }
        project = self._make_project()
        with self.assertRaises(Exception) as ctx:
            validate_resources_against_tree(paths_notags, manifest, project)
        self.assertIn('images/icon.png', str(ctx.exception))

    def test_pebblejs_skips_builtin_resources(self):
        paths_notags = {'src/app.js'}
        manifest = {
            'projectType': 'pebblejs',
            'resources': {'media': [
                {'file': 'images/mono.png', 'name': 'MONO_FONT_14', 'type': 'font'},
                {'file': 'images/icon.png', 'name': 'IMAGE_MENU_ICON', 'type': 'bitmap'},
            ]}
        }
        project = self._make_project(project_type='pebblejs')
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 2)
        names = {r['name'] for r in result}
        self.assertEqual(names, {'MONO_FONT_14', 'IMAGE_MENU_ICON'})

    def test_pebblejs_requires_non_builtin_resource(self):
        paths_notags = {'src/app.js'}
        manifest = {
            'projectType': 'pebblejs',
            'resources': {'media': [
                {'file': 'images/mono.png', 'name': 'MONO_FONT_14', 'type': 'font'},
                {'file': 'images/custom.png', 'name': 'CUSTOM_ICON', 'type': 'bitmap'},
            ]}
        }
        project = self._make_project(project_type='pebblejs')
        with self.assertRaises(Exception) as ctx:
            validate_resources_against_tree(paths_notags, manifest, project)
        self.assertIn('custom.png', str(ctx.exception))
        self.assertNotIn('mono.png', str(ctx.exception))

    def test_empty_resources_passes(self):
        paths_notags = {'src/main.c'}
        manifest = {'resources': {'media': []}}
        project = self._make_project()
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 0)

    def test_no_resources_key_passes(self):
        paths_notags = {'src/main.c'}
        manifest = {}
        project = self._make_project()
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 0)

    def test_package_project_uses_src_resources_prefix(self):
        paths_notags = {'src/resources/data/config.json', 'src/main.c'}
        manifest = {
            'resources': {'media': [
                {'file': 'data/config.json', 'name': 'CONFIG', 'type': 'raw'}
            ]}
        }
        project = self._make_project(resources_path='src/resources')
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'CONFIG')

    def test_resource_with_variant_in_tree_matches_root(self):
        paths_notags = {'resources/images/icon.png', 'src/main.c'}
        manifest = {
            'resources': {'media': [
                {'file': 'images/icon.png', 'name': 'ICON', 'type': 'png'}
            ]}
        }
        project = self._make_project()
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'ICON')

    def test_package_json_manifest_reads_resources_from_pebble_key(self):
        paths_notags = {'src/resources/images/icon.png', 'src/main.c'}
        manifest = {
            'pebble': {
                'projectType': 'native',
                'resources': {'media': [
                    {'file': 'images/icon.png', 'name': 'ICON', 'type': 'png'}
                ]}
            }
        }
        project = self._make_project(resources_path='src/resources')
        result = validate_resources_against_tree(paths_notags, manifest, project)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'ICON')

    def test_package_json_pebble_skips_builtin_resources(self):
        paths_notags = {'src/app.js'}
        manifest = {
            'pebble': {
                'projectType': 'pebblejs',
                'resources': {'media': [
                    {'file': 'images/mono.png', 'name': 'MONO_FONT_14', 'type': 'font'},
                    {'file': 'images/custom.png', 'name': 'CUSTOM_ICON', 'type': 'bitmap'},
                ]}
            }
        }
        project = self._make_project(project_type='pebblejs', resources_path='src/resources')
        with self.assertRaises(Exception) as ctx:
            validate_resources_against_tree(paths_notags, manifest, project)
        self.assertIn('custom.png', str(ctx.exception))
        self.assertNotIn('mono.png', str(ctx.exception))

    def test_root_prefix_prepended_to_paths(self):
        paths_notags = {'myproject/resources/images/icon.png', 'myproject/src/main.c'}
        manifest = {
            'resources': {'media': [
                {'file': 'images/icon.png', 'name': 'ICON', 'type': 'png'}
            ]}
        }
        project = self._make_project()
        result = validate_resources_against_tree(paths_notags, manifest, project, root='myproject')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'ICON')

    def test_root_prefix_with_package_json_manifest(self):
        paths_notags = {'sdk-demo/src/resources/data/config.json', 'sdk-demo/src/main.c'}
        manifest = {
            'pebble': {
                'projectType': 'native',
                'resources': {'media': [
                    {'file': 'data/config.json', 'name': 'CONFIG', 'type': 'raw'}
                ]}
            }
        }
        project = self._make_project(resources_path='src/resources')
        result = validate_resources_against_tree(paths_notags, manifest, project, root='sdk-demo')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'CONFIG')


class PebblejsBuiltinsTest(TestCase):
    def test_builtin_resource_names(self):
        self.assertEqual(
            PEBBLEJS_BUILTIN_RESOURCES,
            {'MONO_FONT_14', 'IMAGE_MENU_ICON', 'IMAGE_LOGO_SPLASH', 'IMAGE_TILE_SPLASH'},
        )

    def test_builtin_resources_are_frozenset(self):
        self.assertIsInstance(PEBBLEJS_BUILTIN_RESOURCES, frozenset)


class ParseManifestFromTreeTest(TestCase):
    def _make_appinfo(self, **overrides):
        appinfo = {
            "uuid": "123e4567-e89b-42d3-a456-426655440000",
            "longName": "test",
            "shortName": "test",
            "companyName": "test",
            "versionLabel": "1.0",
            "projectType": "native",
            "sdkVersion": "3",
            "enableMultiJS": True,
            "watchapp": {"watchface": False},
            "appKeys": {},
            "resources": {"media": []},
        }
        appinfo.update(overrides)
        return json.dumps(appinfo)

    def _make_package(self, pebble_options=None, **overrides):
        package = {
            "name": "test",
            "version": "1.0.0",
            "author": "test",
            "dependencies": {},
            "keywords": [],
            "pebble": {
                "displayName": "test",
                "messageKeys": [],
                "enableMultiJS": True,
                "projectType": "native",
                "resources": {"media": []},
                "sdkVersion": "3",
                "uuid": "123e4567-e89b-42d3-a456-426655440000",
                "watchapp": {"watchface": False},
            },
        }
        if pebble_options:
            package["pebble"].update(pebble_options)
        package.update(overrides)
        return json.dumps(package)

    def test_extracts_appinfo_manifest_from_root(self):
        items = [
            FakeItem('src/main.c', 'int main(void) { return 0; }'),
            FakeItem('appinfo.json', self._make_appinfo()),
        ]
        root, manifest = parse_manifest_from_tree(items, None)
        self.assertEqual(root, '')
        self.assertEqual(manifest['projectType'], 'native')
        self.assertEqual(manifest['shortName'], 'test')
        self.assertIn('resources', manifest)

    def test_extracts_appinfo_manifest_from_subdirectory(self):
        items = [
            FakeItem('myproject/src/main.c', 'int main(void) { return 0; }'),
            FakeItem('myproject/appinfo.json', self._make_appinfo()),
        ]
        root, manifest = parse_manifest_from_tree(items, None)
        self.assertEqual(root, 'myproject/')
        self.assertEqual(manifest['projectType'], 'native')

    def test_extracts_package_json_manifest(self):
        items = [
            FakeItem('src/main.c', 'int main(void) { return 0; }'),
            FakeItem('package.json', self._make_package()),
        ]
        root, manifest = parse_manifest_from_tree(items, None)
        self.assertEqual(root, '')
        self.assertIn('pebble', manifest)
        self.assertEqual(manifest['pebble']['projectType'], 'native')

    def test_raises_on_invalid_json(self):
        items = [
            FakeItem('src/main.c', 'int main(void) { return 0; }'),
            FakeItem('appinfo.json', 'not valid json {{{'),
        ]
        from ide.utils.project import InvalidProjectArchiveException
        with self.assertRaises(InvalidProjectArchiveException):
            parse_manifest_from_tree(items, None)

    def test_raises_when_no_manifest_found(self):
        items = [
            FakeItem('src/main.c', 'int main(void) { return 0; }'),
        ]
        from ide.utils.project import InvalidProjectArchiveException
        with self.assertRaises(InvalidProjectArchiveException):
            parse_manifest_from_tree(items, None)


class InferResourceKindTest(TestCase):
    def test_png_maps_to_png(self):
        self.assertEqual(_infer_resource_kind_from_path('icon.png'), 'png')

    def test_pbi_maps_to_pbi(self):
        self.assertEqual(_infer_resource_kind_from_path('image.pbi'), 'pbi')

    def test_ttf_maps_to_font(self):
        self.assertEqual(_infer_resource_kind_from_path('font.ttf'), 'font')

    def test_otf_maps_to_font(self):
        self.assertEqual(_infer_resource_kind_from_path('font.otf'), 'font')

    def test_unknown_maps_to_raw(self):
        self.assertEqual(_infer_resource_kind_from_path('data.bin'), 'raw')

    def test_jpg_maps_to_raw(self):
        self.assertEqual(_infer_resource_kind_from_path('photo.jpg'), 'raw')


class StripResourceDirPrefixTest(TestCase):
    def test_strips_images_prefix(self):
        self.assertEqual(_strip_resource_dir_prefix('images/icon.png'), 'icon.png')

    def test_strips_fonts_prefix(self):
        self.assertEqual(_strip_resource_dir_prefix('fonts/mono.ttf'), 'mono.ttf')

    def test_strips_data_prefix(self):
        self.assertEqual(_strip_resource_dir_prefix('data/config.json'), 'config.json')

    def test_no_prefix_returns_unchanged(self):
        self.assertEqual(_strip_resource_dir_prefix('icon.png'), 'icon.png')

    def test_custom_prefixes(self):
        prefixes = {'images/', 'fonts/', 'data/'}
        self.assertEqual(_strip_resource_dir_prefix('images/icon.png', prefixes), 'icon.png')


class FetchFileContentTest(TestCase):
    def _make_change(self, filename, sha=None):
        change = mock.MagicMock()
        change.filename = filename
        change.sha = sha
        return change

    def test_returns_decoded_content_for_text_file(self):
        repo = mock.MagicMock()
        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'hello world'
        repo.get_contents.return_value = contents

        change = self._make_change('src/main.c', sha='abc123')
        result = _fetch_file_content(repo, change)
        self.assertEqual(result, b'hello world')
        repo.get_contents.assert_called_once_with('src/main.c', ref='abc123')

    def test_returns_base64_decoded_content(self):
        import base64
        repo = mock.MagicMock()
        contents = mock.MagicMock()
        contents.encoding = 'base64'
        contents.content = base64.b64encode(b'binary data').decode('ascii')
        repo.get_contents.return_value = contents

        change = self._make_change('resources/images/icon.png')
        result = _fetch_file_content(repo, change)
        self.assertEqual(result, b'binary data')

    def test_returns_none_for_directory(self):
        repo = mock.MagicMock()
        repo.get_contents.return_value = [mock.MagicMock(), mock.MagicMock()]

        change = self._make_change('src/')
        result = _fetch_file_content(repo, change)
        self.assertIsNone(result)

    def test_returns_none_on_github_exception(self):
        from github import GithubException
        repo = mock.MagicMock()
        repo.get_contents.side_effect = GithubException(404, 'Not Found', {})

        change = self._make_change('src/missing.c', sha='abc')
        result = _fetch_file_content(repo, change)
        self.assertIsNone(result)

    def test_uses_sha_ref_when_available(self):
        repo = mock.MagicMock()
        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'data'
        repo.get_contents.return_value = contents

        change = self._make_change('src/main.c', sha='deadbeef')
        _fetch_file_content(repo, change)
        repo.get_contents.assert_called_once_with('src/main.c', ref='deadbeef')

    def test_uses_no_ref_when_sha_is_none(self):
        repo = mock.MagicMock()
        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'data'
        repo.get_contents.return_value = contents

        change = self._make_change('src/main.c', sha=None)
        _fetch_file_content(repo, change)
        repo.get_contents.assert_called_once_with('src/main.c', ref=None)


class RemoveFileByPathTest(TestCase):
    def _make_project(self, project_type='native', resources_path='resources'):
        project = mock.MagicMock()
        project.project_type = project_type
        project.resources_path = resources_path
        return project

    def test_removes_existing_source_file(self):
        project = self._make_project()
        source = mock.MagicMock()
        existing_sources = {'src/main.c': source}
        existing_resources = {}

        _remove_file_by_path(project, 'src/main.c', existing_sources, existing_resources)
        source.delete.assert_called_once()
        self.assertNotIn('src/main.c', existing_sources)

    def test_removes_missing_source_file_from_db(self):
        project = self._make_project()
        existing_sources = {}
        existing_resources = {}

        with mock.patch('ide.tasks.git.SourceFile.get_details_for_path', return_value=('main.c', 'app')):
            with mock.patch('ide.tasks.git.SourceFile.objects') as mock_objects:
                mock_filter = mock.MagicMock()
                mock_objects.filter.return_value = mock_filter
                _remove_file_by_path(project, 'src/main.c', existing_sources, existing_resources)
                mock_objects.filter.assert_called_once()
                mock_filter.delete.assert_called_once()

    def test_removes_resource_variant_and_orphaned_file(self):
        project = self._make_project()
        resource_file = mock.MagicMock()
        resource_file.variants.count.return_value = 0
        existing_sources = {}
        existing_resources = {'images/icon.png': resource_file}

        with mock.patch('ide.tasks.git.ResourceVariant.objects') as mock_objects:
            mock_filter = mock.MagicMock()
            mock_objects.filter.return_value = mock_filter
            _remove_file_by_path(project, 'resources/images/icon.png', existing_sources, existing_resources)
            mock_objects.filter.assert_called_once()
            mock_filter.delete.assert_called_once()
            resource_file.delete.assert_called_once()
            self.assertNotIn('images/icon.png', existing_resources)

    def test_removes_resource_variant_but_keeps_file_with_remaining_variants(self):
        project = self._make_project()
        resource_file = mock.MagicMock()
        resource_file.variants.count.return_value = 1
        existing_sources = {}
        existing_resources = {'images/icon.png': resource_file}

        with mock.patch('ide.tasks.git.ResourceVariant.objects') as mock_objects:
            mock_filter = mock.MagicMock()
            mock_objects.filter.return_value = mock_filter
            _remove_file_by_path(project, 'resources/images/icon~color.png', existing_sources, existing_resources)
            mock_objects.filter.assert_called_once()
            mock_filter.delete.assert_called_once()
            resource_file.delete.assert_not_called()
            self.assertIn('images/icon.png', existing_resources)

    def test_skips_unrecognized_resource_tags(self):
        project = self._make_project()
        existing_sources = {}
        existing_resources = {}

        _remove_file_by_path(project, 'resources/images/icon~unknowntag.png', existing_sources, existing_resources)

    def test_skips_unrecognized_source_paths(self):
        project = self._make_project()
        existing_sources = {}
        existing_resources = {}

        with mock.patch('ide.tasks.git.SourceFile') as MockSourceFile:
            MockSourceFile.get_details_for_path.side_effect = ValueError('bad path')
            _remove_file_by_path(project, 'unknown/path.dat', existing_sources, existing_resources)
            MockSourceFile.objects.filter.assert_not_called()


def _mock_github():
    mock_repo = mock.MagicMock()
    mock_repo.default_branch = 'main'
    mock_branch = mock.MagicMock()
    mock_branch.commit.sha = 'newsha'
    mock_repo.get_branch.return_value = mock_branch
    return mock_repo, mock_branch


class GithubPullRoutingTest(TestCase):
    def setUp(self):
        self.user = mock.MagicMock()
        self.project = mock.MagicMock()
        self.project.github_repo = 'owner/repo'
        self.project.github_branch = 'main'
        self.project.github_last_commit = 'oldsha'
        self.project.github_hook_force = False

    @mock.patch('ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.tasks.git._github_pull_full')
    @mock.patch('ide.tasks.git.get_github')
    def test_force_pull_uses_full(self, mock_get_github, mock_full, mock_verify):
        mock_repo, mock_branch = _mock_github()
        mock_get_github.return_value.get_repo.return_value = mock_repo
        mock_full.return_value = True

        result = github_pull(self.user, self.project, force=True)
        mock_full.assert_called_once()
        self.assertTrue(result)

    @mock.patch('ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.tasks.git._github_pull_full')
    @mock.patch('ide.tasks.git.get_github')
    def test_no_previous_commit_uses_full(self, mock_get_github, mock_full, mock_verify):
        self.project.github_last_commit = None
        mock_repo, mock_branch = _mock_github()
        mock_get_github.return_value.get_repo.return_value = mock_repo
        mock_full.return_value = True

        result = github_pull(self.user, self.project, force=False)
        mock_full.assert_called_once()

    @mock.patch('ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.tasks.git._github_pull_delta')
    @mock.patch('ide.tasks.git._github_pull_full')
    @mock.patch('ide.tasks.git.get_github')
    def test_delta_sync_when_not_forced(self, mock_get_github, mock_full, mock_delta, mock_verify):
        mock_repo, mock_branch = _mock_github()
        mock_get_github.return_value.get_repo.return_value = mock_repo
        mock_delta.return_value = True

        result = github_pull(self.user, self.project, force=False)
        mock_delta.assert_called_once_with(self.user, self.project, mock_repo, 'newsha')
        mock_full.assert_not_called()
        self.assertTrue(result)

    @mock.patch('ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.tasks.git._github_pull_delta')
    @mock.patch('ide.tasks.git._github_pull_full')
    @mock.patch('ide.tasks.git.get_github')
    def test_falls_back_to_full_on_delta_failure(self, mock_get_github, mock_full, mock_delta, mock_verify):
        mock_repo, mock_branch = _mock_github()
        mock_get_github.return_value.get_repo.return_value = mock_repo
        mock_delta.side_effect = Exception('compare API failed')
        mock_full.return_value = True

        result = github_pull(self.user, self.project, force=False)
        mock_full.assert_called_once_with(self.user, self.project, mock_repo, mock_branch)
        self.assertTrue(result)

    @mock.patch('ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.tasks.git.get_github')
    def test_returns_false_when_no_new_commits(self, mock_get_github, mock_verify):
        mock_repo = mock.MagicMock()
        mock_repo.default_branch = 'main'
        mock_branch = mock.MagicMock()
        mock_branch.commit.sha = 'oldsha'
        mock_repo.get_branch.return_value = mock_branch
        mock_get_github.return_value.get_repo.return_value = mock_repo

        result = github_pull(self.user, self.project, force=False)
        self.assertFalse(result)

    @mock.patch('ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.tasks.git.get_github')
    def test_raises_when_no_repo_defined(self, mock_get_github, mock_verify):
        self.project.github_repo = None
        mock_repo, mock_branch = _mock_github()
        mock_get_github.return_value.get_repo.return_value = mock_repo

        with self.assertRaises(Exception) as ctx:
            github_pull(self.user, self.project, force=False)
        self.assertIn('No GitHub repo defined', str(ctx.exception))

    @mock.patch('ide.git.git_verify_tokens', return_value=True)
    @mock.patch('ide.tasks.git.get_github')
    def test_raises_when_branch_not_found(self, mock_get_github, mock_verify):
        from github import GithubException
        mock_repo = mock.MagicMock()
        mock_repo.default_branch = 'main'
        mock_repo.get_branch.side_effect = GithubException(404, 'Not Found', {})
        mock_get_github.return_value.get_repo.return_value = mock_repo

        with self.assertRaises(Exception) as ctx:
            github_pull(self.user, self.project, force=False)
        self.assertIn('Unable to get the branch', str(ctx.exception))


class GithubPullDeltaTest(TestCase):
    def setUp(self):
        self.user = mock.MagicMock()
        self.project = mock.MagicMock()
        self.project.github_last_commit = 'oldsha'
        self.project.resources_path = 'resources'
        self.project.project_type = 'native'
        self.repo = mock.MagicMock()

    @mock.patch('ide.tasks.git._apply_delta_changes')
    @mock.patch('ide.tasks.git.validate_resources_against_tree')
    @mock.patch('ide.tasks.git.parse_manifest_from_tree')
    @mock.patch('ide.tasks.git.get_root_path')
    @mock.patch('ide.tasks.git.now')
    def test_delta_pull_applies_changes(self, mock_now, mock_get_root, mock_parse, mock_validate, mock_apply):
        mock_now.return_value = '2025-01-01T00:00:00Z'
        comparison = mock.MagicMock()
        comparison.ahead_by = 3
        comparison.files = [mock.MagicMock(filename='src/main.c', status='modified')]
        self.repo.compare.return_value = comparison

        mock_commit = mock.MagicMock()
        mock_commit.tree.sha = 'treesha'
        self.repo.get_git_commit.return_value = mock_commit
        mock_tree = mock.MagicMock()
        mock_tree.tree = []
        self.repo.get_git_tree.return_value = mock_tree

        mock_parse.return_value = ('', {'projectType': 'native'})
        mock_get_root.return_value = 'src/main.c'

        # _apply_delta_changes is responsible for stamping the new SHA inside
        # its atomic block; simulate that here.
        def fake_apply(project, repo, root, manifest, changed_files, new_commit_sha=None):
            project.github_last_commit = new_commit_sha
            project.github_last_sync = mock_now.return_value
            project.save()
        mock_apply.side_effect = fake_apply

        result = _github_pull_delta(self.user, self.project, self.repo, 'newsha')
        self.assertTrue(result)
        mock_apply.assert_called_once()
        self.assertEqual(self.project.github_last_commit, 'newsha')
        self.project.save.assert_called()

    @mock.patch('ide.tasks.git.now')
    def test_delta_pull_returns_false_when_ahead_by_zero(self, mock_now):
        mock_now.return_value = '2025-01-01T00:00:00Z'
        comparison = mock.MagicMock()
        comparison.ahead_by = 0
        self.repo.compare.return_value = comparison

        result = _github_pull_delta(self.user, self.project, self.repo, 'newsha')
        self.assertFalse(result)
        self.assertEqual(self.project.github_last_commit, 'newsha')


class ApplyDeltaChangesTest(TestCase):
    def _make_change(self, filename, status, sha=None, previous_filename=None):
        change = mock.MagicMock()
        change.filename = filename
        change.status = status
        change.sha = sha or 'abc123'
        if previous_filename:
            change.previous_filename = previous_filename
        else:
            change.previous_filename = None
        return change

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git._upsert_source_file')
    def test_applies_added_source_file(self, mock_upsert, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('src/main.c', 'added')
        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            _apply_delta_changes(project, repo, '', manifest, [change])

        mock_upsert.assert_called_once()
        self.assertEqual(mock_upsert.call_args[0][2].filename, 'src/main.c')

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git._remove_file_by_path')
    def test_applies_removed_source_file(self, mock_remove, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('src/main.c', 'removed')
        manifest = {'projectType': 'native', 'resources': {'media': []}}
        existing_sources = {}
        existing_resources = {}

        with mock.patch('ide.tasks.git.transaction'):
            with mock.patch('ide.tasks.git.SourceFile') as MockSF:
                mock_qs = mock.MagicMock()
                project.source_files.all.return_value = []
                project.resources.all.return_value = []
                _apply_delta_changes(project, repo, '', manifest, [change])

        mock_remove.assert_called()

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git._remove_file_by_path')
    @mock.patch('ide.tasks.git._upsert_source_file')
    def test_handles_renamed_file(self, mock_upsert, mock_remove, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('src/new_main.c', 'renamed', previous_filename='src/old_main.c')
        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            with mock.patch('ide.tasks.git.SourceFile') as MockSF:
                project.source_files.all.return_value = []
                project.resources.all.return_value = []
                _apply_delta_changes(project, repo, '', manifest, [change])

        mock_remove.assert_called_once()
        self.assertEqual(mock_remove.call_args[0][1], 'src/old_main.c')

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git.SourceFile')
    def test_skips_unrecognized_source_file_path(self, MockSF, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('unknown/weird.dat', 'added')
        manifest = {'projectType': 'native', 'resources': {'media': []}}

        MockSF.get_details_for_path.side_effect = ValueError('bad path')

        with mock.patch('ide.tasks.git.transaction'):
            project.source_files.all.return_value = []
            project.resources.all.return_value = []
            _apply_delta_changes(project, repo, '', manifest, [change])

        MockSF.objects.create.assert_not_called()

    @mock.patch('ide.tasks.git._upsert_resource_variant')
    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    def test_routes_resource_file_to_upsert_resource_variant(self, mock_load, mock_sync, mock_upsert_resource):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('resources/images/icon.png', 'added')
        manifest = {'projectType': 'native', 'resources': {'media': []}}
        tag_map = {}

        with mock.patch('ide.tasks.git.transaction'):
            with mock.patch('ide.tasks.git.ResourceVariant') as MockRV:
                mock_rv_map = {v: k for k, v in MockRV.VARIANT_STRINGS.items() if v}
                with mock.patch('ide.tasks.git.SourceFile'):
                    project.source_files.all.return_value = []
                    project.resources.all.return_value = []
                    _apply_delta_changes(project, repo, '', manifest, [change])

        mock_upsert_resource.assert_called_once()

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git._upsert_resource_variant')
    @mock.patch('ide.tasks.git.SourceFile')
    def test_existing_resources_keyed_by_manifest_path(self, MockSF, mock_upsert_resource, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        existing_resource = mock.MagicMock()
        existing_resource.file_name = 'icon.png'
        existing_resource.kind = 'png'
        project.resources.all.return_value = [existing_resource]
        project.source_files.all.return_value = []

        change = self._make_change('resources/images/icon.png', 'modified')
        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            with mock.patch('ide.tasks.git.ResourceVariant') as MockRV:
                mock_rv_map = {v: k for k, v in MockRV.VARIANT_STRINGS.items() if v}
                _apply_delta_changes(project, repo, '', manifest, [change])

        mock_upsert_resource.assert_called_once()
        self.assertIs(mock_upsert_resource.call_args[0][4]['images/icon.png'], existing_resource)

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    def test_updates_project_options_from_manifest(self, mock_load, mock_sync):
        mock_load.return_value = ({
            'app_long_name': 'My App',
            'app_short_name': 'MyApp',
        }, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            project.source_files.all.return_value = []
            project.resources.all.return_value = []
            _apply_delta_changes(project, repo, '', manifest, [])

        project.full_clean.assert_called_once()
        project.set_dependencies.assert_called_once_with({})


class UpsertSourceFileTest(TestCase):
    def test_creates_new_source_file_when_not_in_existing(self):
        project = mock.MagicMock()
        repo = mock.MagicMock()
        existing_sources = {}

        change = mock.MagicMock()
        change.filename = 'src/main.c'
        change.sha = 'abc123'

        mock_source = mock.MagicMock()
        mock_source.is_editable_text = True

        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'// hello'
        repo.get_contents.return_value = contents

        with mock.patch('ide.tasks.git.SourceFile') as MockSF:
            MockSF.objects.create.return_value = mock_source
            MockSF.get_details_for_path.return_value = ('main.c', 'app')
            _upsert_source_file(project, repo, change, 'main.c', 'app', existing_sources)

        MockSF.objects.create.assert_called_once_with(project=project, file_name='main.c', target='app')
        mock_source.save_text.assert_called_once_with('// hello')

    def test_updates_existing_source_file(self):
        project = mock.MagicMock()
        repo = mock.MagicMock()
        existing_source = mock.MagicMock()
        existing_source.is_editable_text = True
        existing_sources = {'src/main.c': existing_source}

        change = mock.MagicMock()
        change.filename = 'src/main.c'
        change.sha = 'def456'

        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'// updated'
        repo.get_contents.return_value = contents

        _upsert_source_file(project, repo, change, 'main.c', 'app', existing_sources)

        existing_source.save_text.assert_called_once_with('// updated')

    @mock.patch('ide.tasks.git._fetch_file_content')
    def test_skips_when_content_is_none(self, mock_fetch):
        project = mock.MagicMock()
        repo = mock.MagicMock()
        existing_sources = {}

        change = mock.MagicMock()
        change.filename = 'src/main.c'

        mock_fetch.return_value = None

        with mock.patch('ide.tasks.git.SourceFile') as MockSF:
            _upsert_source_file(project, repo, change, 'main.c', 'app', existing_sources)
            MockSF.objects.create.assert_not_called()


class UpsertResourceVariantTest(TestCase):
    def test_creates_new_resource_variant(self):
        project = mock.MagicMock()
        project.resources_path = 'resources'
        repo = mock.MagicMock()

        change = mock.MagicMock()
        change.filename = 'resources/images/icon.png'
        change.sha = 'abc123'

        existing_resources = {}
        tag_map = {}

        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'\x89PNG'
        repo.get_contents.return_value = contents

        mock_resource = mock.MagicMock()
        mock_variant = mock.MagicMock()

        with mock.patch('ide.tasks.git.ResourceFile') as MockRF:
            with mock.patch('ide.tasks.git.ResourceVariant') as MockRV:
                with mock.patch('ide.tasks.git.ResourceVariant.VARIANT_STRINGS', {}):
                    MockRF.objects.create.return_value = mock_resource
                    MockRV.objects.filter.return_value.first.return_value = None
                    MockRV.objects.create.return_value = mock_variant

                    _upsert_resource_variant(project, repo, change, 'resources/images/icon.png', existing_resources, tag_map)

        MockRF.objects.create.assert_called_once()
        mock_variant.save_file.assert_called_once()

    def test_adds_variant_to_existing_resource(self):
        project = mock.MagicMock()
        project.resources_path = 'resources'
        repo = mock.MagicMock()

        change = mock.MagicMock()
        change.filename = 'resources/images/icon.png'
        change.sha = 'abc123'

        existing_resource = mock.MagicMock()
        existing_resources = {'images/icon.png': existing_resource}
        tag_map = {}

        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'\x89PNG'
        repo.get_contents.return_value = contents

        mock_variant = mock.MagicMock()

        with mock.patch('ide.tasks.git.ResourceFile') as MockRF:
            with mock.patch('ide.tasks.git.ResourceVariant') as MockRV:
                with mock.patch('ide.tasks.git.ResourceVariant.VARIANT_STRINGS', {}):
                    MockRV.objects.filter.return_value.first.return_value = None
                    MockRV.objects.create.return_value = mock_variant

                    _upsert_resource_variant(project, repo, change, 'resources/images/icon.png', existing_resources, tag_map)

        MockRF.objects.create.assert_not_called()
        mock_variant.save_file.assert_called_once()


class ApplyDeltaChangesWithRootTest(TestCase):
    def _make_change(self, filename, status, sha=None, previous_filename=None):
        change = mock.MagicMock()
        change.filename = filename
        change.status = status
        change.sha = sha or 'abc123'
        if previous_filename:
            change.previous_filename = previous_filename
        else:
            change.previous_filename = None
        return change

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git._upsert_source_file')
    def test_strips_root_from_source_file_path(self, mock_upsert, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('myproject/src/main.c', 'added')
        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            with mock.patch('ide.tasks.git.SourceFile') as MockSF:
                MockSF.get_details_for_path.return_value = ('main.c', 'app')
                project.source_files.all.return_value = []
                project.resources.all.return_value = []
                _apply_delta_changes(project, repo, 'myproject', manifest, [change])

        mock_upsert.assert_called_once()
        self.assertEqual(mock_upsert.call_args[0][6], 'src/main.c')

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git._upsert_resource_variant')
    def test_strips_root_from_resource_file_path(self, mock_upsert_resource, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('myproject/resources/images/icon.png', 'added')
        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            with mock.patch('ide.tasks.git.ResourceVariant') as MockRV:
                mock_rv_map = {v: k for k, v in MockRV.VARIANT_STRINGS.items() if v}
                with mock.patch('ide.tasks.git.SourceFile'):
                    project.source_files.all.return_value = []
                    project.resources.all.return_value = []
                    _apply_delta_changes(project, repo, 'myproject', manifest, [change])

        mock_upsert_resource.assert_called_once()
        self.assertEqual(mock_upsert_resource.call_args[0][3], 'resources/images/icon.png')

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git._remove_file_by_path')
    @mock.patch('ide.tasks.git._upsert_source_file')
    def test_strips_root_from_renamed_previous_filename(self, mock_upsert, mock_remove, mock_load, mock_sync):
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        repo = mock.MagicMock()

        change = self._make_change('myproject/src/new_main.c', 'renamed', previous_filename='myproject/src/old_main.c')
        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            with mock.patch('ide.tasks.git.SourceFile') as MockSF:
                MockSF.get_details_for_path.return_value = ('new_main.c', 'app')
                project.source_files.all.return_value = []
                project.resources.all.return_value = []
                _apply_delta_changes(project, repo, 'myproject', manifest, [change])

        mock_remove.assert_called_once()


class UpsertResourceVariantKindOverrideTest(TestCase):
    def test_uses_manifest_type_when_media_map_provided(self):
        project = mock.MagicMock()
        project.resources_path = 'resources'
        repo = mock.MagicMock()

        change = mock.MagicMock()
        change.filename = 'resources/images/icon.png'
        change.sha = 'abc123'

        existing_resources = {}
        tag_map = {}
        media_map = [{'file': 'images/icon.png', 'name': 'ICON', 'type': 'bitmap'}]

        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'\x89PNG'
        repo.get_contents.return_value = contents

        mock_resource = mock.MagicMock()
        mock_variant = mock.MagicMock()

        with mock.patch('ide.tasks.git.ResourceFile') as MockRF:
            with mock.patch('ide.tasks.git.ResourceVariant') as MockRV:
                with mock.patch('ide.tasks.git.ResourceVariant.VARIANT_STRINGS', {}):
                    MockRF.objects.create.return_value = mock_resource
                    MockRV.objects.filter.return_value.first.return_value = None
                    MockRV.objects.create.return_value = mock_variant

                    _upsert_resource_variant(project, repo, change, 'resources/images/icon.png', existing_resources, tag_map, media_map)

        MockRF.objects.create.assert_called_once()
        self.assertEqual(MockRF.objects.create.call_args[1]['kind'], 'bitmap')

    def test_infers_kind_when_media_map_is_none(self):
        project = mock.MagicMock()
        project.resources_path = 'resources'
        repo = mock.MagicMock()

        change = mock.MagicMock()
        change.filename = 'resources/images/icon.png'
        change.sha = 'abc123'

        existing_resources = {}
        tag_map = {}

        contents = mock.MagicMock()
        contents.encoding = None
        contents.decoded_content = b'\x89PNG'
        repo.get_contents.return_value = contents

        mock_resource = mock.MagicMock()
        mock_variant = mock.MagicMock()

        with mock.patch('ide.tasks.git.ResourceFile') as MockRF:
            with mock.patch('ide.tasks.git.ResourceVariant') as MockRV:
                with mock.patch('ide.tasks.git.ResourceVariant.VARIANT_STRINGS', {}):
                    MockRF.objects.create.return_value = mock_resource
                    MockRV.objects.filter.return_value.first.return_value = None
                    MockRV.objects.create.return_value = mock_variant

                    _upsert_resource_variant(project, repo, change, 'resources/images/icon.png', existing_resources, tag_map)

        MockRF.objects.create.assert_called_once()
        self.assertEqual(MockRF.objects.create.call_args[1]['kind'], 'png')


class SyncResourceFilesFromManifestTest(TestCase):
    @mock.patch('ide.tasks.git.ResourceIdentifier')
    def test_corrects_kind_on_existing_resource(self, MockRI):
        from ide.tasks.git import _sync_resource_files_from_manifest
        project = mock.MagicMock()
        project.project_type = 'native'

        existing_resource = mock.MagicMock()
        existing_resource.kind = 'png'
        existing_resource.is_menu_icon = False
        existing_resources = {'images/icon.png': existing_resource}

        media_map = [{'file': 'images/icon.png', 'name': 'ICON', 'type': 'bitmap', 'menuIcon': True}]

        _sync_resource_files_from_manifest(project, media_map, existing_resources)

        self.assertEqual(existing_resource.kind, 'bitmap')
        self.assertTrue(existing_resource.is_menu_icon)
        existing_resource.save.assert_called_once()

    @mock.patch('ide.tasks.git.ResourceIdentifier')
    def test_does_not_save_when_kind_already_correct(self, MockRI):
        from ide.tasks.git import _sync_resource_files_from_manifest
        project = mock.MagicMock()
        project.project_type = 'native'

        existing_resource = mock.MagicMock()
        existing_resource.kind = 'png'
        existing_resource.is_menu_icon = False
        existing_resources = {'images/icon.png': existing_resource}

        media_map = [{'file': 'images/icon.png', 'name': 'ICON', 'type': 'png', 'menuIcon': False}]

        _sync_resource_files_from_manifest(project, media_map, existing_resources)

        self.assertEqual(existing_resource.kind, 'png')
        existing_resource.save.assert_not_called()


class GithubPullDeltaAtomicityTest(TestCase):
    """Verifies that github_last_commit and github_last_sync are persisted in
    the same atomic transaction as the file-content changes, so a partial
    failure (or a worker kill) can never leave the project with new files but
    the old SHA, which would cause the next pull to re-apply the same delta.
    """

    def setUp(self):
        self.user = mock.MagicMock()
        self.project = mock.MagicMock()
        self.project.github_last_commit = 'oldsha'
        self.project.resources_path = 'resources'
        self.project.project_type = 'native'
        self.repo = mock.MagicMock()

    @mock.patch('ide.tasks.git._apply_delta_changes')
    @mock.patch('ide.tasks.git.validate_resources_against_tree')
    @mock.patch('ide.tasks.git.parse_manifest_from_tree')
    @mock.patch('ide.tasks.git.get_root_path')
    @mock.patch('ide.tasks.git.now')
    def test_delta_pull_passes_new_commit_sha_to_apply_delta_changes(
            self, mock_now, mock_get_root, mock_parse, mock_validate, mock_apply):
        """The new SHA must be passed through so _apply_delta_changes can
        stamp it inside the same atomic block as the file mutations."""
        mock_now.return_value = '2025-01-01T00:00:00Z'
        comparison = mock.MagicMock()
        comparison.ahead_by = 3
        comparison.files = [mock.MagicMock(filename='src/main.c', status='modified')]
        self.repo.compare.return_value = comparison

        mock_commit = mock.MagicMock()
        mock_commit.tree.sha = 'treesha'
        self.repo.get_git_commit.return_value = mock_commit
        mock_tree = mock.MagicMock()
        mock_tree.tree = []
        self.repo.get_git_tree.return_value = mock_tree

        mock_parse.return_value = ('', {'projectType': 'native'})
        mock_get_root.return_value = 'src/main.c'

        _github_pull_delta(self.user, self.project, self.repo, 'newsha')

        mock_apply.assert_called_once()
        args, kwargs = mock_apply.call_args
        self.assertEqual(args[5], 'newsha')

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    def test_apply_delta_changes_updates_github_last_commit_inside_atomic(
            self, mock_load, mock_sync):
        """When called with new_commit_sha, the SHA and last_sync must be
        assigned and saved *inside* the transaction.atomic() block."""
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        project.github_last_commit = 'oldsha'
        repo = mock.MagicMock()

        manifest = {'projectType': 'native', 'resources': {'media': []}}

        # Use a context-manager spy that records the project state at __enter__
        # and __exit__ so we can prove the SHA was set before the block exited.
        captured = {}

        class SpyAtomic:
            def __enter__(self_inner):
                captured['enter_github_last_commit'] = project.github_last_commit
                return self_inner

            def __exit__(self_inner, *args):
                captured['exit_github_last_commit'] = project.github_last_commit
                return False

        with mock.patch('ide.tasks.git.transaction.atomic', return_value=SpyAtomic()):
            project.source_files.all.return_value = []
            project.resources.all.return_value = []
            _apply_delta_changes(project, repo, '', manifest, [], new_commit_sha='newsha')

        self.assertEqual(captured['enter_github_last_commit'], 'oldsha')
        self.assertEqual(captured['exit_github_last_commit'], 'newsha')
        self.assertIsNotNone(project.github_last_sync)

    @mock.patch('ide.tasks.git._sync_resource_files_from_manifest')
    @mock.patch('ide.tasks.git.load_manifest_dict')
    def test_apply_delta_changes_does_not_touch_sha_when_omitted(
            self, mock_load, mock_sync):
        """When new_commit_sha is None (legacy call sites), the SHA must
        not be silently overwritten."""
        mock_load.return_value = ({}, {}, {})
        project = mock.MagicMock()
        project.resources_path = 'resources'
        project.project_type = 'native'
        project.github_last_commit = 'oldsha'
        repo = mock.MagicMock()

        manifest = {'projectType': 'native', 'resources': {'media': []}}

        with mock.patch('ide.tasks.git.transaction'):
            project.source_files.all.return_value = []
            project.resources.all.return_value = []
            _apply_delta_changes(project, repo, '', manifest, [])

        self.assertEqual(project.github_last_commit, 'oldsha')

    @mock.patch('ide.tasks.git._apply_delta_changes')
    @mock.patch('ide.tasks.git.validate_resources_against_tree')
    @mock.patch('ide.tasks.git.parse_manifest_from_tree')
    @mock.patch('ide.tasks.git.get_root_path')
    @mock.patch('ide.tasks.git.now')
    @mock.patch('ide.tasks.git.transaction.atomic')
    def test_delta_pull_ahead_by_zero_saves_inside_atomic(
            self, mock_atomic, mock_now, mock_get_root, mock_parse, mock_validate, mock_apply):
        """The 'no new commits' branch must also wrap its save in atomic()."""
        mock_atomic.return_value.__enter__ = mock.MagicMock()
        mock_atomic.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_now.return_value = '2025-01-01T00:00:00Z'
        comparison = mock.MagicMock()
        comparison.ahead_by = 0
        self.repo.compare.return_value = comparison

        _github_pull_delta(self.user, self.project, self.repo, 'newsha')

        mock_atomic.assert_called_once()
        self.assertEqual(self.project.github_last_commit, 'newsha')


class GithubPullFullAtomicityTest(TestCase):
    """Verifies that _github_pull_full stamps the new SHA in an atomic block
    after do_import_archive, so a project never ends up with new files but
    the old github_last_commit.
    """

    def setUp(self):
        self.user = mock.MagicMock()
        self.project = mock.MagicMock()
        self.project.github_last_commit = 'oldsha'
        self.project.resources_path = 'resources'
        self.project.project_type = 'native'
        self.repo = mock.MagicMock()

    @mock.patch('ide.tasks.git.do_import_archive')
    @mock.patch('ide.tasks.git.zipfile.is_zipfile', return_value=True)
    @mock.patch('ide.tasks.git.load_manifest_dict')
    @mock.patch('ide.tasks.git.find_project_root_and_manifest')
    @mock.patch('ide.tasks.git.urlopen')
    @mock.patch('ide.tasks.git.now')
    @mock.patch('ide.tasks.git.transaction.atomic')
    def test_full_pull_stamps_sha_in_atomic_block(
            self, mock_atomic, mock_now, mock_urlopen, mock_find_manifest, mock_load_manifest, mock_is_zipfile, mock_import):
        mock_atomic.return_value.__enter__ = mock.MagicMock()
        mock_atomic.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_now.return_value = '2025-01-01T00:00:00Z'

        branch = mock.MagicMock()
        branch.commit.sha = 'newsha'
        self.repo.default_branch = 'main'
        self.project.source_files.exists.return_value = False
        self.project.resources.exists.return_value = False

        commit = mock.MagicMock()
        commit.tree.sha = 'treesha'
        self.repo.get_git_commit.return_value = commit
        tree = mock.MagicMock()
        tree.tree = []
        self.repo.get_git_tree.return_value = tree
        self.repo.get_archive_link.return_value = 'https://example.com/zip'

        mock_manifest_item = mock.MagicMock()
        mock_manifest_item.path = 'package.json'
        mock_manifest_item.read.return_value = '{}'
        mock_find_manifest.return_value = ('', mock_manifest_item)
        mock_load_manifest.return_value = ({'project_type': 'native'}, [], [])
        mock_import.return_value = 'import_result'

        mock_response = mock.MagicMock()
        mock_response.__enter__ = mock.MagicMock(return_value=mock_response)
        mock_response.__exit__ = mock.MagicMock(return_value=False)
        mock_response.read.return_value = b'zip-bytes'
        mock_urlopen.return_value = mock_response

        result = _github_pull_full(self.user, self.project, self.repo, branch)

        self.assertEqual(result, 'import_result')
        mock_atomic.assert_called_once()
        self.assertEqual(self.project.github_last_commit, 'newsha')
        self.assertEqual(self.project.github_last_sync, '2025-01-01T00:00:00Z')
        self.project.save.assert_called_once()