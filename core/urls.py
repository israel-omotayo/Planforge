from django.urls import path
from . import views
from projects.views import org_activity


urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("activity/", org_activity, name="org_activity"),
    path("analytics/", views.analytics, name="analytics"),
    path("foruptimerobot/health/", views.health, name="health"),
    path("offline/", views.offline, name="offline"),
    path("cron/cleanup-activity/", views.cron_cleanup_activity, name= "cron_cleanup_activity"),
    path("cron/cleanup-invites/", views.cron_cleanup_invites, name= "cron_cleanup_invites"),
    path("cron/daily-digest/", views.cron_daily_digest, name= "cron_daily_digest"),
    path("cron/weekly-digest/", views.cron_weekly_digest, name= "cron_weekly_digest"),
]