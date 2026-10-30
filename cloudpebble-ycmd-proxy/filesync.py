__author__ = 'katharine'

import os.path
import errno

# ycmd imports any file with this name that sits above a source file. The server
# writes the only legitimate one itself (ycm_helpers.spinup); user files may never
# create, rename onto, or patch one. npm config/lock files are blocked too, since
# npm_helpers runs npm in the project root.
EXTRA_CONF_NAME = '.ycm_extra_conf.py'
BLOCKED_NAMES = {EXTRA_CONF_NAME, '.npmrc', 'package-lock.json', 'npm-shrinkwrap.json'}


class FileSync(object):
    def __init__(self, root_dir):
        assert isinstance(root_dir, str)
        self.root_dir = root_dir

    def apply_patches(self, patch_sequence):
        # TODO: optimisations, if we care.
        # We can keep the files in memory
        # A sequence of patches probably all apply to the same file. We can optimise around this.
        # But does it matter?

        # The patches should arrive in order.
        patches = sorted(patch_sequence, key=lambda x: x['sequence'])

        for patch in patches:
            abs_path = self.abs_path(patch['filename'])

            with open(abs_path, encoding='utf-8') as f:
                lines = f.readlines()
                start = patch['start']
                end = patch['end']

                # Including everything up to the start line
                content = lines[:start['line']]
                # Merge the start line, replacement, and end line into a single line
                merged_line = ''
                if len(lines) > start['line']:
                    merged_line += lines[start['line']][:start['ch']]
                merged_line += "\n".join(patch['text'])
                if len(lines) > end['line']:
                    merged_line += lines[end['line']][end['ch']:]
                content.append(merged_line)
                # Add the lines from the end through to the end.
                if len(lines) > end['line'] + 1:
                    content.extend(lines[end['line'] + 1:])

            # Writeback.
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.writelines(content)

    def create_file(self, path, content):
        path = self.abs_path(path)
        dir_name = os.path.dirname(path)
        try:
            os.makedirs(dir_name)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(dir_name):
                pass
            else:
                raise
        with open(path, 'w') as f:
            f.write(content)

    def rename_file(self, path, new_path):
        path = self.abs_path(path)
        new_path = self.abs_path(new_path)
        if os.path.exists(new_path):
            raise Exception("Cannot rename file, path already exists")
        os.rename(path, new_path)

    def delete_file(self, path):
        path = self.abs_path(path)
        os.unlink(path)

    def abs_path(self, path):
        abs_path = os.path.normpath(os.path.join(self.root_dir, path))
        if os.path.commonpath([abs_path, self.root_dir]) != self.root_dir:
            raise Exception("Bad path")
        if os.path.basename(abs_path) in BLOCKED_NAMES:
            raise Exception("Bad path")
        return abs_path
