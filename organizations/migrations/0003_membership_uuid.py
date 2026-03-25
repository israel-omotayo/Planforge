import uuid
from django.db import migrations, models


def gen_uuid(apps, schema_editor):
    Membership = apps.get_model("organizations", "Membership")
    for m in Membership.objects.all():
        m.uuid = uuid.uuid4()
        m.save(update_fields=["uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0002_membership_invited_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="uuid",
            field=models.UUIDField(null=True),
        ),
        migrations.RunPython(gen_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="membership",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True),
        ),
    ]