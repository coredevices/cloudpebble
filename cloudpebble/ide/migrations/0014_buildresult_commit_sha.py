from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ide", "0013_github_hook_force"),
    ]

    operations = [
        migrations.AddField(
            model_name="buildresult",
            name="commit_sha",
            field=models.CharField(blank=True, max_length=46, null=True),
        ),
    ]
