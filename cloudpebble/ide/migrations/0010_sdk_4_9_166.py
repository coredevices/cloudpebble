from django.db import migrations, models


def migrate_all_projects_to_4_9_166(apps, schema_editor):
    Project = apps.get_model('ide', 'Project')
    Project.objects.exclude(sdk_version='4.9.166').update(sdk_version='4.9.166')


class Migration(migrations.Migration):
    dependencies = [
        ('ide', '0009_alter_project_project_type_alter_publishedmedia_name_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_all_projects_to_4_9_166, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='project',
            name='sdk_version',
            field=models.CharField(
                choices=[('4.9.166', 'SDK 4.9.166')],
                default='4.9.166',
                max_length=32,
            ),
        ),
    ]
