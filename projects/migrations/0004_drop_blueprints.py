"""
Drop the orphaned blueprints_blueprint table.

The blueprints app was removed from the codebase but its table remained in the
database, holding a FK back to projects_project. That FK was blocking project
deletion with an IntegrityError.

This migration drops the table with IF EXISTS so it is safe to run even if the
table was already cleaned up manually. It must run before 0004_task.py.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0003_project_uuid"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS blueprints_blueprint CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]