import subprocess
import re

from elftools.elf.elffile import ELFFile
from elftools.dwarf.descriptions import describe_form_class

from . import ARM_CS_TOOLS

class LineReader(object):
    def __init__(self, elf_path):
        self.elf = elf_path

    def _exec_tool(self):
        output = subprocess.check_output([ARM_CS_TOOLS + "arm-none-eabi-objdump", "--dwarf=decodedline", self.elf])
        return output.decode('utf-8', errors='replace')

    def get_line_listing(self):
        decoded = self._exec_tool()

        # Hack: assume that any line some text ending in .c, followed by a
        # decimal integer and a hex integer is location information.

        lines = [
            {'file': x.group(1).strip(), 'line': int(x.group(2)), 'address': int(x.group(3), 16)}
            for x in re.finditer(r"(.*\.c)\s+(\d+)\s+(0x[0-9a-f]+)", decoded, re.MULTILINE)
        ]

        # New binutils prints "main.c:" instead of "CU: .../main.c:".
        # Derive the file table from the rows we actually reference so both
        # formats (and inlined source files) produce valid indices.
        files = list(dict.fromkeys(line['file'] for line in lines))

        return files, lines

    def get_compact_listing(self):
        files, lines = self.get_line_listing()

        # Now compact this into a handy compact listing (to save on file size)
        file_id_lookup = {files[x]: x for x in range(len(files))}

        compact_lines = [(x['address'], file_id_lookup[x['file']], x['line']) for x in lines]

        compact_lines.sort(key=lambda x: x[0])

        return {'files': files, 'lines': compact_lines}

class FunctionRange(object):
    def __init__(self, name, start, end, line=None):
        """
        Creates a representation of a function.

        @type name str
        @type start int
        @type end int
        @type line int
        """
        self.name = name
        self.start = start
        self.end = end
        self.line = line

    def __repr__(self):
        return "addr2lines.FunctionRange('%s', %s, %s, %s)" % (self.name, self.start, self.end, self.line)

class FunctionReader(object):
    """
    hello world
    """

    def __init__(self, elf_path):
        self.elf = elf_path

    def iter_info_groups(self):
        # DWARF 4/5 may encode high_pc as an offset, not an address. Read
        # its form instead of guessing from objdump's rendered number.
        with open(self.elf, 'rb') as stream:
            dwarf = ELFFile(stream).get_dwarf_info()
            for unit in dwarf.iter_CUs():
                for die in unit.iter_DIEs():
                    if die.tag != 'DW_TAG_subprogram':
                        continue
                    attrs = die.attributes
                    if 'DW_AT_low_pc' not in attrs or 'DW_AT_high_pc' not in attrs:
                        continue
                    origin = die
                    if 'DW_AT_name' not in attrs and 'DW_AT_abstract_origin' in attrs:
                        origin = die.get_DIE_from_attribute('DW_AT_abstract_origin')
                    name = origin.attributes.get('DW_AT_name')
                    if name is None:
                        continue
                    start = attrs['DW_AT_low_pc'].value
                    high = attrs['DW_AT_high_pc']
                    end = high.value
                    if describe_form_class(high.form) == 'constant':
                        end += start
                    line = origin.attributes.get('DW_AT_decl_line')
                    yield FunctionRange(name.value.decode('utf-8', errors='replace'),
                                        start, end, line.value if line else None)

    def get_info_groups(self):
        return list(self.iter_info_groups())

def create_coalesced_group(elf):
    dict = LineReader(elf).get_compact_listing()
    dict['functions'] = sorted([(x.start, x.end, x.name, x.line) for x in FunctionReader(elf).iter_info_groups()], key=lambda x: x[0])
    return dict
