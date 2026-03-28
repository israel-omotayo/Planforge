from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.auth.models import User

from datetime import timedelta

from organizations.models import Membership
from projects.models import Task, ActivityLog


class Command(BaseCommand):
    help = "Send activity digest emails to org members."

    def add_arguments(self, parser):
        parser.add_argument(
            "--frequency",
            choices=["daily", "weekly"],
            default="daily",
            help="Which frequency group to send to (default: daily).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be sent without actually sending.",
        )

    def handle(self, *args, **options):
        frequency = options["frequency"]
        dry_run   = options["dry_run"]

        # How far back to look for activity
        days  = 1 if frequency == "daily" else 7
        since = timezone.now() - timedelta(days=days)
        today = timezone.now().date()
        due_soon = today + timedelta(days=7)

        sent    = 0
        skipped = 0

        memberships = (
            Membership.objects
            .select_related("user", "user__userprofile", "organization")
            .filter(user__is_active=True)
            .exclude(user__email="")
        )

        for membership in memberships:
            user    = membership.user
            org     = membership.organization
            profile = getattr(user, "userprofile", None)

            # Respect opt-out
            user_frequency = getattr(profile, "digest_frequency", "weekly")
            if user_frequency == "never":
                skipped += 1
                continue
            if user_frequency != frequency:
                skipped += 1
                continue

            # Overdue tasks
            overdue_tasks = list(
                Task.objects
                .filter(
                    project__organization=org,
                    assigned_to=user,
                    due_date__lt=today,
                )
                .exclude(status=Task.Status.DONE)
                .select_related("project")
                .order_by("due_date")
            )

            # For daily sends — only continue if there are overdue tasks
            # Daily is urgent-only, not a general summary
            if frequency == "daily" and not overdue_tasks:
                skipped += 1
                continue

            # Due soon
            due_soon_tasks = list(
                Task.objects
                .filter(
                    project__organization=org,
                    assigned_to=user,
                    due_date__gte=today,
                    due_date__lte=due_soon,
                )
                .exclude(status=Task.Status.DONE)
                .select_related("project")
                .order_by("due_date")
            )

            # Recent activity
            activity_since = max(since, membership.joined_at)
            recent_activity = list(
                ActivityLog.objects
                .filter(
                    organization=org,
                    created_at__gte=activity_since,
                )
                .exclude(actor=user)
                .select_related("actor", "project")
                .order_by("-created_at")[:15]
            )

            # Skip if nothing at all to report
            if not overdue_tasks and not due_soon_tasks and not recent_activity:
                skipped += 1
                continue

            subject = self._subject(org.name, overdue_tasks, frequency)
            context = {
                "user":            user,
                "org":             org,
                "overdue_tasks":   overdue_tasks,
                "due_soon_tasks":  due_soon_tasks,
                "recent_activity": recent_activity,
                "frequency":       frequency,
                "today":           today,
            }

            html_body = render_to_string("emails/digest.html", context)
            text_body = render_to_string("emails/digest.txt", context)

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] {user.email} ({frequency}) — "
                    f"{len(overdue_tasks)} overdue, "
                    f"{len(due_soon_tasks)} due soon, "
                    f"{len(recent_activity)} activity items"
                )
                sent += 1
                continue

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=None,
                to=[user.email],
            )
            msg.attach_alternative(html_body, "text/html")
            msg.send(fail_silently=False)

            sent += 1
            self.stdout.write(f"  ✓ {user.email} ({org.name})")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone — {sent} sent, {skipped} skipped."
            )
        )

    def _subject(self, org_name, overdue_tasks, frequency):
        if overdue_tasks:
            count = len(overdue_tasks)
            return f"⚠ {count} overdue task{'s' if count > 1 else ''} — {org_name}"
        return f"{org_name} Weekly Digest"