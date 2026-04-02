# A context processor runs on every request and injects variables
# into every template automatically — no need to pass them manually from each view.

from django.core.cache import cache

from .services import get_active_organization, get_user_organizations
from .models import Notification, Organization


def organization_context(request):
    if not request.user.is_authenticated:
        return {
            "active_org": None,
            "user_orgs": [],
            "unread_notification_count": 0,
        }

    # get_active_organization() caches on request._active_org_cache after first call
    active_org = get_active_organization(request)

    # Last 3 visited orgs for the navbar switcher.
    # set_active_organization() keeps _recent_org_ids up to date in the session.
    recent_ids = request.session.get("_recent_org_ids", [])

    if recent_ids:
        orgs_by_id = {o.id: o for o in Organization.objects.filter(pk__in=recent_ids)}
        # Preserve the visit order (most recent first)
        user_orgs = [orgs_by_id[oid] for oid in recent_ids if oid in orgs_by_id]
    else:
        # No visit history yet — just show the first org they belong to
        user_orgs = list(get_user_organizations(request.user.id)[:3])

    # Unread count for the inbox badge in the navbar
    # Cached per page for 30 seconds - avoids a DB hit on every page load
    # Invalidated whenever a new notification is created (see organizations/services.py)
    cache_key=f"notif_count:{request.user.id}"
    unread_count = cache.get(cache_key)
    if unread_count is None:
        unread_count = Notification.objects.filter(
        recipient=request.user, is_read=False
        ).count()
        cache.set(cache_key, unread_count, 30)
    return {
        "active_org": active_org,
        "user_orgs": user_orgs,
        "unread_notification_count": unread_count,
    }