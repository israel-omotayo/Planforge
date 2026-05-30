from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from projects.models import ActivityLog


class Command(BaseCommand):
    help = "Marks ActivityLog entries older than a given number of days as inactive."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30, # can see up to 30 days in the activity log    
            help="Deactivate entries older than this many days (default: 30).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many rows would be marked inactive without changing them.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        qs = ActivityLog.objects.filter(created_at__lt=cutoff, is_active=True)

        if dry_run:
            count = qs.count()
            self.stdout.write(
                f"[DRY RUN] Would mark {count} ActivityLog "
                f"entries older than {days} days."
            )
            return

        updated = qs.update(is_active=False)
        self.stdout.write(
            self.style.SUCCESS(
                f"Marked {updated} ActivityLog entries older than {days} days as inactive."
            )
        )
