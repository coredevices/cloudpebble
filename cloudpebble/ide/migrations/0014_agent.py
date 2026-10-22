from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ide', '0013_github_hook_force'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentSession',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sdk_session_id', models.CharField(blank=True, max_length=64)),
                ('status', models.CharField(choices=[('idle', 'Idle'), ('running', 'Running'), ('error', 'Error'), ('cancelled', 'Cancelled')], default='idle', max_length=16)),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('last_active', models.DateTimeField(auto_now=True)),
                ('turn_count', models.IntegerField(default=0)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agent_sessions', to='ide.project')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agent_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'cloudpebble_agent_sessions',
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='AgentTranscript',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sdk_session_id', models.CharField(db_index=True, max_length=64)),
                ('subpath', models.CharField(blank=True, default='', max_length=128)),
                ('data', models.BinaryField(default=b'')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transcripts', to='ide.agentsession')),
            ],
            options={
                'db_table': 'cloudpebble_agent_transcripts',
                'abstract': False,
                'unique_together': {('sdk_session_id', 'subpath')},
            },
        ),
        migrations.CreateModel(
            name='AgentMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('seq', models.IntegerField()),
                ('role', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant'), ('tool', 'Tool'), ('system', 'System')], max_length=16)),
                ('content', models.JSONField(default=dict)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='ide.agentsession')),
            ],
            options={
                'db_table': 'cloudpebble_agent_messages',
                'ordering': ['seq'],
                'abstract': False,
                'unique_together': {('session', 'seq')},
            },
        ),
    ]
