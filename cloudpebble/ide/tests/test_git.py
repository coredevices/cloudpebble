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
        username, reponame = ide.git.url_to_repo("https://github.com/pebble/cloudpebble")
        self.assertEqual("pebble", username)
        self.assertEqual("cloudpebble", reponame)

    def test_strange_url_to_repo(self):
        username, reponame = ide.git.url_to_repo("git://github.com:foo/bar.git")
        self.assertEqual("foo", username)
        self.assertEqual("bar", reponame)

    def test_bad_url_to_repo(self):
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