#!/usr/bin/env python
import gevent.monkey; gevent.monkey.patch_all(subprocess=True)

import uuid
import tempfile
import os
import os.path
import errno
import gevent
import collections
import traceback
import atexit

import settings
from ycm import YCM
from filesync import FileSync
from projectinfo import ProjectInfo, RESOURCE_HEADER_NAME, MESSAGEKEY_HEADER_NAME
from npm_helpers import try_setup_dependencies, setup_dependencies

mapping = {}

YCMHolder = collections.namedtuple('YCMHolder', ('filesync', 'projectinfo', 'ycms'))
CodeCompletion = collections.namedtuple('CodeCompletion', ('kind', 'insertion_text', 'extra_menu_info', 'detailed_info'))


class YCMProxyException(Exception):
    pass


def spinup(content):
    root_dir = tempfile.mkdtemp()
    platforms = set(content.get('platforms', ['basalt']))
    dependencies = content.get('dependencies', {})
    messagekeys = content.get('messagekeys', [])
    resources = content.get('resources', [])

    print("spinup in %s" % root_dir)
    filesync = FileSync(root_dir)
    # Dump all the files we should need. create_file rejects paths outside root_dir
    # and any user-supplied .ycm_extra_conf.py.
    for path, file_content in content['files'].items():
        filesync.create_file(path, file_content)

    # Just ignore NPM failures on spinup since we don't wait them to kill YCM completely.
    # The user will notice that something is wrong when their includes all show as errors.
    (lib_info, lib_messagekeys, lib_resources), npm_error = try_setup_dependencies(dependencies, root_dir)

    info = ProjectInfo(
        messagekeys=messagekeys,
        resources=resources,
        lib_resources=lib_resources,
        lib_messagekeys=lib_messagekeys
    )
    filesync.create_file(RESOURCE_HEADER_NAME, info.make_resource_ids_header())
    filesync.create_file(MESSAGEKEY_HEADER_NAME, info.make_messagekey_header())

    ycms = YCMHolder(filesync=filesync, projectinfo=info, ycms={})

    print("created files")
    settings_path = os.path.join(root_dir, ".ycm_extra_conf.py")

    conf_file = 'ycm_extra_conf_sdk3.py'
    sdk_path = settings.PEBBLE_SDK3

    with open(settings_path, "w") as f:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ycm_conf', conf_file)) as template:
            f.write(template.read().format(sdk=sdk_path, here=root_dir, stdlib=settings.STDLIB_INCLUDE_PATH))

    try:
        for platform in ('aplite', 'basalt', 'chalk', 'diorite', 'gabbro', 'flint'):
            if platform in platforms:
                ycm = YCM(filesync, platform)
                ycm.wait()
                ycm.apply_settings(settings_path)
                ycms.ycms[platform] = ycm

    except Exception as e:
        print("Failed to spawn ycm with root_dir %s" % root_dir)
        print(traceback.format_exc())
        return dict(success=False, error=str(e))

    # Keep track of it
    this_uuid = str(uuid.uuid4())
    mapping[this_uuid] = ycms
    # print mapping
    print("spinup complete (%s); %s -> %s" % (platforms, this_uuid, root_dir))
    # victory!
    return dict(success=True, uuid=this_uuid, libraries=lib_info, npm_error=npm_error)


def get_completions(ycms, data):
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    completions = collections.OrderedDict()
    completion_start_column = None
    for platform, ycm in sorted(ycms.ycms.items(), reverse=True):
        ycm.parse(data['file'], data['line'], data['ch'])  # TODO: Should we do this here?
        platform_completions = ycm.get_completions(data['file'], data['line'], data['ch'])
        if platform_completions is not None:
            completion_start_column = platform_completions['completion_start_column']
            for completion in platform_completions['completions']:
                if completion['insertion_text'] in completions:
                    continue
                completions[completion['insertion_text']] = completion

    return dict(
        completions=list(completions.values()),
        start_column=completion_start_column,
    )


def get_ycms(process_uuid):
    if process_uuid not in mapping:
        raise YCMProxyException("UUID not found")
    return mapping[process_uuid]


def get_errors(ycms, data):
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    errors = {}
    for platform, ycm in sorted(ycms.ycms.items(), reverse=True):
        result = ycm.parse(data['file'], data['line'], data['ch'])
        if result is None:
            continue
        if 'exception' in result:
            continue
        for error in result:
            error_key = (error['kind'], error['location']['line_num'], error['text'])
            if error_key in errors:
                errors[error_key]['platforms'].append(platform)
            else:
                error['platforms'] = [platform]
                errors[error_key] = error

    return dict(
        errors=list(errors.values())
    )


def go_to(ycms, data):
    if 'patches' in data:
        ycms.filesync.apply_patches(data['patches'])
    for platform, ycm in sorted(ycms.ycms.items(), reverse=True):
        ycm.parse(data['file'], data['line'], data['ch'])
        result = ycm.go_to(data['file'], data['line'], data['ch'])
        if result is not None:
            return dict(location=result)
    return dict(location=None)


def update_dependencies(ycms, data):
    info = ycms.projectinfo
    filesync = ycms.filesync
    lib_info, new_messagekeys, new_resources = setup_dependencies(data['dependencies'], filesync.root_dir)
    info.lib_resources = new_resources
    info.lib_messagekeys = new_messagekeys
    filesync.create_file(RESOURCE_HEADER_NAME, info.make_resource_ids_header())
    filesync.create_file(MESSAGEKEY_HEADER_NAME, info.make_messagekey_header())
    return {'libraries': lib_info}


def update_resources(ycms, data):
    info = ycms.projectinfo
    filesync = ycms.filesync
    info.resources = data['resources']
    filesync.create_file(RESOURCE_HEADER_NAME, info.make_resource_ids_header())


def update_messagekeys(ycms, data):
    info = ycms.projectinfo
    filesync = ycms.filesync
    info.messagekeys = data['messagekeys']
    filesync.create_file(MESSAGEKEY_HEADER_NAME, info.make_messagekey_header())


def create_file(ycms, data):
    ycms.filesync.create_file(data['filename'], data['content'])


def delete_file(ycms, data):
    ycms.filesync.delete_file(data['filename'])


def rename_file(ycms, data):
    ycms.filesync.rename_file(data['filename'], data['new_filename'])


def ping(ycms, data=None):
    for ycm in ycms.ycms.values():
        if not ycm.ping():
            raise YCMProxyException("Failed to ping YCM")


def kill_completer(process_uuid):
    global mapping
    if process_uuid in mapping:
        for platform, ycm in mapping[process_uuid].ycms.items():
            print("killing %s:%s (alive: %s)" % (process_uuid, platform, ycm.alive))
            ycm.close()
        del mapping[process_uuid]
    else:
        print("no uuid %s to kill" % process_uuid)


def kill_completers():
    global mapping

    for ycms in mapping.values():
        for ycm in ycms.ycms.values():
            ycm.close()
    mapping = {}


def monitor_processes():
    global mapping

    def monitor(process_mapping):
        while True:
            print("process sweep running")
            gevent.sleep(20)
            to_kill = set()

            for process_uuid, ycms in process_mapping.items():
                for platform, ycm in ycms.ycms.items():
                    if not ycm.alive:
                        print("killing %s:%s (alive: %s)" % (process_uuid, platform, ycm.alive))
                        ycm.close()
                        to_kill.add(process_uuid)
            for process_uuid in to_kill:
                del process_mapping[process_uuid]
            print("process sweep collected %d instances" % len(to_kill))

    g = gevent.spawn(monitor, mapping)
    atexit.register(lambda: g.kill())
