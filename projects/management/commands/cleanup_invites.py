from django.core.management.base import BaseCommand
from django.utils import timezone
from projects.models import ProjectGuestInvite


class Command(BaseCommand):
    help = "Marks expired pending guest invites as expired."

    def handle(self, *args, **options):
        updated = ProjectGuestInvite.objects.filter(
            status=ProjectGuestInvite.STATUS_PENDING,
            expires_at__lt=timezone.now(),
        ).update(status=ProjectGuestInvite.STATUS_EXPIRED)

        self.stdout.write(self.style.SUCCESS(f"Marked {updated} invite(s) as expired."))
        