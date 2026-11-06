from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('ide', '0015_agent_credential')]

    operations = [
        migrations.AddField(
            model_name='agentcredential',
            name='auth_failed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='agentcredential',
            name='auth_error',
            field=models.TextField(blank=True),
        ),
    ]
