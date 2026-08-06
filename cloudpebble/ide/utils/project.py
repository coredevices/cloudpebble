import logging
import abc
import json

from django.utils.translation import gettext as _

__author__ = 'katharine'


PACKAGE_MANIFEST = 'package.json'
APPINFO_MANIFEST = 'appinfo.json'
MANIFEST_KINDS = [PACKAGE_MANIFEST, APPINFO_MANIFEST]

# Directories that should never be treated as project roots.
# build/ contains waf build artifacts (including appinfo.json and auto-generated .c files).
# node_modules/ contains npm dependencies (which may have their own package.json with "pebble" keys).
_SKIP_DIRS = ('build/', 'node_modules/')


class InvalidProjectArchiveException(Exception):
    pass


class BaseProjectItem():
    """ A ProjectItem simply represents an item in a project archive which has a path
    and can be read. With custom implementations for BaseProjectItem, find_project_root_and_manifest
    is able to work identically on zip archives, git repos and automated tests """
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def read(self):
        """ This function should return the contents of the file/item as a string. """
        return None

    @abc.abstractproperty
    def path(self):
        """ This property should return the path to the item in the project. """
        return None


def is_manifest(kind, contents):
    """ A potentially valid manifest is a package.json file with a "pebble" object, or an appinfo.json file. """
    if kind == PACKAGE_MANIFEST:
        return 'pebble' in json.loads(contents)
    elif kind == APPINFO_MANIFEST:
        json.loads(contents)
        return True
    else:
        return False


def _dir_matches_hint(base_dir, root_hint):
    """ True if base_dir ('' or 'a/b/') is the root_hint directory, allowing
    at most ONE wrapping folder above it ('<repo>-<ref>/...' in GitHub zips).
    The wrapper limit matters: a bare suffix match would let a hint like
    'src' latch onto any directory of that name at any depth. """
    stripped = base_dir.rstrip('/')
    if stripped == root_hint:
        return True
    suffix = '/' + root_hint
    return stripped.endswith(suffix) and '/' not in stripped[:-len(suffix)]


def find_project_root_and_manifest(project_items, root_hint=None):
    """ Given the contents of an archive, find a valid Pebble project.
    :param project_items: A list of BaseProjectItems
    :param root_hint: If given, only accept a project whose directory is
        root_hint, relative to the archive's own root (archives from GitHub
        wrap everything in a '<repo>-<ref>/' folder, so the hint is matched
        against the tail of the directory). Used by /tree/<ref>/<subdir>
        imports to pick one project out of a repository that contains several.
    :return: A tuple of (path_to_project, manifest BaseProjectItem)
    """
    SRC_DIR = 'src/'
    invalid_package_path = None
    for item in project_items:
        base_dir = item.path

        # Skip manifests inside build artifacts or dependency directories.
        if any(('/' + d) in base_dir or base_dir.startswith(d) for d in _SKIP_DIRS):
            continue

        # Check if the file is one of the kinds of manifest file
        for name in MANIFEST_KINDS:
            dir_end = base_dir.rfind(name)
            if dir_end == -1:
                continue
            # Ensure that the file is actually a manifest file
            if dir_end + len(name) == len(base_dir):
                content = item.read()
                try:
                    if is_manifest(name, content):
                        manifest_item = item
                        break
                except ValueError as e:
                    invalid_package_path = item.path
        else:
            # If the file is not a manifest file, continue looking for the manfiest.
            continue

        # The base dir is the location of the manifest file without the manifest filename.
        base_dir = base_dir[:dir_end]

        # A root hint pins the project to one directory; manifests anywhere
        # else (e.g. the repository root) don't count.
        if root_hint and not _dir_matches_hint(base_dir, root_hint):
            continue

        # If we found a valid package.json, just return.
        if name == PACKAGE_MANIFEST:
            return base_dir, manifest_item

        # Otherwise if it's an appinfo.json, check that there is a a source directory containing
        # at least one source file.
        for source_item in project_items:
            source_dir = source_item.path
            if source_dir[:dir_end] != base_dir:
                continue
            if not source_dir.endswith('.c') and not source_dir.endswith('.js'):
                continue
            if source_dir[dir_end:dir_end + len(SRC_DIR)] != SRC_DIR:
                continue
            break
        else:
            # If there was no source directory with a source file, keep looking for manifest files.
            continue
        return base_dir, manifest_item

    # If we didn't find a valid project but we did find a broken manifest file, complain about it specifically.
    if root_hint:
        raise InvalidProjectArchiveException(
            _("No valid Pebble project found at '%s' in this repository." % root_hint))
    if invalid_package_path:
        raise InvalidProjectArchiveException(_("The file %s does not contain a valid JSON object." % invalid_package_path))
    else:
        raise InvalidProjectArchiveException(
            _(
                "No valid Pebble project root found. Expected either a package.json "
                "with a top-level 'pebble' object, or an appinfo.json with source "
                "files under src/."
            )
        )
