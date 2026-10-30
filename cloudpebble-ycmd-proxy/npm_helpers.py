import contextlib
import json
import os
import re
import shutil
import subprocess
import zipfile
import settings
from projectinfo import Resource


class NPMInstallError(Exception):
    pass


@contextlib.contextmanager
def temporary_package_json(root_dir, dependencies):
    package_path = os.path.join(root_dir, 'package.json')
    try:
        with open(package_path, 'w') as f:
            json.dump({
                "name": "cloudpebble-ycmd-proxy",
                "version": "1.0.0",
                "description": "A temporary package.json",
                "repository": None,
                "license": "",
                "dependencies": dependencies
            }, f)
        yield
    finally:
        os.unlink(package_path)


def validate_dependencies(dependencies):
    """ Check that none of the version strings in a dictionary of dependencies reference local paths. """
    # CloudPebble performs identical checks for this, so hopefully it should never actually get triggered.
    for version in dependencies.values():
        if re.match(r'^file:|(\.*|~)/', version):
            raise ValueError("Dependencies are not allowed to reference paths")


def _npm(root_dir, *args):
    """ Run npm without lifecycle scripts. prune, install and dedupe all reify
    node_modules, which runs install scripts by default, and the dependencies are
    user-chosen. The env var outranks a project .npmrc; the flags outrank both. """
    env = dict(os.environ, npm_config_ignore_scripts="true")
    subprocess.check_output([settings.NPM_BINARY, *args, "--ignore-scripts", "--no-bin-links"],
                            stderr=subprocess.STDOUT, cwd=root_dir, env=env)


def install_dependencies(dependencies, root_dir):
    """ Install some npm dependencies into a directory and then extract the headers
    :param dependencies: a dictionary of name->version
    :param root_dir: the directory to install into
    """
    validate_dependencies(dependencies)
    # Make a minimal package.json file
    with temporary_package_json(root_dir, dependencies):
        try:
            # Install all the dependencies
            # TODO: Should NPM itself have resource limits?
            _npm(root_dir, "prune")
            if dependencies:
                _npm(root_dir, "install")
                _npm(root_dir, "dedupe")
        except subprocess.CalledProcessError:
            # Setting the error message to e.output here would let the user see their lovely NPM error output.
            raise NPMInstallError("One or more of your dependencies cannot be installed. Please check that the names and versions for all of your dependencies are valid.")


def search_node_modules(base, filename, folder='node_modules'):
    search_root = os.path.join(base, folder)
    for dirname, _, filenames in os.walk(search_root):
        if filename in filenames:
            path = os.path.join(dirname, filename)
            libname = os.path.dirname(os.path.relpath(path, search_root))
            yield libname, path


def get_package_metadata(root_dir):
    """ Given a directory with a node_modules directory full of pebble modules, get all of their messageKeys and resource type/name information
    :param root_dir:
    :return: (array of resources, array of (type, name) tuples
    """
    resources = []
    messagekeys = []
    versions = {}
    for libname, package_path in search_node_modules(root_dir, 'package.json'):
        with open(package_path, 'r') as f:
            data = json.load(f)
            if 'pebble' not in data:
                continue
            messagekeys.extend(data.get('pebble', {}).get('messageKeys', []))
            resources.extend(Resource(r['type'], r['name']) for r in data.get('pebble', {}).get('resources', {}).get('media', []))
            versions[libname] = data.get('version', None)
    return resources, messagekeys, versions


def extract_library_headers(root_dir):
    """ Given a directory with a node_modules directory full of Pebble modules, extract all of their header files into ./librares/include/<module_name>
    :param root_dir: base directory
    """
    # Make the libraries directory if it does not exist
    libs_path = os.path.join(root_dir, 'libraries')
    if os.path.isdir(libs_path):
        shutil.rmtree(libs_path)
    os.mkdir(libs_path)
    # Look for C modules with dist.zip files
    for libname, zip_path in search_node_modules(root_dir, 'dist.zip'):
        try:
            # Construct the expected path to the library's headers based on its name
            includes_path = os.path.join('include', libname)
            with zipfile.ZipFile(zip_path) as z:
                # Extract any header files which are inside 'include/<module_name>'
                for zip_entry in z.infolist():
                    if zip_entry.filename.startswith(includes_path) and zip_entry.filename.endswith('.h'):
                        extracted_to = z.extract(zip_entry, libs_path)
                        if not extracted_to.endswith('auto.h'):
                            yield os.path.relpath(extracted_to, os.path.join(libs_path, 'include'))

        except Exception:
            raise NPMInstallError("One or more of your dependencies is not a valid pebble library.")


def make_library_info(dependencies, versions, headers):
    libs = {}
    for name, version in versions.items():
        if version and name in dependencies:
            libs[name] = {
                'headers': [],
                'version': version
            }

    for header in headers:
        dep = header.startswith(tuple(dependencies))
        if dep and dep in libs:
            libs[dep]['headers'].append(header)
    return libs


def setup_dependencies(dependencies, root_dir):
    install_dependencies(dependencies, root_dir)
    lib_headers = extract_library_headers(root_dir)
    lib_resources, lib_messagekeys, lib_versions = get_package_metadata(root_dir)
    lib_info = make_library_info(dependencies, lib_versions, lib_headers)
    return lib_info, lib_messagekeys, lib_resources


def try_setup_dependencies(dependencies, root_dir):
    try:
        return setup_dependencies(dependencies, root_dir), None
    except NPMInstallError as e:
        return ({}, [], []), str(e)
