import io
import zipfile
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from ide.models import Project, SourceFile
from ide.utils.sdk.manifest import generate_v3_manifest_dict, load_manifest_dict
from ide.utils.sdk.project_assembly import assemble_project
from ide.utils.project import PACKAGE_MANIFEST
from ide.tasks.archive import do_import_archive, add_project_to_archive
from ide.utils.microphone_templates import build_microphone_archive


@override_settings(AWS_ENABLED=False)
class PluginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('plugin-test')
        self.project = Project.objects.create(owner=self.user, name='Test', app_short_name='Test', app_long_name='Test', app_company_name='Test', app_platforms='emery')

    def test_manifest_round_trip(self):
        self.project.plugin = {'script': 'plugin.js', 'sources': [], 'oauth': {'example': {}}}
        self.project.config_page = 'config.html'
        self.project.uses_permissions = ['WatchMicrophone', {'name': 'Internet', 'parameters': {'domains': ['example.com']}}]
        self.project.app_is_shown_on_communication = True
        self.project.save()
        manifest = generate_v3_manifest_dict(self.project, [])
        loaded, _, _ = load_manifest_dict(manifest, PACKAGE_MANIFEST)
        for field in ('plugin', 'config_page', 'uses_permissions', 'manifest_version', 'app_is_shown_on_communication'):
            self.assertEqual(loaded[field], getattr(self.project, field))

    def test_legacy_import_and_new_project_defaults(self):
        manifest = generate_v3_manifest_dict(self.project, [])
        manifest['pebble'].pop('manifestVersion')
        manifest['pebble'].pop('usesPermissions')
        self.assertEqual(load_manifest_dict(manifest, PACKAGE_MANIFEST)[0]['manifest_version'], 1)
        self.assertEqual(self.project.manifest_version, 2)

    def test_invalid_v1_feature_combination(self):
        self.project.manifest_version = 1
        self.project.uses_permissions = ['WatchMicrophone']
        with self.assertRaises(ValidationError):
            self.project.full_clean()

    def test_source_paths(self):
        for project_type in ('native', 'alloy', 'plugin'):
            for path, target in [('plugin.js', 'plugin'), ('config.html', 'config'), ('settings/page.html', 'config'), ('plugin/helper.json', 'plugin')]:
                self.assertEqual(SourceFile.get_details_for_path(project_type, path), (path, target))
        for path in ('../escape.js', '/escape.js', 'build/plugin.js', 'package.json', 'a/../../escape.html'):
            with self.assertRaises(ValueError, msg=path):
                SourceFile.get_details_for_path('plugin', path)

    def test_message_keys_validation(self):
        for keys in (['FOO', 'FOO[2]'], ['FOO[0]'], {'A': None}, {'A': 1, 'B': 1}):
            self.project.app_keys = json.dumps(keys)
            with self.assertRaises(ValidationError):
                self.project.full_clean()

    @patch('ide.api.project.send_td_event')
    def test_create_plugin_api(self, _):
        self.client.force_login(self.user)
        response = self.client.post('/ide/project/create', {'name': 'Hello plugin', 'type': 'plugin', 'template': '0'})
        self.assertEqual(response.status_code, 200, response.content)
        project = Project.objects.get(pk=response.json()['id'])
        self.assertEqual(project.project_type, 'plugin')
        self.assertEqual(project.manifest_version, 2)
        self.assertEqual(set(project.source_files.values_list('file_name', flat=True)), {'plugin.js', 'config.html'})
        with tempfile.TemporaryDirectory() as directory:
            assemble_project(project, directory, None)
            self.assertTrue(Path(directory, 'plugin.js').is_file())
            manifest = json.loads(Path(directory, 'package.json').read_text())
            self.assertNotIn('watchapp', manifest['pebble'])
            self.assertNotIn('targetPlatforms', manifest['pebble'])

    def test_microphone_template_import(self):
        for kind in ('capture', 'stream'):
            do_import_archive(self.project.id, build_microphone_archive('microphone/' + kind), wipe_existing=True)
            self.project.refresh_from_db()
            self.assertEqual(self.project.uses_permissions, ['WatchMicrophone'])
            self.assertEqual(self.project.manifest_version, 2)
            self.assertEqual(self.project.app_platform_list, ['emery', 'flint', 'gabbro'])

    @patch('ide.api.project.send_td_event')
    def test_plugin_archive_round_trip(self, _):
        self.client.force_login(self.user)
        response = self.client.post('/ide/project/create', {'name': 'Export plugin', 'type': 'plugin', 'template': '0'})
        original = Project.objects.get(pk=response.json()['id'])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            add_project_to_archive(archive, original)
        do_import_archive(self.project.id, buffer.getvalue(), wipe_existing=True)
        self.project.refresh_from_db()
        self.assertEqual(self.project.project_type, 'plugin')
        self.assertEqual(self.project.plugin, original.plugin)
        self.assertEqual(self.project.config_page, 'config.html')
        self.assertEqual(self.project.manifest_version, 2)
        self.assertEqual(set(self.project.source_files.values_list('file_name', flat=True)), {'plugin.js', 'config.html'})

    def test_invalid_settings_returns_error_without_writing(self):
        self.client.force_login(self.user)
        response = self.client.post('/ide/project/%s/save_settings' % self.project.id,
                                   {'manifest_version': 'not-a-number'})
        self.assertEqual(response.status_code, 400)
        self.project.refresh_from_db()
        self.assertEqual(self.project.manifest_version, 2)

    @patch('ide.tasks.git.do_import_archive')
    @patch('ide.tasks.git.urlopen')
    @patch('ide.tasks.git.file_exists', return_value=True)
    @patch('ide.tasks.git.get_authenticated_archive_url', return_value=None)
    @patch('ide.tasks.git.Github')
    def test_github_import_uses_repository_default_branch(self, github, auth, exists, urlopen, imported):
        from ide.tasks.git import do_import_github
        github.return_value.get_repo.return_value.default_branch = 'main'
        urlopen.return_value.read.return_value = b'archive'
        do_import_github(self.project.id, 'example', 'repository', '')
        urlopen.assert_called_once_with('https://github.com/example/repository/archive/main.zip')
        imported.assert_called_once_with(self.project.id, b'archive')


