from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from datetime import timedelta
import logging
from organizations.services import get_active_organization
from projects.models import Project, ActivityLog, Task
from projects.services import get_dashboard_task_stats
from organizations.services import get_user_membership

logger = logging.getLogger(__name__)


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "home.html")



def offline(request):
    """Served by the service worker as the offline fallback page."""
    return render(request, "offline.html")

@login_required
def dashboard(request):
    active_org = get_active_organization(request)
    if not active_org:
        return redirect("organizations:create")

    membership = get_user_membership(request.user.id, active_org.id)

    recent_projects = (
        Project.objects
        .filter(organization=active_org)
        .select_related("created_by")
        .order_by("-created_at")[:5]
    )

    all_projects_count = Project.objects.filter(organization=active_org).count()
    members_count = active_org.memberships.count()
    task_stats = get_dashboard_task_stats(active_org.id)

    my_tasks_count = Task.objects.filter(
        assigned_to=request.user,
        project__organization=active_org,
    ).exclude(status="done").count()

    # Upcoming tasks: overdue + due within 7 days, assigned to this user.
    # Ordered so overdue (negative days) surface first, then soonest due date.
    today = timezone.now().date()
    due_soon_cutoff = today + timedelta(days=7)
    upcoming_tasks = (
        Task.objects
        .filter(
            assigned_to=request.user,
            project__organization=active_org,
            due_date__isnull=False,
            due_date__lte=due_soon_cutoff,
        )
        .exclude(status=Task.Status.DONE)
        .select_related("project")
        .order_by("due_date")[:8]
    )

    if not membership:
        org_activity = ActivityLog.objects.none()
    else:
        org_activity = (
            ActivityLog.objects.filter(
                organization=active_org,
                created_at__gte=membership.joined_at,
            )
            .select_related("actor", "project")[:5]
        )

    return render(request, "dashboard.html", {
        "active_org": active_org,
        "membership": membership,
        "recent_projects": recent_projects,
        "all_projects_count": all_projects_count,
        "members_count": members_count,
        "task_stats": task_stats,
        "my_tasks_count": my_tasks_count,
        "upcoming_tasks": upcoming_tasks,
        "today": today,
        "org_activity": org_activity,
        "see_all_activity_url": "/activity/",
    })

@login_required
def analytics(request):
    active_org = get_active_organization(request)
    if not active_org:
        return redirect("organizations:create")

    membership = get_user_membership(request.user.id, active_org.id)

    from projects.services import get_analytics_data
    data = get_analytics_data(active_org.id)
    data["members_count"] = active_org.memberships.count()

    import json
    return render(request, "analytics.html", {
        "active_org": active_org,
        "membership": membership,
        "data": data,
        # Serialised for Chart.js — safe to embed in <script>
        "chart_json": json.dumps({
            "task_status": data["task_status"],
            "task_priority": data["task_priority"],
            "project_status": data["project_status"],
            "workload_labels": data["workload_labels"],
            "workload_data": data["workload_data"],
            "trend_labels": data["trend_labels"],
            "trend_data": data["trend_data"],
        }),
    })