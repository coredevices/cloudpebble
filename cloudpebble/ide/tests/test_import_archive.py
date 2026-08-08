""" These tests check basic operation of ide.tasks.archive.do_import_archive """
import mock

from django.core.exceptions import ValidationError

from ide.tasks.archive import do_import_archive, InvalidProjectArchiveException
from ide.utils.cloudpebble_test import CloudpebbleTestCase, make_package, make_appinfo, build_bundle, override_settings
from ide.models.project import Project
from ide.models.files import SourceFile
from ide.utils.regexes import regexes
from utils.fakes import FakeS3

__author__ = 'joe'

fake_s3 = FakeS3()


@mock.patch('ide.models.s3file.s3', fake_s3)
class TestImportArchive(CloudpebbleTestCase):
    def setUp(self):
        self.login()

    @staticmethod
    def make_resource_spec(name='IMAGE_BLAH'):
        return {
            'resources': {
                'media': [{
                    'file': 'images/blah.png',
                    'name': name,
                    'type': 'bitmap'
                }]
            }
        }

    def test_import_basic_bundle_with_appinfo(self):
        """ Check that a minimal bundle imports without error """
        bundle = build_bundle({
            'src/main.c': '',
            'appinfo.json': make_appinfo()
        })
        do_import_archive(self.project_id, bundle)

    def test_throws_with_invalid_appinfo(self):
        """ Check that appinfo validation is performed with a few invalid values """
        invalid_things = [
            ('projectType', 'invalid'),
            ('versionLabel', '01.0'),
        ]
        for k, v in invalid_things:
            bundle = build_bundle({
                'src/main.c': '',
                'appinfo.json': make_appinfo({k: v})
            })
            with self.assertRaises(ValidationError):
                do_import_archive(self.project_id, bundle)

    def test_import_basic_bundle_with_npm_manifest(self):
        """ Check that archives with package.json can be imported """
        bundle = build_bundle({
            'src/main.c': '',
            'package.json': make_package(package_options={'name': 'myproject'})
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.app_long_name, 'test')
        self.assertEqual(project.app_short_name, 'myproject')

    def test_import_package_with_dependencies(self):
        """ Check that dependencies in a package.json file are imported into the database """
        deps = {
            'some_package': '3.14.15',
            'another': 'http://blah.com/package.git',
        }
        bundle = build_bundle({
            'src/main.c': '',
            'package.json': make_package(package_options={
                'dependencies': deps
            })
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        actual_deps = {d.name: d.version for d in project.dependencies.all()}
        self.assertDictEqual(actual_deps, deps)

    def test_import_package_with_invalid_uuid_generates_new_uuid4(self):
        invalid_uuid = 'b2c3d4e5-2345-6789-bcde-f01234567890'
        bundle = build_bundle({
            'src/main.c': '',
            'package.json': make_package(pebble_options={'uuid': invalid_uuid})
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertNotEqual(project.app_uuid, invalid_uuid)
        self.assertRegex(project.app_uuid, regexes.uuid)

    def test_import_package_with_keywords(self):
        """ Check that keywords in a package.json file are imported into the database """
        keywords = ['pebbles', 'watch', 'bunnies']
        bundle = build_bundle({
            'src/main.c': '',
            'package.json': make_package(package_options={
                'keywords': keywords
            })
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(set(keywords), set(project.keywords))

    def test_import_appinfo_with_resources(self):
        """ Check that a resource can be imported in an appinfo.json project """
        bundle = build_bundle({
            'src/main.c': '',
            'resources/images/blah.png': 'contents!',
            'appinfo.json': make_appinfo(options=self.make_resource_spec())
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.resources.get().variants.get().get_contents(), 'contents!')

    def test_import_package_with_resources(self):
        """ Check that a resource can be imported in an package.json project """
        bundle = build_bundle({
            'src/main.c': '',
            'resources/images/blah.png': 'contents!',
            'package.json': make_package(pebble_options=self.make_resource_spec())
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.resources.get().variants.get().get_contents(), 'contents!')

    def test_throws_with_local_file_dependencies(self):
        """ Throw if any dependencies reference local files """
        bad_versions = [
            'file:security/breach',
            '/security/breach',
            './security/breach',
            '../security/breach',
            '~/security/breach'
        ]
        for version in bad_versions:
            bundle = build_bundle({
                'src/main.c': '',
                'package.json': make_package(package_options={
                    'dependencies': {'some_package': version}
                })
            })
            with self.assertRaises(ValidationError):
                do_import_archive(self.project_id, bundle)

    def test_invalid_resource_id(self):
        """ Check that invalid characters are banned from resource IDs """
        bundle = build_bundle({
            'src/main.c': '',
            'resources/images/blah.png': 'contents!',
            'package.json': make_package(pebble_options=self.make_resource_spec("<>"))
        })

        with self.assertRaises(ValidationError):
            do_import_archive(self.project_id, bundle)

    def test_import_json_file(self):
        """ Check that json files are correctly imported """
        bundle = build_bundle({
            'src/js/test.json': '{}',
            'src/main.c': '',
            'package.json': make_package()
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.filter(file_name='test.json').count(), 1)

    def test_import_rocky(self):
        """ Check that json files are correctly imported """
        bundle = build_bundle({
            'src/rocky/index.js': '',
            'src/common/lib.js': '',
            'src/pkjs/app.js': '',
            'package.json': make_package(pebble_options={'projectType': 'rocky'})
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.filter(file_name='index.js', target='app').count(), 1)
        self.assertEqual(project.source_files.filter(file_name='lib.js', target='common').count(), 1)
        self.assertEqual(project.source_files.filter(file_name='app.js', target='pkjs').count(), 1)

    def test_import_alloy_binary_embedded_assets(self):
        bundle = build_bundle({
            'src/c/mdbl.c': 'int main(void) { return 0; }',
            'src/embeddedjs/main.js': 'trace("ok");',
            'src/embeddedjs/manifest.json': '{}',
            'src/embeddedjs/hours.pdc': 'PDC',
            'src/embeddedjs/emery/dial.png': b'\x89PNG\r\n',
            'package.json': make_package(pebble_options={'projectType': 'alloy'})
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        project_files = {(f.file_name, f.target): f for f in project.source_files.all()}
        self.assertIn(('hours.pdc', 'embeddedjs'), project_files)
        self.assertIn(('emery/dial.png', 'embeddedjs'), project_files)
        self.assertTrue(project_files[('hours.pdc', 'embeddedjs')].is_binary_source)
        self.assertTrue(project_files[('emery/dial.png', 'embeddedjs')].is_binary_source)

        dial_file = SourceFile.objects.get(project=project, file_name='emery/dial.png', target='embeddedjs')
        self.assertEqual(dial_file.get_contents(), b'\x89PNG\r\n')


@mock.patch('ide.models.s3file.s3', fake_s3)
class TestImportLibrary(CloudpebbleTestCase):
    def setUp(self):
        self.login(type='package')

    def test_import_basic_library(self):
        """ Try importing a basic library """
        bundle = build_bundle({
            'include/my-lib.h': '',
            'package.json': make_package(pebble_options={'projectType': 'package'}),
            'src/c/my-lib.c': '',
            'src/c/my-priv.h': '',
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        files = {f.file_name: f for f in project.source_files.all()}
        self.assertSetEqual(set(files.keys()), {'my-lib.h', 'my-lib.c', 'my-priv.h'})
        self.assertEqual(files['my-lib.h'].target, 'public')
        self.assertEqual(files['my-lib.c'].target, 'app')
        self.assertEqual(files['my-priv.h'].target, 'app')

    def test_import_library_with_resources(self):
        """ Try importing a basic library with resources """
        bundle = build_bundle({
            'package.json': make_package(pebble_options={
                'projectType': 'package',
                'resources': {'media': [{
                    'type': 'bitmap',
                    'name': 'MY_RES1',
                    'file': 'res1.png'
                }, {
                    'type': 'bitmap',
                    'name': 'MY_RES2',
                    'file': 'res2.png'
                }]}
            }),
            'src/resources/res1.png': '',
            'src/resources/res2.png': '',
        })
        do_import_archive(self.project_id, bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertSetEqual({f.file_name for f in project.resources.all()}, {'res1.png', 'res2.png'})


@mock.patch('ide.models.s3file.s3', fake_s3)
class TestWipeExisting(CloudpebbleTestCase):
    def setUp(self):
        self.login()

    def test_file_limit_ignores_files_outside_project_root(self):
        """A GitHub zipball can contain many files that aren't part of the
        project (docs, screenshots, etc). Only files inside the project root
        count against the 400-file limit."""
        spec = {
            'repo/project/src/main.c': '',
            'repo/project/appinfo.json': make_appinfo()
        }
        for i in range(450):
            spec['repo/screenshots/shot%d.png' % i] = 'not-a-real-png'
        # Directory entries (as GitHub zipballs contain) don't count either.
        for i in range(450):
            spec['repo/project/src/dir%d/' % i] = ''
        do_import_archive(self.project_id, build_bundle(spec))
        self.assertEqual(Project.objects.get(pk=self.project_id).source_files.count(), 1)

    def test_file_limit_applies_to_project_files(self):
        """More than 400 files inside the project root is rejected."""
        spec = {
            'src/main.c': '',
            'appinfo.json': make_appinfo()
        }
        for i in range(450):
            spec['src/extra%d.h' % i] = ''
        with self.assertRaises(InvalidProjectArchiveException):
            do_import_archive(self.project_id, build_bundle(spec))

    def test_wipe_existing_replaces_source_files(self):
        """Importing with wipe_existing=True replaces existing source files"""
        first_bundle = build_bundle({
            'src/main.c': '// original',
            'src/utils.c': '// utils',
            'appinfo.json': make_appinfo()
        })
        do_import_archive(self.project_id, first_bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.count(), 2)

        second_bundle = build_bundle({
            'src/replaced.c': '// replaced',
            'appinfo.json': make_appinfo()
        })
        do_import_archive(self.project_id, second_bundle, wipe_existing=True)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.count(), 1)
        self.assertEqual(project.source_files.first().file_name, 'replaced.c')

    def test_wipe_existing_replaces_resources(self):
        """Importing with wipe_existing=True replaces existing resources"""
        first_bundle = build_bundle({
            'src/main.c': '',
            'resources/images/blah.png': 'original!',
            'appinfo.json': make_appinfo(options={
                'resources': {
                    'media': [{
                        'file': 'images/blah.png',
                        'name': 'IMAGE_BLAH',
                        'type': 'bitmap'
                    }]
                }
            })
        })
        do_import_archive(self.project_id, first_bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.resources.count(), 1)

        second_bundle = build_bundle({
            'src/main.c': '',
            'resources/images/new.png': 'new!',
            'appinfo.json': make_appinfo(options={
                'resources': {
                    'media': [{
                        'file': 'images/new.png',
                        'name': 'IMAGE_NEW',
                        'type': 'bitmap'
                    }]
                }
            })
        })
        do_import_archive(self.project_id, second_bundle, wipe_existing=True)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.resources.count(), 1)
        self.assertEqual(project.resources.first().file_name, 'new.png')

    def test_wipe_existing_false_keeps_files(self):
        """Importing with wipe_existing=False (default) does not delete existing files"""
        first_bundle = build_bundle({
            'src/main.c': '// original',
            'appinfo.json': make_appinfo()
        })
        do_import_archive(self.project_id, first_bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.count(), 1)

        second_bundle = build_bundle({
            'src/added.c': '// added',
            'appinfo.json': make_appinfo()
        })
        do_import_archive(self.project_id, second_bundle, wipe_existing=False)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.count(), 2)

    def test_wipe_existing_rolls_back_on_failure(self):
        """If wipe_existing=True and import fails, original files are preserved"""
        first_bundle = build_bundle({
            'src/main.c': '// original',
            'appinfo.json': make_appinfo()
        })
        do_import_archive(self.project_id, first_bundle)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.count(), 1)

        bad_bundle = b'this is not a valid zip file'
        with self.assertRaises(Exception):
            do_import_archive(self.project_id, bad_bundle, wipe_existing=True)
        project = Project.objects.get(pk=self.project_id)
        self.assertEqual(project.source_files.count(), 1,
                         "Original files should be preserved after failed import")
