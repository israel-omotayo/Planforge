# Reusable view decorators for organization-level access control.

# Usage example:
#   @login_required
#   @org_member_required
#   def some_view(request, org_slug):
#
# Performance note:
# get_active_organization() caches its result on request._active_org_cache so
# the context processor (which runs later, inside render()) pays zero DB cost.
# Each decorator also caches the membership on request._membership_cache so
# multiple decorators stacked on one view don't re-query.


from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from .services import get_active_organization, get_user_membership, ServiceError


def _resolve_org_and_membership(request):
    """
    Shared helper: fetch active org (from request cache if available),
    then fetch membership (from request cache if available).
    Returns (active_org, membership) — either may be None.
    """
    active_org = get_active_organization(request)  # already cached on request after first call
    if not active_org:
        return None, None

    # Cache membership on request so stacked decorators and the same
    # decorator on different views in the same request don't re-query.
    cached_membership = getattr(request, "_membership_cache", None)
    if cached_membership is not None and cached_membership.organization_id == active_org.id:
        return active_org, cached_membership

    # fetch membership if not cached, and cache it on the request object for future use during the same request lifecycle
    membership = get_user_membership(request.user.id, active_org.id)
    request._membership_cache = membership
    return active_org, membership


def org_member_required(view_func):
    """
    Ensures the user is a member of the active organization.
    If not, redirects to the organization list.
    """
    # wraps(view_func) is a decorator that preserves the original view function's metadata (like its name and docstring) when we wrap it with our custom logic
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        active_org, membership = _resolve_org_and_membership(request)

        if not active_org:
            messages.warning(request, "Please select or create an organization first.")
            return redirect("organizations:list")

        if not membership:
            messages.error(request, "You are not a member of this organization.")
            return redirect("organizations:list")

        # Attach to request so views can access them without another DB query
        request.active_org = active_org
        request.membership = membership
        # If we got this far, the user is a member and we can proceed to the view
        return view_func(request, *args, **kwargs)

    return wrapper


def org_admin_required(view_func):
    """
    Ensures the user is an admin or owner of the active organization.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        active_org, membership = _resolve_org_and_membership(request)

        if not active_org:
            messages.warning(request, "Please select or create an organization first.")
            return redirect("organizations:list")

        if not membership or not membership.is_admin_or_owner:
            messages.error(request, "You need admin or owner access for this action.")
            return redirect("organizations:list")

        request.active_org = active_org
        request.membership = membership
        # If we got this far, the user is an admin or owner and we can proceed to the view
        return view_func(request, *args, **kwargs)

    return wrapper


def org_owner_required(view_func):
    """
    Ensures the user is the owner of the active organization.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        active_org, membership = _resolve_org_and_membership(request)

        if not active_org:
            messages.warning(request, "Please select or create an organization first.")
            return redirect("organizations:list")

        if not membership or not membership.is_owner:
            messages.error(request, "Only the organization owner can do this.")
            return redirect("organizations:list")

        request.active_org = active_org
        request.membership = membership
        # If we got this far, the user is the owner and we can proceed to the view
        return view_func(request, *args, **kwargs)

    return wrapper