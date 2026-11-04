from django.db import migrations

# Rows are updated in batches: one query per project took over an hour against
# the production database, longer than the web pod's startup window.
BATCH_SIZE = 500


def migrate_projects(apps, schema_editor):
    Project = apps.get_model('ide', 'Project')
    SourceFile = apps.get_model('ide', 'SourceFile')
    alias = schema_editor.connection.alias
    projects = Project.objects.using(alias).filter(manifest_version=1).exclude(project_type='package')
    pkjs_project_ids = set(SourceFile.objects.using(alias).filter(target='pkjs', project__in=projects)
                           .values_list('project_id', flat=True).distinct())
    batch = []
    for project in projects.only('id', 'project_type', 'uses_permissions', 'app_capabilities',
                                 'app_is_shown_on_communication').iterator(chunk_size=2000):
        permissions = list(project.uses_permissions)
        names = {p if isinstance(p, str) else p.get('name') for p in permissions}
        required = []
        if project.project_type in ('pebblejs', 'simplyjs') or project.pk in pkjs_project_ids:
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
        batch.append(project)
        if len(batch) >= BATCH_SIZE:
            Project.objects.using(alias).bulk_update(batch, ['manifest_version', 'uses_permissions'])
            batch = []
    if batch:
        Project.objects.using(alias).bulk_update(batch, ['manifest_version', 'uses_permissions'])


class Migration(migrations.Migration):
    dependencies = [('ide', '0015_plugins_permissions')]
    operations = [migrations.RunPython(migrate_projects, migrations.RunPython.noop)]
