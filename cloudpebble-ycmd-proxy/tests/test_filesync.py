import os
import shutil
import tempfile
import unittest

from filesync import FileSync


class TestAbsPath(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.fs = FileSync(self.root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_normal_file(self):
        self.assertEqual(self.fs.abs_path('src/main.c'), os.path.join(self.root, 'src', 'main.c'))

    def test_rejects_traversal(self):
        with self.assertRaises(Exception):
            self.fs.abs_path('../escape.c')

    def test_rejects_sibling_with_shared_prefix(self):
        # startswith() accepted /tmp/tmpabc123 + "../tmpabc123x/f"; commonpath must not.
        with self.assertRaises(Exception):
            self.fs.abs_path('../' + os.path.basename(self.root) + 'x/f.c')

    def test_rejects_extra_conf_anywhere(self):
        for path in ('.ycm_extra_conf.py', 'src/.ycm_extra_conf.py', 'src/a/../.ycm_extra_conf.py'):
            with self.assertRaises(Exception):
                self.fs.abs_path(path)

    def test_rejects_npm_config_files(self):
        for path in ('.npmrc', 'package-lock.json', 'npm-shrinkwrap.json', 'src/.npmrc'):
            with self.assertRaises(Exception):
                self.fs.abs_path(path)

    def test_create_file_cannot_plant_extra_conf(self):
        with self.assertRaises(Exception):
            self.fs.create_file('src/.ycm_extra_conf.py', 'import os')
        self.assertFalse(os.path.exists(os.path.join(self.root, 'src', '.ycm_extra_conf.py')))

    def test_rename_onto_extra_conf_rejected(self):
        self.fs.create_file('src/x.py', 'pass')
        with self.assertRaises(Exception):
            self.fs.rename_file('src/x.py', 'src/.ycm_extra_conf.py')


if __name__ == '__main__':
    unittest.main()
