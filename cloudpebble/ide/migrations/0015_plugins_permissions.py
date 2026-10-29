from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ide', '0014_buildresult_commit_sha')]
    operations = [
        # Existing projects retain the network/permission behavior they had before SDK 4.43.
        migrations.AddField('project', 'manifest_version', models.PositiveSmallIntegerField(default=1, choices=((1, 'Legacy'), (2, 'Permissions')))),
        migrations.AlterField('project', 'manifest_version', models.PositiveSmallIntegerField(default=2, choices=((1, 'Legacy'), (2, 'Permissions')))),
        migrations.AddField('project', 'uses_permissions', models.JSONField(default=list, blank=True)),
        migrations.AddField('project', 'plugin', models.JSONField(default=dict, blank=True)),
        migrations.AddField('project', 'config_page', models.TextField(default='', blank=True)),
        migrations.AlterField('sourcefile', 'target', models.CharField(max_length=12, default='app', choices=[('app', 'App'), ('pkjs', 'PebbleKit JS'), ('worker', 'Worker'), ('public', 'Public Header File'), ('common', 'Shared JS'), ('embeddedjs', 'Embedded JS'), ('plugin', 'Plugin JavaScript'), ('config', 'Configuration files')])),
        migrations.AlterField('project', 'project_type', models.CharField(max_length=10, default='native', choices=[('native', 'Pebble C SDK'), ('simplyjs', 'Simply.js'), ('pebblejs', 'Pebble.js (beta)'), ('package', 'Pebble Package'), ('rocky', 'Rocky.js'), ('alloy', 'JavaScript SDK (beta)'), ('plugin', 'Phone plugin')])),
    ]
