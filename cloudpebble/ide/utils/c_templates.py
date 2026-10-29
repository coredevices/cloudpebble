import io
import os
import re
import zipfile

from django.conf import settings
from ide.utils.microphone_templates import TEMPLATES, build_microphone_archive


WATCHFACE_TUTORIAL_PREFIX = 'watchface-tutorial'
WATCHFACE_TUTORIAL_ROOT_DEFAULT = '/opt/c-watchface-tutorial'
WATCHFACE_TUTORIAL_PARTS = {
    'part1': 'Your First Watchface',
    'part2': 'Customizing Your Watchface',
    'part3': 'Battery Meter and Bluetooth',
    'part4': 'Adding Weather',
    'part5': 'Timeline Peek',
    'part6': 'Adding a Settings Page',
}


def _watchface_tutorial_root():
    return getattr(settings, 'C_WATCHFACE_TUTORIAL_ROOT', WATCHFACE_TUTORIAL_ROOT_DEFAULT)


def _part_number(slug):
    match = re.match(r'^part(\d+)$', slug or '')
    if not match:
        return None
    return int(match.group(1))


def _is_native_project(project_dir):
    package_json = os.path.join(project_dir, 'package.json')
    main_c = os.path.join(project_dir, 'src', 'c', 'main.c')
    return os.path.isfile(package_json) and os.path.isfile(main_c)


def list_c_templates():
    tutorial_root = _watchface_tutorial_root()
    if not os.path.isdir(tutorial_root):
        return list(TEMPLATES)

    templates = []
    for entry in os.listdir(tutorial_root):
        part_number = _part_number(entry)
        if part_number is None:
            continue
        template_dir = os.path.join(tutorial_root, entry)
        if not os.path.isdir(template_dir):
            continue
        if not _is_native_project(template_dir):
            continue
        template_id = '%s/%s' % (WATCHFACE_TUTORIAL_PREFIX, entry)
        templates.append({
            'id': template_id,
            'path': template_id,
            'label': WATCHFACE_TUTORIAL_PARTS.get(entry, 'Part %d' % part_number),
            'dir': WATCHFACE_TUTORIAL_PREFIX + '/',
            'group': WATCHFACE_TUTORIAL_PREFIX + '/',
            'part_number': part_number,
        })

    templates.sort(key=lambda item: item['part_number'])
    for template in templates:
        template.pop('part_number', None)
    return templates + list(TEMPLATES)


def _resolve_template_directory(template_path):
    if not template_path.startswith(WATCHFACE_TUTORIAL_PREFIX + '/'):
        raise ValueError('Unknown C template path')
    slug = template_path.split('/', 1)[1]
    root = _watchface_tutorial_root()
    return os.path.normpath(os.path.join(root, slug)), os.path.normpath(root)


def build_c_template_archive(template_path):
    if template_path in {item["id"] for item in TEMPLATES}:
        return build_microphone_archive(template_path)
    target_dir, root = _resolve_template_directory(template_path)
    if not target_dir.startswith(root + os.sep):
        raise ValueError('Invalid template path')
    if not os.path.isdir(target_dir):
        raise ValueError('Template path does not exist')
    if not _is_native_project(target_dir):
        raise ValueError('Template is not a valid Pebble C SDK project')

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(target_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '.git']
            for filename in filenames:
                if filename.startswith('.'):
                    continue
                full_path = os.path.join(dirpath, filename)
                arcname = os.path.relpath(full_path, target_dir)
                archive.write(full_path, arcname=arcname)

    return bundle.getvalue()
