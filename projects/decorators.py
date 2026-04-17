# projects/decorators.py
#
# project_access_required — grants access to a project view if the user is
# either a full org member OR a project-level guest.
#
# Usage:
#   @login_required
#   @project_access_required
#   def project_detail(request, project_uuid):
#       ...
#
# Attaches to request:
#   request.project — the Project object
#   request.active_org — the Organization (always set)
#   request.membership — Membership or None (None for guests)
#   request.project_membership — ProjectMembership or None (None for org members)
#   request.is_project_guest — True if access is granted via ProjectMembership only

from functools import wraps
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from .models import Project, ProjectMembership
from organizations.services import get_active_organization, get_user_membership


def project_access_required(view_func):
    """
    Allows access if the user is an org member OR a project guest.
    Must be placed after @login_required.
    The view must accept a `project_uuid` URL kwarg.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        project_uuid = kwargs.get("project_uuid")

        # Fetch the project (404 if it doesn't exist)
        project = get_object_or_404(Project, uuid=project_uuid)

        # Path 1: org member
        active_org = get_active_organization(request)
        membership = None
        if active_org and active_org.id == project.organization_id:
            membership = get_user_membership(request.user.id, active_org.id)

        if membership:
            request.project = project
            request.active_org = project.organization
            request.membership = membership
            request.project_membership = None
            request.is_project_guest = False
            return view_func(request, *args, **kwargs)

        # Path 2: project guest
        try:
            project_membership = ProjectMembership.objects.get(
                project=project,
                user=request.user,
            )
            request.project = project
            request.active_org = project.organization
            request.membership = None
            request.project_membership = project_membership
            request.is_project_guest = True
            return view_func(request, *args, **kwargs)
        
        except ProjectMembership.DoesNotExist:
            pass

        # No access 
        messages.error(request, "You don't have access to this project.")
        return redirect("organizations:list")

    return wrapper


def project_admin_required(view_func):
    """
    Restricts a project view to org admins/owners only.
    Guests are always denied. Must be stacked on top of project_access_required.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if getattr(request, "is_project_guest", False):
            messages.error(request, "Guests cannot perform this action.")
            project = getattr(request, "project", None)
            if project:
                return redirect("projects:detail", project_uuid=project.uuid)
            return redirect("organizations:list")

        membership = getattr(request, "membership", None)
        if not membership or not membership.is_admin_or_owner:
            messages.error(request, "You need admin or owner access for this action.")
            project = getattr(request, "project", None)
            if project:
                return redirect("projects:detail", project_uuid=project.uuid)
            return redirect("organizations:list")

        return view_func(request, *args, **kwargs)

    return wrapper
