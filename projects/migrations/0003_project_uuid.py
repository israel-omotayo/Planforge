import uuid
from django.db import migrations, models


def gen_uuid(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    for project in Project.objects.all():
        project.uuid = uuid.uuid4()
        project.save(update_fields=["uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0002_project_budget_project_currency"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="uuid",
            field=models.UUIDField(null=True),
        ),
        migrations.RunPython(gen_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="project",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True),
        ),
    ]