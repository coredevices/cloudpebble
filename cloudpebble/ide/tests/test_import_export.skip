""" These are integration tests. They create project archives, import them, export them, and then check that the manifest files are identical. """

import mock
import json

from ide.tasks.archive import do_import_archive
from ide.utils.cloudpebble_test import CloudpebbleTestCase, make_package, make_appinfo, build_bundle, read_bundle, override_settings

from ide.tasks.archive import create_archive
from utils.fakes import FakeS3

__author__ = 'joe'

fake_s3 = FakeS3()


@mock.patch('ide.tasks.archive.s3', fake_s3)
@mock.patch('ide.models.s3file.s3', fake_s3)
class TestImportExport(CloudpebbleTestCase):

    def setUp(self):
        self.login()
        self.maxDiff = None

    @staticmethod
    def make_custom_manifests(messageKeys):
        # We want to specify as many optional options as possible, in the hope that they all get exported
        # identically after being imported.
        npm_options = {
            'package_options': {
                'dependencies': {'some_package': '11.11.0'},
                'keywords': ['earth', 'wind', 'fire', 'water'],
            },
            'pebble_options': {
                'messageKeys': messageKeys
            }
        }
        appinfo_options = {
            'appKeys': messageKeys
        }
        return make_package(**npm_options), make_appinfo(appinfo_options)

    def runTest(self, manifest, import_manifest_name, expected_export_package_filename, expected_manifest=None):
        expected_manifest = expected_manifest or manifest
        bundle_file = build_bundle({
            'src/main.c': '',
            import_manifest_name: manifest
        })
        do_import_archive(self.project_id, bundle_file)
        create_archive(self.project_id)
        exported_manifest = read_bundle(fake_s3.read_last_file())[expected_export_package_filename]
        self.assertDictEqual(json.loads(expected_manifest), json.loads(exported_manifest))

    def test_import_then_export_npm_style(self):
        """ An imported then exported project manifest should remain identical, preserving all important data. """
        manifest, _ = self.make_custom_manifests(messageKeys={'key': 1, 'keytars': 2})
        self.runTest(manifest, 'package.json', 'test/package.json')

    def test_import_then_export_npm_style_with_new_messageKeys(self):
        """ We should be able to import and export SDK 3 projects with arrays for messageKeys """
        manifest, _ = self.make_custom_manifests(messageKeys=['keyLimePie', 'donkey[123]'])
        self.runTest(manifest, 'package.json', 'test/package.json')

    def test_import_preserves_manifest_resource_order(self):
        """Resource ID ordering must follow manifest.media order, not ZIP entry order."""
        package = json.loads(make_package(pebble_options={'messageKeys': ['dummy']}))
        package['pebble']['resources']['media'] = [
            {'type': 'bitmap', 'name': 'RES_1', 'file': 'images/1'},
            {'type': 'bitmap', 'name': 'RES_2', 'file': 'images/2'},
            {'type': 'bitmap', 'name': 'RES_3', 'file': 'images/3'},
            {'type': 'bitmap', 'name': 'RES_4', 'file': 'images/4'},
            {'type': 'bitmap', 'name': 'RES_5', 'file': 'images/5'},
            {'type': 'bitmap', 'name': 'RES_6', 'file': 'images/6'},
            {'type': 'bitmap', 'name': 'RES_7', 'file': 'images/7'},
            {'type': 'bitmap', 'name': 'RES_8', 'file': 'images/8'},
            {'type': 'bitmap', 'name': 'RES_9', 'file': 'images/9'},
            {'type': 'bitmap', 'name': 'RES_10', 'file': 'images/10'},
            {'type': 'bitmap', 'name': 'RES_11', 'file': 'images/11'},
            {'type': 'bitmap', 'name': 'RES_12', 'file': 'images/12'},
        ]
        manifest = json.dumps(package, indent=4, separators=(",", ": "), sort_keys=True) + "\n"

        # Intentionally scramble ZIP file entry order to verify import is manifest-order driven.
        bundle_file = build_bundle({
            'src/main.c': '',
            'package.json': manifest,
            'resources/images/9': '9',
            'resources/images/11': '11',
            'resources/images/7': '7',
            'resources/images/6': '6',
            'resources/images/1': '1',
            'resources/images/10': '10',
            'resources/images/8': '8',
            'resources/images/4': '4',
            'resources/images/3': '3',
            'resources/images/12': '12',
            'resources/images/2': '2',
            'resources/images/5': '5',
        })

        do_import_archive(self.project_id, bundle_file)
        create_archive(self.project_id)
        exported_manifest = json.loads(read_bundle(fake_s3.read_last_file())['test/package.json'])
        exported_media = exported_manifest['pebble']['resources']['media']

        self.assertEqual(
            [entry['file'] for entry in exported_media],
            [entry['file'] for entry in package['pebble']['resources']['media']]
        )
        self.assertEqual(
            [entry['name'] for entry in exported_media],
            [entry['name'] for entry in package['pebble']['resources']['media']]
        )
