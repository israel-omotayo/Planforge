from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
import logging
from organizations.services import get_active_organization
from projects.models import Project, ActivityLog
from projects.services import get_dashboard_task_stats
from organizations.services import get_user_membership

logger = logging.getLogger(__name__)


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "home.html")


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
    joined_at = membership.joined_at if membership else None
    activity_qs = ActivityLog.objects.filter(organization=active_org)
    if joined_at:
        activity_qs = activity_qs.filter(created_at__gte=joined_at)
    org_activity = activity_qs.select_related("actor", "project")[:5]

    return render(request, "dashboard.html", {
        "active_org": active_org,
        "membership": membership,
        "recent_projects": recent_projects,
        "all_projects_count": all_projects_count,
        "members_count": members_count,
        "task_stats": task_stats,
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