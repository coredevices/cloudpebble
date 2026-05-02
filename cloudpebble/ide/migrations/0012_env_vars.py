from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ide', '0011_drop_sdk_version'),
    ]

    operations = [
        migrations.CreateModel(
            name='EnvironmentVariable',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100)),
                ('encrypted_value', models.TextField()),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='env_vars', to='ide.project')),
            ],
            options={
                'db_table': 'cloudpebble_env_vars',
                'unique_together': {('project', 'key')},
            },
        ),
    ]