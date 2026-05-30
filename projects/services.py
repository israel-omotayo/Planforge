import logging
from django.contrib.auth.models import User
from .models import Project, Task
from .schemas import CreateTaskDTO, UpdateTaskDTO, DeleteTaskDTO, UpdateTaskStatusDTO
from organizations.models import Notification
from .models import ActivityLog, ProjectMembership

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Raised when a business rule is violated."""
    pass


class PermissionDenied(Exception):
    """Raised when the acting user lacks permission."""
    pass


class TaskAccess:
    FULL = "full"    # admin/owner — read + write everything
    ASSIGNEE = "assignee"  # assigned member/guest — status + attachments only
    READONLY = "readonly"  # non-assigned member/guest — read only, no writes

def get_task_access(request, task) -> str:
    """
    Returns the access level the current user has on a task.
    Call this at the top of every task write view.
    """
    if request.membership and request.membership.is_admin_or_owner:
        return TaskAccess.FULL
    if task.assigned_to_id == request.user.id:
        return TaskAccess.ASSIGNEE
    return TaskAccess.READONLY

# Internal helpers 

def _get_task(task_uuid: str, project_id: int) -> Task:
    """Fetch a task by UUID, scoped to a specific project."""
    try:
        return Task.objects.get(uuid=task_uuid, project_id=project_id)
    except Task.DoesNotExist:
        raise ServiceError("Task not found.")


# Task CRUD 
def create_task(dto: CreateTaskDTO) -> Task:
    """
    Create a new task inside a project.
    Only Admin/Owner can create tasks.
    """
    due_date = None
    if dto.due_date:
        from datetime import date
        try:
            due_date = date.fromisoformat(dto.due_date)
        except ValueError:
            raise ServiceError("Invalid due date format. Use YYYY-MM-DD.")

    assigned_to = None
    if dto.assigned_to_id:
        try:
            assigned_to = User.objects.get(pk=dto.assigned_to_id)
        except User.DoesNotExist:
            raise ServiceError("Assigned user not found.")

    try:
        created_by = User.objects.get(pk=dto.created_by_id)
    except User.DoesNotExist:
        raise ServiceError("Creator user not found.")

    task = Task.objects.create(
        project_id=dto.project_id,
        created_by=created_by,
        title=dto.title,
        description=dto.description,
        status=dto.status,
        priority=dto.priority,
        due_date=due_date,
        assigned_to=assigned_to,
    )
    logger.info("Task '%s' created in project %s by %s", task.title, dto.project_id, created_by.username)

    # Inbox notification — only if someone is assigned and it's not self-assignment
    if assigned_to and assigned_to.id != dto.created_by_id:
        project = Project.objects.select_related("organization").get(pk=dto.project_id)
        Notification.objects.create(
            recipient=assigned_to,
            type=Notification.Type.TASK_ASSIGNED,
            title=f"You've been assigned a task in {project.name}",
            body=(
                f"{created_by.get_full_name() or created_by.username} assigned you: \"{task.title}\" "
                f"in {project.organization.name} › {project.name}."
                + (f" Due {task.due_date.strftime('%b %-d, %Y')}." if task.due_date else "")
            ),
        )

    return task


def update_task(dto: UpdateTaskDTO) -> Task:
    """
    Update a task's fields.
    Any org member can edit tasks assigned to them.
    """
    task = _get_task(dto.task_uuid, dto.project_id)

    due_date = None
    if dto.due_date:
        from datetime import date
        try:
            due_date = date.fromisoformat(dto.due_date)
        except ValueError:
            raise ServiceError("Invalid due date format. Use YYYY-MM-DD.")

    assigned_to = None
    if dto.assigned_to_id:
        try:
            assigned_to = User.objects.get(pk=dto.assigned_to_id)
        except User.DoesNotExist:
            raise ServiceError("Assigned user not found.")

    old_assigned_id = task.assigned_to_id

    task.title = dto.title
    task.description = dto.description
    task.status = dto.status
    task.priority = dto.priority
    task.due_date = due_date
    task.assigned_to = assigned_to
    task.save()

    logger.info("Task %s updated by user %s", task.uuid, dto.acting_user_id)

    # Notify newly assigned user — skip if same person or self-assignment
    new_assigned_id = assigned_to.id if assigned_to else None
    if (
        assigned_to
        and new_assigned_id != old_assigned_id
        and new_assigned_id != dto.acting_user_id
    ):
        project = Project.objects.select_related("organization").get(pk=dto.project_id)
        try:
            assigner = User.objects.get(pk=dto.acting_user_id)
        except User.DoesNotExist:
            assigner = None
        assigner_name = (assigner.get_full_name() or assigner.username) if assigner else "Someone"
        Notification.objects.create(
            recipient=assigned_to,
            type=Notification.Type.TASK_ASSIGNED,
            title=f"You've been assigned a task in {project.name}",
            body=(
                f"{assigner_name} assigned you: \"{task.title}\" "
                f"in {project.organization.name} › {project.name}."
                + (f" Due {task.due_date.strftime('%b %-d, %Y')}." if task.due_date else "")
            ),
        )

    return task


def delete_task(dto: DeleteTaskDTO) -> None:
    """
    Delete a task. only Admin/Owner can delete tasks.
    """
    task = _get_task(dto.task_uuid, dto.project_id)
    task_title = task.title
    task.delete()
    logger.info("Task '%s' deleted by user %s", task_title, dto.acting_user_id)


def update_task_status(dto: UpdateTaskStatusDTO) -> Task:
    """
    Quick status update — used for the inline checkbox / status toggle.
    """
    task = _get_task(dto.task_uuid, dto.project_id)
    task.status = dto.status
    task.save(update_fields=["status", "updated_at"])
    return task


# Query helpers 

def get_tasks_for_project(
    project_id: int,
    *,
    q: str = "",
    priority: str = "",
    assignee_id: int = None,
    overdue_only: bool = False,
    sort: str = "created_at",
):
    """
    Return tasks for a project with optional filtering and sorting.
    All filtering is done in the DB — nothing loaded into Python unnecessarily.
    """
    from django.utils import timezone

    ALLOWED_SORTS = {"created_at", "-created_at", "due_date", "-priority", "title"}
    if sort not in ALLOWED_SORTS:
        sort = "created_at"

    qs = (
        Task.objects
        .filter(project_id=project_id)
        .select_related("assigned_to", "created_by")
        .prefetch_related("attachments")
    )
    if q:
        qs = qs.filter(title__icontains=q)
    if priority:
        qs = qs.filter(priority=priority)
    if assignee_id:
        qs = qs.filter(assigned_to_id=assignee_id)
    if overdue_only:
        today = timezone.now().date()
        qs = qs.exclude(status=Task.Status.DONE).filter(due_date__lt=today)

    return qs.order_by(sort)


def get_task_stats(project_id: int) -> dict:
    """
    Return task counts and progress for a project's detail page.
    Single DB query using conditional aggregation.
    """
    from django.db.models import Count, Q
    from django.utils import timezone

    today = timezone.now().date()

    stats = Task.objects.filter(project_id=project_id).aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(status=Task.Status.DONE)),
        in_progress=Count("id", filter=Q(status=Task.Status.IN_PROGRESS)),
        todo=Count("id", filter=Q(status=Task.Status.TODO)),
        overdue=Count("id", filter=Q(
            due_date__lt=today,
            status__in=[Task.Status.TODO, Task.Status.IN_PROGRESS],
        )),
    )
    stats["progress"] = round((stats["done"] / stats["total"]) * 100) if stats["total"] else 0
    return stats

def get_dashboard_task_stats(organization_id: int) -> dict:
    """
    Org-wide task stats for the dashboard.
    Single DB query using conditional aggregation.
    """
    from django.db.models import Count, Q
    from django.utils import timezone

    today = timezone.now().date()

    stats = Task.objects.filter(project__organization_id=organization_id).aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(status=Task.Status.DONE)),
        in_progress=Count("id", filter=Q(status=Task.Status.IN_PROGRESS)),
        todo=Count("id", filter=Q(status=Task.Status.TODO)),
        overdue=Count("id", filter=Q(
            due_date__lt=today,
            status__in=[Task.Status.TODO, Task.Status.IN_PROGRESS],
        )),
    )
    stats["progress"] = round((stats["done"] / stats["total"]) * 100) if stats["total"] else 0
    return stats


# Project guest access 

def invite_project_guest(dto) -> tuple:
    """
    Send a guest invite to an email address for a specific project.
    Returns (invite, is_existing_user).
    Raises ServiceError on business rule violations.
    """
    from django.utils import timezone
    from datetime import timedelta
    from django.contrib.auth import get_user_model
    from .models import ProjectMembership, ProjectGuestInvite
    from organizations.models import Membership

    User = get_user_model()

    project = Project.objects.select_related("organization").get(pk=dto.project_id)

    # Don't re-invite someone already a guest on this project
    existing_user = User.objects.filter(email__iexact=dto.email).first()

    if existing_user:
        if ProjectMembership.objects.filter(project=project, user=existing_user).exists():
            raise ServiceError(f"{dto.email} is already a guest on this project.")
        if Membership.objects.filter(organization=project.organization, user=existing_user).exists():
            raise ServiceError(f"{dto.email} is already an org member and has full access.")

    # Check for a live pending invite to the same email
    live_invite = ProjectGuestInvite.objects.filter(
        project=project,
        email__iexact=dto.email,
        status=ProjectGuestInvite.STATUS_PENDING,
        expires_at__gt=timezone.now(),
    ).first()
    if live_invite:
        raise ServiceError(f"A pending invite has already been sent to {dto.email}.")

    try:
        invited_by = User.objects.get(pk=dto.invited_by_id)
    except User.DoesNotExist:
        raise ServiceError("Inviting user not found.")

    invite = ProjectGuestInvite.objects.create(
        project=project,
        invited_by=invited_by,
        email=dto.email,
        invited_user=existing_user,
        expires_at=timezone.now() + timedelta(days=7),
    )
    # Send inbox notification if the invitee already has a Planforge account
    if existing_user:
        from organizations.models import Notification
        Notification.objects.create(
            recipient=existing_user,
            type=Notification.Type.PROJECT_GUEST_INVITE,
            title=f"You've been invited to collaborate on {project.name}",
            body=(
                f"{invited_by.get_full_name() or invited_by.username} invited you to join "
                f"\"{project.name}\" in {project.organization.name} as a guest."
            ),
            project_guest_invite=invite,
        )
    return invite, existing_user is not None


def accept_guest_invite(dto) -> ProjectMembership:
    """
    Called when a user clicks the accept link in their invite email.
    Validates the invite is still valid, creates the ProjectMembership.
    Raises ServiceError on any problem.
    """
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    from .models import ProjectMembership, ProjectGuestInvite

    User = get_user_model()

    try:
        invite = ProjectGuestInvite.objects.select_related("project").get(uuid=dto.invite_uuid)
    except ProjectGuestInvite.DoesNotExist:
        raise ServiceError("Invite not found or already used.")

    if invite.status != ProjectGuestInvite.STATUS_PENDING:
        raise ServiceError("This invite has already been used or has expired.")

    if invite.is_expired:
        invite.status = ProjectGuestInvite.STATUS_EXPIRED
        invite.save(update_fields=["status"])
        raise ServiceError("This invite has expired. Ask the project owner to send a new one.")

    try:
        user = User.objects.get(pk=dto.accepting_user_id)
    except User.DoesNotExist:
        raise ServiceError("User not found.")

    # Ensure the accepting user's email matches the invite
    if user.email.lower() != invite.email.lower():
        raise ServiceError(
            f"This invite was sent to {invite.email}. "
            f"Please sign in with that account to accept it."
        )

    from django.db import transaction
 
    # Atomically create the membership and mark the invite accepted.
    with transaction.atomic():
        membership, created = ProjectMembership.objects.update_or_create(
            project=invite.project,
            user=user,
            defaults={
                "invited_by": invite.invited_by,
                "role": ProjectMembership.Role.GUEST,
                "joined_at": timezone.now(),
            },
        )
 
        invite.status = ProjectGuestInvite.STATUS_ACCEPTED
        invite.save(update_fields=["status"])
 
    return membership


def remove_project_guest(project_id: int, guest_user_id: int, acting_user_id: int) -> None:
    """Remove a guest's project access. Only admins/owners can do this.
    Also unassigns any tasks in this project that were assigned to the guest,
    so their name no longer appears in task content after they leave.
    """
    from .models import ProjectMembership
    try:
        membership = ProjectMembership.objects.get(project_id=project_id, user_id=guest_user_id)
        membership.delete()
    except ProjectMembership.DoesNotExist:
        raise ServiceError("Guest membership not found.")

    # Unassign any tasks in this project that still point to the departing user
    Task.objects.filter(project_id=project_id, assigned_to_id=guest_user_id).update(
        assigned_to=None
    )


def get_analytics_data(organization_id: int) -> dict:
    """
    Compute all data needed for the analytics dashboard in one function.
    Returns plain dicts/lists — no ORM objects — so the view can pass them
    straight to json_script and Chart.js.
    """
    from collections import defaultdict
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Count

    org_tasks = Task.objects.filter(project__organization_id=organization_id)
    open_tasks = org_tasks.exclude(status=Task.Status.DONE)
    org_projects = Project.objects.filter(organization_id=organization_id)

    # 1. Task status donut
    task_status = {
        "todo": org_tasks.filter(status=Task.Status.TODO).count(),
        "in_progress": org_tasks.filter(status=Task.Status.IN_PROGRESS).count(),
        "done": org_tasks.filter(status=Task.Status.DONE).count(),
    }

    # 2. Open-task priority horizontal bar
    task_priority = {
        "high": open_tasks.filter(priority=Task.Priority.HIGH).count(),
        "medium": open_tasks.filter(priority=Task.Priority.MEDIUM).count(),
        "low": open_tasks.filter(priority=Task.Priority.LOW).count(),
    }

    # 3. Project health donut
    project_status = {
        "active": org_projects.filter(status=Project.Status.ACTIVE).count(),
        "on_hold": org_projects.filter(status=Project.Status.ON_HOLD).count(),
        "completed": org_projects.filter(status=Project.Status.COMPLETED).count(),
        "archived": org_projects.filter(status=Project.Status.ARCHIVED).count(),
    }

    # 4. Team workload — open tasks per assignee (top 8)
    workload_qs = (
        open_tasks
        .filter(assigned_to__isnull=False)
        .values(
            "assigned_to__username",
            "assigned_to__first_name",
            "assigned_to__last_name",
        )
        .annotate(task_count=Count("id")) # For each assignee, count how many open tasks they have  
        .order_by("-task_count")[:8]
    )
    workload_labels = [] # Assignee names for the chart labels
    workload_data = [] # Corresponding task counts for the chart data
    for row in workload_qs:
        fn = row["assigned_to__first_name"]
        ln = row["assigned_to__last_name"]
        name = f"{fn} {ln}".strip() or row["assigned_to__username"]
        workload_labels.append(name)
        workload_data.append(row["task_count"])

    # 5. Completion trend — tasks completed per day for the last 30 days
    # Sourced from ActivityLog so we capture the exact completion timestamp.
    cutoff = timezone.now() - timedelta(days=29)
    completion_logs = (
        ActivityLog.objects
        .filter(
            organization_id=organization_id,
            verb=ActivityLog.Verb.TASK_COMPLETED,
            created_at__gte=cutoff,
            is_active=True,
        )
        .values("created_at")
    )

    counts_by_day: dict = defaultdict(int)
    for entry in completion_logs:
        day_key = entry["created_at"].strftime("%Y-%m-%d")
        counts_by_day[day_key] += 1

    today = timezone.now().date()
    trend_labels = [] # Last 30 days for the x-axis labels, oldest to newest
    trend_data = [] # Number of tasks completed on each day for the y-axis data
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        trend_labels.append(day.strftime("%b ") + str(day.day))
        trend_data.append(counts_by_day.get(str(day), 0))

    # Overdue count for the summary bar
    overdue = org_tasks.filter(
        due_date__lt=today,
        status__in=[Task.Status.TODO, Task.Status.IN_PROGRESS],
    ).count()

    return {
        "task_status": task_status,
        "task_priority": task_priority,
        "project_status": project_status,
        "workload_labels": workload_labels,
        "workload_data": workload_data,
        "trend_labels": trend_labels,
        "trend_data": trend_data,
        "total_tasks": sum(task_status.values()),
        "total_projects": sum(project_status.values()),
        "done_tasks": task_status["done"],
        "overdue_tasks": overdue,
        "members_count": 0,  # filled in the view from org
    }
