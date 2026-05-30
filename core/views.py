from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from datetime import timedelta
import logging
from organizations.services import get_active_organization
from projects.models import Project, ActivityLog, Task
from projects.services import get_dashboard_task_stats
from organizations.services import get_user_membership
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods, require_POST
from django.db import connection
from django.core.cache import cache
import hmac
from django.views.decorators.csrf import csrf_exempt
from django.core.management import call_command
import os

logger = logging.getLogger(__name__)


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "home.html")

@require_http_methods(["GET", "POST", "HEAD"])
def health(request):
    """
    Health check endpoint for load balancers and uptime monitors.
    Probes both PostgreSQL and Redis so a broken dependency causes a non-200,
    which tells the load balancer to stop routing traffic here.
    """
    #sets up a dictionary to store the results of the health checks for the database and cache
    checks = {}

    # Probe PostgreSQL
    try:
        # Executes a simple query to check database connectivity
        #connection.cursor() opens a database cursor so Django can run SQL
        with connection.cursor() as cursor:
            #Runs a tiny SQL query.
            cursor.execute("SELECT 1")
        checks["db"] = "ok"
    #If any exception occurs during the database check
    except Exception as e:
        logger.error("Health check: DB probe failed: %s", e)
        checks["db"] = "error"

    # Probe Redis (cache backend)
    try:
        # We set a test key and then read it back to confirm Redis is working.
        cache.set("health_check_ping", "pong", timeout=5)
        result = cache.get("health_check_ping")
        checks["cache"] = "ok" if result == "pong" else "error"
    except Exception as e:
        logger.error("Health check: Cache probe failed: %s", e)
        checks["cache"] = "error"

    # Determine overall status based on individual checks. 
    all_ok = all(v == "ok" for v in checks.values())
    http_status = 200 if all_ok else 503
    status_label = "ok" if all_ok else "degraded"

    return JsonResponse({"status": status_label, "checks": checks}, status=http_status)

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
        .order_by("due_date")[:5]
    )

    if not membership:
        org_activity = ActivityLog.objects.none()
    else:
        org_activity = (
            ActivityLog.objects.filter(
                organization=active_org,
                created_at__gte=membership.joined_at,
                is_active=True,
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

def _verify_cron_secret(request):
    secret = os.environ.get("CRON_SECRET", "")
    token = request.headers.get("X-Cron-Secret", "")
    return hmac.compare_digest(secret, token)

@csrf_exempt
@require_POST
def cron_cleanup_activity(request):
    if not _verify_cron_secret(request):
        return HttpResponseForbidden("Forbidden")
    call_command("cleanup_activity", days=30)
    return HttpResponse("ok")

@csrf_exempt
@require_POST
def cron_cleanup_invites(request):
    if not _verify_cron_secret(request):
        return HttpResponseForbidden("Forbidden")
    call_command("cleanup_invites")
    return HttpResponse("ok")

@csrf_exempt
@require_POST
def cron_daily_digest(request):
    if not _verify_cron_secret(request):
        return HttpResponseForbidden("Forbidden")
    call_command("send_digest", frequency="daily")
    return HttpResponse("ok")

@csrf_exempt
@require_POST
def cron_weekly_digest(request):
    if not _verify_cron_secret(request):
        return HttpResponseForbidden("Forbidden")
    call_command("send_digest", frequency="weekly")
    return HttpResponse("ok")