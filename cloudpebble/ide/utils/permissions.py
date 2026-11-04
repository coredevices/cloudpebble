"""Validation shared by imports and project settings."""
import json
import re
from pathlib import PurePosixPath
from django.core.exceptions import ValidationError


def validate_bundle_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValidationError("Use a relative project file path.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValidationError("File paths must stay inside the project.")
    if path.parts[0] in ('build', 'node_modules', '.git') or value in ('package.json', 'appinfo.json', 'wscript'):
        raise ValidationError("This file path is reserved for the build system.")


def validate_project_manifest(project):
    if not project.name.strip():
        raise ValidationError({'name': 'Enter a project name.'})
    if not isinstance(project.uses_permissions, list):
        raise ValidationError({'uses_permissions': 'Permissions must be a JSON array.'})
    for permission in project.uses_permissions:
        if isinstance(permission, str) and permission.strip():
            continue
        if not isinstance(permission, dict) or not isinstance(permission.get('name'), str) or not permission['name'].strip():
            raise ValidationError({'uses_permissions': 'Each permission needs a name.'})
        if 'parameters' in permission and not isinstance(permission['parameters'], dict):
            raise ValidationError({'uses_permissions': 'Permission parameters must be an object.'})
    if not isinstance(project.plugin, dict):
        raise ValidationError({'plugin': 'Plugin configuration must be a JSON object.'})
    if project.manifest_version == 1 and (project.plugin or project.uses_permissions or project.config_page):
        raise ValidationError('Plugins, permissions and configuration pages require manifest version 2.')
    if project.project_type == 'plugin' and not project.plugin:
        raise ValidationError({'plugin': 'A plugin project needs a plugin script.'})
    if project.plugin:
        validate_bundle_path(project.plugin.get('script'))
    if project.config_page and not project.config_page.startswith(('https://', 'http://')):
        validate_bundle_path(project.config_page)
    try:
        keys = json.loads(project.app_keys)
    except (ValueError, TypeError):
        raise ValidationError({'app_keys': 'Message keys must be valid JSON.'})
    if isinstance(keys, list):
        names = []
        for key in keys:
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\[[1-9][0-9]*\])?', key):
                raise ValidationError({'app_keys': 'Message keys must be C identifiers with optional positive array lengths.'})
            names.append(key.split('[')[0])
        if len(names) != len(set(names)):
            raise ValidationError({'app_keys': 'Message key names must be unique.'})
    elif isinstance(keys, dict):
        if any(type(value) is not int or not 0 <= value <= 0xffffffff for value in keys.values()):
            raise ValidationError({'app_keys': 'Message key IDs must be unsigned 32-bit integers.'})
        if len(set(keys.values())) != len(keys):
            raise ValidationError({'app_keys': 'Message key IDs must be unique.'})
    else:
        raise ValidationError({'app_keys': 'Message keys must be an array or object.'})


def migrate_manifest_v2(project):
    """Declare legacy access before opting an existing app into permissions."""
    if project.manifest_version != 1 or project.project_type == 'package':
        return
    permissions = list(project.uses_permissions)
    names = {p if isinstance(p, str) else p.get('name')
             for p in permissions if isinstance(p, (str, dict))}
    required = []
    if (project.project_type in ('pebblejs', 'simplyjs') or
            project.source_files.filter(target='pkjs').exists()):
        required += ['Internet', 'Location', 'Timeline']
    capabilities = (project.app_capabilities or '').split(',')
    if 'location' in capabilities:
        required.append('Location')
    if 'health' in capabilities:
        required.append('Health')
    if project.app_is_shown_on_communication:
        required.append('LegacyPebbleKit')
    for name in required:
        if name not in names:
            permissions.append(name)
            names.add(name)
    project.uses_permissions = permissions
    project.manifest_version = 2
