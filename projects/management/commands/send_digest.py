from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from datetime import timedelta
from django.conf import settings
from organizations.models import Membership
from projects.models import Task, ActivityLog
from core.utils import send_email, build_planforge_email



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
        dry_run = options["dry_run"]

        days = 1 if frequency == "daily" else 7
        since = timezone.now() - timedelta(days=days)
        today = timezone.now().date()
        due_soon = today + timedelta(days=7)

        sent = 0
        skipped = 0

        memberships = (
            Membership.objects
            .select_related("user", "user__userprofile", "organization")
            .filter(user__is_active=True)
            .exclude(user__email="")
        )

        for membership in memberships:
            user = membership.user
            org = membership.organization
            profile = getattr(user, "userprofile", None)

            # Respect opt-out and frequency preference
            user_frequency = getattr(profile, "digest_frequency", "weekly")
            if user_frequency == "never" or user_frequency != frequency:
                skipped += 1
                continue

            # Overdue tasks assigned to this user in this org
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

            # Daily is urgent-only — skip if nothing overdue
            if frequency == "daily" and not overdue_tasks:
                skipped += 1
                continue

            # Tasks due in the next 7 days
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

            # Recent activity — respects joined_at, excludes own actions
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

            # Nothing to report — skip
            if not overdue_tasks and not due_soon_tasks and not recent_activity:
                skipped += 1
                continue

            subject = self._subject(org.name, overdue_tasks, frequency)
            context = {
                "user": user,
                "org": org,
                "overdue_tasks": overdue_tasks,
                "due_soon_tasks":  due_soon_tasks,
                "recent_activity": recent_activity,
                "frequency": frequency,
                "today": today,
            }

            # 1. Use your BASE_FRONTEND_URL
            base_url = getattr(settings, 'BASE_FRONTEND_URL', 'http://localhost:8000').rstrip('/')

            # 2. Render the "Inner Content" (the lists of tasks/activity)
            # We move the greeting and CTA out of the template and into the wrapper
            inner_html = render_to_string("emails/digest.html", context)

            # 3. Choose the wrapper configuration
            is_urgent = frequency == "daily" and overdue_tasks
            heading = f"{org.name} Update" if not is_urgent else "Action Required: Overdue Tasks"

            # 4. Wrap everything in the Planforge Layout
            full_html_body = build_planforge_email(
                heading=heading,
                message=inner_html, # This is your task/activity list
                action_content=f'<a href="{base_url}/dashboard/" class="btn">Open Dashboard</a>',
                notice=f"Frequency: {frequency.capitalize()}. Change settings at {base_url}/accounts/profile/"
            )

            subject = self._subject(org.name, overdue_tasks, frequency)

            if dry_run:
                self.stdout.write(f"[DRY RUN] Would send to {user.email}")
                continue

            try:
                # Uses Resend in production, console backend in dev
                send_email(user.email, subject, full_html_body)
                sent += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f" ✗ {user.email} — {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone — {sent} sent, {skipped} skipped."
            )
        )

    def _subject(self, org_name, overdue_tasks, frequency):
        if overdue_tasks:
            count = len(overdue_tasks)
            return (
                f"⚠ {count} overdue task{'s' if count > 1 else ''} "
                f"— {org_name}"
            )
        return f"{org_name} Weekly Digest"