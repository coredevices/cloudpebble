import json
import os
import re
import shutil

from django.conf import settings

from ide.models import ResourceFile
from ide.utils.crypto import decrypt_value
from .manifest import manifest_name_for_project, generate_manifest_dict
from ide.utils.sdk import generate_wscript_file, generate_jshint_file


def assemble_source_files(project, base_dir):
    """ Copy all the source files for a project into a project directory """
    source_files = project.source_files.all()
    for f in source_files:
        target_dir = os.path.join(base_dir, f.project_dir)
        abs_target = os.path.abspath(os.path.join(target_dir, f.file_name))
        if not abs_target.startswith(target_dir):
            raise Exception("Suspicious filename: %s" % f.file_name)
        abs_target_dir = os.path.dirname(abs_target)
        if not os.path.exists(abs_target_dir):
            os.makedirs(abs_target_dir)
        f.copy_to_path(abs_target)


def assemble_simplyjs_sources(project, base_dir, build_result):
    """ Concatenate all JS files in the project into one file and add it to the project directory """
    source_files = project.source_files.all()
    shutil.rmtree(base_dir)
    shutil.copytree(settings.SIMPLYJS_ROOT, base_dir)

    js = '\n\n'.join(x.get_contents() for x in source_files if x.file_name.endswith('.js'))
    escaped_js = json.dumps(js)
    build_result.save_simplyjs(js)

    with open(os.path.join(base_dir, 'src', 'js', 'zzz_userscript.js'), 'w') as f:
        f.write("""
    (function() {
        simply.mainScriptSource = %s;
    })();
    """ % escaped_js)


def assemble_resource_directories(project, base_dir):
    """ Create images/fonts/data resource directories for the project. """
    resource_path = os.path.join(base_dir, project.resources_path)
    os.makedirs(os.path.join(resource_path, 'images'))
    os.makedirs(os.path.join(resource_path, 'fonts'))
    os.makedirs(os.path.join(resource_path, 'data'))


def assemble_resources(base_dir, resource_path, resources, type_restrictions=None):
    """ Copy all the project's resources to a path, optionally filtering by type. """
    for f in resources:
        if type_restrictions and f.kind not in type_restrictions:
            continue
        target_dir = os.path.abspath(os.path.join(base_dir, resource_path, ResourceFile.DIR_MAP[f.kind]))
        f.copy_all_variants_to_dir(target_dir)


def _inject_env_vars(base_dir, project, env_map):
    """Replace process.env.KEY references in pkjs source files with actual values."""
    from ide.models.files import SourceFile

    pattern = re.compile(r'process\.env\.([a-zA-Z_][a-zA-Z0-9_]*)')
    pkjs_dirs = SourceFile.DIR_MAP.get(project.project_type, {}).get('pkjs', [])
    if not pkjs_dirs:
        return

    for pkjs_dir in pkjs_dirs:
        dir_path = os.path.join(base_dir, pkjs_dir)
        if not os.path.isdir(dir_path):
            continue
        for root, dirs, files in os.walk(dir_path):
            for fname in files:
                if not fname.endswith('.js') and not fname.endswith('.json'):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, 'r') as f:
                    content = f.read()

                def _replace(match):
                    key = match.group(1)
                    if key in env_map:
                        return json.dumps(env_map[key])
                    return match.group(0)

                new_content = pattern.sub(_replace, content)
                if new_content != content:
                    with open(fpath, 'w') as f:
                        f.write(new_content)


def assemble_project(project, base_dir, build_result=None):
    """ Copy all files necessary to build a project into a directory. """
    resources = project.resources.all()

    if project.is_standard_project_type:
        # Write out the sources, resources, and wscript and jshint file
        assemble_source_files(project, base_dir)
        if project.project_type != 'rocky':
            assemble_resource_directories(project, base_dir)
            assemble_resources(base_dir, project.resources_path, resources)
        with open(os.path.join(base_dir, 'wscript'), 'w') as wscript:
            wscript.write(generate_wscript_file(project))
        with open(os.path.join(base_dir, 'pebble-jshintrc'), 'w') as jshint:
            jshint.write(generate_jshint_file(project))
    elif project.project_type == 'simplyjs':
        # SimplyJS is a particularly special case
        assemble_simplyjs_sources(project, base_dir, build_result)
    elif project.project_type == 'pebblejs':
        # PebbleJS projects have to import the entire pebblejs library, including its wscript
        assemble_resource_directories(project, base_dir)
        shutil.rmtree(base_dir)
        shutil.copytree(settings.PEBBLEJS_ROOT, base_dir)
        assemble_resources(base_dir, project.resources_path, resources, type_restrictions=('png', 'bitmap'))
        assemble_source_files(project, base_dir)

    # All projects have a manifest
    manifest_filename = manifest_name_for_project(project)
    manifest_dict = generate_manifest_dict(project, resources)

    with open(os.path.join(base_dir, manifest_filename), 'w') as f:
        f.write(json.dumps(manifest_dict))

    # Replace process.env.KEY references in pkjs source files with actual values
    env_vars = project.env_vars.all()
    if env_vars:
        env_map = {ev.key: decrypt_value(ev.encrypted_value) for ev in env_vars}
        _inject_env_vars(base_dir, project, env_map)
