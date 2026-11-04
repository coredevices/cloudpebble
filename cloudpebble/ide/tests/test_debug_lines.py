from unittest.mock import patch
from django.test import SimpleTestCase
from apptools.addr2lines import LineReader


class DebugLineTests(SimpleTestCase):
    def test_old_and_sdk443_file_headers(self):
        for header in ('CU: ../src/c/main.c:', 'main.c:'):
            with self.subTest(header=header), patch.object(LineReader, '_exec_tool', return_value=header + """
File name                        Line number    Starting address    View    Stmt
main.c                                     7                0xbe
main.c                                     6                0xbc       1       x
main.c                                     -               0x120
helper.c                                   9               0x130               x
"""):
                result = LineReader('unused.elf').get_compact_listing()
                self.assertEqual(result['files'], ['main.c', 'helper.c'])
                self.assertEqual(result['lines'], [(188, 0, 6), (190, 0, 7), (304, 1, 9)])

    def test_function_ranges_for_old_and_new_dwarf(self):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        from apptools.addr2lines import FunctionReader
        if not shutil.which('gcc') or not shutil.which('nm'):
            self.skipTest('gcc and nm are required for the DWARF compatibility fixture')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, 'fixture.c')
            source.write_text('int first(int x) { return x + 1; }\nint second(int x) { return first(x) + 2; }\n')
            for version in (2, 5):
                with self.subTest(dwarf=version):
                    obj = Path(directory, 'fixture.o')
                    subprocess.check_call(['gcc', '-gdwarf-%s' % version, '-O0', '-c', str(source), '-o', str(obj)])
                    symbols = subprocess.check_output(['nm', '-S', '--defined-only', str(obj)], text=True)
                    expected = {}
                    for row in symbols.splitlines():
                        start, size, kind, name = row.split()
                        if kind.lower() == 't':
                            expected[name] = (int(start, 16), int(start, 16) + int(size, 16))
                    actual = {fn.name: (fn.start, fn.end) for fn in FunctionReader(str(obj)).iter_info_groups()}
                    self.assertEqual(actual, expected)
                    self.assertGreater(actual['second'][0], 0)
