"""
Lightweight factory helpers for Planforge tests.

No third-party library needed — just plain Django ORM calls.
Import whatever you need in each test module:

    from tests.factories import make_user, make_org, make_project, make_task
"""

from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from organizations.models import Organization, Membership
from projects.models import Project, Task


def make_user(username="alice", password="testpass123", email=None, verified=True):
    """
    Create an active, verified user and their UserProfile.
    The profile is created automatically via the post_save signal.
    """
    email = email or f"{username}@example.com"
    user = User.objects.create_user(
        username=username,
        password=password,
        email=email,
        is_active=True,
    )
    if verified:
        # UserProfile is created by signal; mark email as confirmed by
        # ensuring no pending_email and no code set (the default state).
        profile = user.userprofile
        profile.email_verification_code = None
        profile.pending_email = None
        profile.save(update_fields=["email_verification_code", "pending_email"])
    return user


def make_org(owner, name="Meridian Studio"):
    """Create an Organization and give the owner an OWNER membership."""
    org = Organization.objects.create(name=name, created_by=owner)
    Membership.objects.create(
        user=owner,
        organization=org,
        role=Membership.Role.OWNER,
    )
    return org


def make_membership(user, org, role=Membership.Role.MEMBER):
    """Add an existing user to an org with the given role."""
    return Membership.objects.create(user=user, organization=org, role=role)


def make_project(org, creator, name="Test Project", status=Project.Status.ACTIVE):
    """Create a project inside an org."""
    return Project.objects.create(
        name=name,
        organization=org,
        created_by=creator,
        status=status,
    )


def make_task(project, creator, title="Test Task",
              status=Task.Status.TODO, priority=Task.Priority.MEDIUM,
              assigned_to=None, due_date=None):
    """Create a task inside a project."""
    return Task.objects.create(
        project=project,
        title=title,
        status=status,
        priority=priority,
        created_by=creator,
        assigned_to=assigned_to,
        due_date=due_date,
    )


def make_overdue_task(project, creator, assigned_to=None):
    """Convenience: a task with a due date in the past."""
    return make_task(
        project=project,
        creator=creator,
        title="Overdue Task",
        assigned_to=assigned_to,
        due_date=(timezone.now() - timedelta(days=3)).date(),
    )
