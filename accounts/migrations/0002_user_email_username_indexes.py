"""
Add PostgreSQL functional indexes for case-insensitive email and username lookups.

Without these, every login, registration, invite, and email-change request
does a full-table scan on auth_user using iexact. At 5,000+ users these
become visibly slow.

These indexes let PostgreSQL use an index scan for:
    User.objects.filter(email__iexact=...)
    User.objects.filter(username__iexact=...)
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS idx_auth_user_email_lower
                ON auth_user (LOWER(email));
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_auth_user_email_lower;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS idx_auth_user_username_lower
                ON auth_user (LOWER(username));
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_auth_user_username_lower;",
        ),
    ]
