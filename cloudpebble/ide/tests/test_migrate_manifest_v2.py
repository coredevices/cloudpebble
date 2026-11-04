import importlib
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

from ide.models.files import SourceFile
from ide.models.project import Project

migration = importlib.import_module('ide.migrations.0016_migrate_manifest_v2')


class TestMigrateManifestV2(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mv2', 'mv2@example.com', 'pw')

    def project(self, name, **kwargs):
        return Project.objects.create(owner=self.user, name=name, manifest_version=1, **kwargs)

    def run_migration(self):
        # Historical models, as the migration sees them; the live Project's __init__
        # reads deferred fields and recurses under .only().
        apps = MigrationExecutor(connection).loader.project_state([('ide', '0015_plugins_permissions')]).apps
        migration.migrate_projects(apps, mock.Mock(connection=connection))

    def test_adds_required_permissions_in_batches(self):
        pkjs = self.project('pkjs', uses_permissions=['Internet'])
        SourceFile.objects.create(project=pkjs, file_name='index.js', target='pkjs')
        health = self.project('health', app_capabilities='health,location', app_is_shown_on_communication=True)
        plain = self.project('plain')
        package = self.project('pkg', project_type='package')

        with mock.patch.object(migration, 'BATCH_SIZE', 2):
            self.run_migration()

        for p in (pkjs, health, plain, package):
            p.refresh_from_db()
        self.assertEqual(pkjs.manifest_version, 2)
        self.assertEqual(pkjs.uses_permissions, ['Internet', 'Location', 'Timeline'])
        self.assertEqual(health.uses_permissions, ['Location', 'Health', 'LegacyPebbleKit'])
        self.assertEqual(plain.manifest_version, 2)
        self.assertEqual(plain.uses_permissions, [])
        self.assertEqual(package.manifest_version, 1)
