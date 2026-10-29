import io
import os
import shutil
import tempfile
import zipfile
import mock

from django.test import TestCase

from ide.utils.c_templates import list_c_templates, build_c_template_archive


class TestCTemplates(TestCase):
    def setUp(self):
        self.tutorial_root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tutorial_root)

    def _write_part(self, part_name, include_main=True):
        part_root = os.path.join(self.tutorial_root, part_name)
        os.makedirs(part_root)
        with open(os.path.join(part_root, 'package.json'), 'w') as handle:
            handle.write('{"name":"%s"}' % part_name)
        os.makedirs(os.path.join(part_root, 'src', 'c'))
        if include_main:
            with open(os.path.join(part_root, 'src', 'c', 'main.c'), 'w') as handle:
                handle.write('int main(void) { return 0; }\n')
        return part_root

    def test_list_c_templates_includes_builtins_when_checkout_missing(self):
        with mock.patch('ide.utils.c_templates._watchface_tutorial_root', return_value='/tmp/unused'):
            self.assertEqual([t['id'] for t in list_c_templates()], ['microphone/capture', 'microphone/stream'])

    def test_list_c_templates_discovers_and_sorts_parts(self):
        self._write_part('part3')
        self._write_part('part1')
        self._write_part('part2')
        self._write_part('part4', include_main=False)
        self._write_part('examples')

        with mock.patch('ide.utils.c_templates._watchface_tutorial_root', return_value=self.tutorial_root):
            templates = list_c_templates()

        self.assertEqual([t['id'] for t in templates[-2:]], ['microphone/capture', 'microphone/stream'])
        templates = templates[:-2]
        ids = [template['id'] for template in templates]
        self.assertEqual(
            ids,
            [
                'watchface-tutorial/part1',
                'watchface-tutorial/part2',
                'watchface-tutorial/part3',
            ],
        )
        labels = [template['label'] for template in templates]
        self.assertEqual(labels, ['Your First Watchface', 'Customizing Your Watchface', 'Battery Meter and Bluetooth'])
        groups = [template['group'] for template in templates]
        self.assertEqual(groups, ['watchface-tutorial/'] * 3)

    def test_build_c_template_archive_contains_project_files(self):
        self._write_part('part1')

        with mock.patch('ide.utils.c_templates._watchface_tutorial_root', return_value=self.tutorial_root):
            archive_bytes = build_c_template_archive('watchface-tutorial/part1')

        with zipfile.ZipFile(io.BytesIO(archive_bytes), 'r') as zf:
            names = set(zf.namelist())

        self.assertIn('package.json', names)
        self.assertIn('src/c/main.c', names)

    def test_build_c_template_archive_rejects_invalid_path(self):
        self._write_part('part1')
        with mock.patch('ide.utils.c_templates._watchface_tutorial_root', return_value=self.tutorial_root):
            with self.assertRaises(ValueError):
                build_c_template_archive('../outside')
