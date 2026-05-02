from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('ide', '0010_sdk_4_9_166'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='project',
            name='sdk_version',
        ),
    ]
