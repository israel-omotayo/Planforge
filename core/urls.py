from django.urls import path
from . import views
from projects.views import org_activity

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("activity/", org_activity, name="org_activity"),
    path("analytics/", views.analytics, name="analytics"),
    path("health/", views.health, name="health"),
    path("offline/", views.offline, name="offline"),
]