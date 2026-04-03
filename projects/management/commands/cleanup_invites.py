from django.core.management.base import BaseCommand
from django.utils import timezone
from projects.models import ProjectGuestInvite
from organizations.models import OrganizationInvite


class Command(BaseCommand):
    help = "Marks expired pending guest and org invites as expired."

    def handle(self, *args, **options):
        now = timezone.now()

        guest_updated = ProjectGuestInvite.objects.filter(
            status=ProjectGuestInvite.STATUS_PENDING,
            expires_at__lt=now,
        ).update(status=ProjectGuestInvite.STATUS_EXPIRED)

        org_updated = OrganizationInvite.objects.filter(
            status=OrganizationInvite.STATUS_PENDING,
            expires_at__lt=now,
        ).update(status=OrganizationInvite.STATUS_EXPIRED)

        self.stdout.write(self.style.SUCCESS(
            f"Marked {guest_updated} guest invite(s) and {org_updated} org invite(s) as expired."
        ))