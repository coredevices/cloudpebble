import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ide', '0014_agent'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentCredential',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('anthropic', 'Anthropic'),
                                                       ('openrouter', 'OpenRouter')],
                                              max_length=16)),
                ('secret_kind', models.CharField(choices=[('api_key', 'API key'),
                                                          ('oauth', 'OAuth token')],
                                                 default='api_key', max_length=16)),
                ('encrypted_secret', models.TextField()),
                ('model', models.CharField(blank=True, max_length=128)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='agent_credential',
                                              to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'cloudpebble_agent_credentials', 'abstract': False},
        ),
    ]