@override_settings(AWS_ENABLED=False)
class PermissionMigrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('migration-test')

    def project(self, **kwargs):
        return Project.objects.create(owner=self.user, name='Legacy', manifest_version=1, **kwargs)

    def test_migration_preserves_parameters_and_declares_legacy_access(self):
        from ide.utils.permissions import migrate_manifest_v2
        project = self.project(app_capabilities='health', app_is_shown_on_communication=True)
        SourceFile.objects.create(project=project, file_name='app.js', target='pkjs')
        project.uses_permissions = [{'name': 'Internet', 'parameters': {'domains': ['example.com']}}]
        migrate_manifest_v2(project)
        self.assertEqual(project.manifest_version, 2)
        self.assertEqual(project.uses_permissions, [
            {'name': 'Internet', 'parameters': {'domains': ['example.com']}},
            'Location', 'Timeline', 'Health', 'LegacyPebbleKit'])
        migrate_manifest_v2(project)
        self.assertEqual(len(project.uses_permissions), 5)

    def test_plain_watchapp_gets_no_unneeded_permissions(self):
        from ide.utils.permissions import migrate_manifest_v2
        project = self.project()
        migrate_manifest_v2(project)
        self.assertEqual(project.manifest_version, 2)
        self.assertEqual(project.uses_permissions, [])

    def test_database_migration(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        project = self.project(project_type='pebblejs')
        with connection.schema_editor() as editor:
            importlib.import_module('ide.migrations.0016_migrate_manifest_v2').migrate_projects(apps, editor)
        project.refresh_from_db()
        self.assertEqual(project.manifest_version, 2)
        self.assertEqual(project.uses_permissions, ['Internet', 'Location', 'Timeline'])

    def test_legacy_import_migrates_after_loading_sources(self):
        project = self.project()
        buffer = io.BytesIO()
        manifest = {'name': 'legacy', 'author': 'test', 'version': '1.0.0',
                    'pebble': {'uuid': project.app_uuid, 'displayName': 'Legacy',
                               'messageKeys': [], 'targetPlatforms': ['emery']}}
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('package.json', json.dumps(manifest))
            archive.writestr('src/pkjs/index.js', 'console.log("legacy");')
        do_import_archive(project.id, buffer.getvalue(), wipe_existing=True)
        project.refresh_from_db()
        self.assertEqual(project.manifest_version, 2)
        self.assertEqual(project.uses_permissions, ['Internet', 'Location', 'Timeline'])
