from django.db import migrations


def migrate_projects(apps, schema_editor):
    Project = apps.get_model('ide', 'Project')
    SourceFile = apps.get_model('ide', 'SourceFile')
    alias = schema_editor.connection.alias
    for project in Project.objects.using(alias).filter(manifest_version=1).exclude(project_type='package').iterator():
        permissions = list(project.uses_permissions)
        names = {p if isinstance(p, str) else p.get('name') for p in permissions}
        required = []
        if project.project_type in ('pebblejs', 'simplyjs') or SourceFile.objects.using(alias).filter(project_id=project.pk, target='pkjs').exists():
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
        project.manifest_version = 2
        project.uses_permissions = permissions
        project.save(using=alias, update_fields=['manifest_version', 'uses_permissions'])


class Migration(migrations.Migration):
    dependencies = [('ide', '0015_plugins_permissions')]
    operations = [migrations.RunPython(migrate_projects, migrations.RunPython.noop)]
