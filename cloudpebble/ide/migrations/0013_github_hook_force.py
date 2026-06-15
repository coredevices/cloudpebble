from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ide', '0012_env_vars'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='github_hook_force',
            field=models.BooleanField(default=False),
        ),
    ]