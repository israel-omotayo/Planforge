import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from .decorators import org_admin_required, org_member_required, org_owner_required
from .forms import ChangeMemberRoleForm, CreateOrganizationForm, InviteMemberForm, UpdateOrganizationForm
from .models import Membership, Organization, InviteLink, LinkJoinRequest, OrganizationInvite
from .schemas import (
    ChangeMemberRoleDTO,
    CreateOrganizationDTO,
    DeleteOrganizationDTO,
    InviteMemberDTO,
    RemoveMemberDTO,
    UpdateOrganizationDTO,
    RespondToInviteDTO,
    GenerateInviteLinkDTO,
    ProcessLinkJoinDTO,
    RespondToJoinRequestDTO,
    TransferOwnershipDTO,
    DisableInviteLinkDTO,
)
from . import services

#create a logger for this file
logger = logging.getLogger(__name__)


# Organization list
@login_required
def org_list(request):
    """
    Show all organizations the user belongs to.
    This is also the page they land on if they have no active org.
    """
    orgs = services.get_user_organizations(request.user.id)
    return render(request, "organizations/list.html", {"orgs": orgs})


# Create organization
@login_required
@require_http_methods(["GET", "POST"])
def org_create(request):
    form = CreateOrganizationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            dto = CreateOrganizationDTO(
                name=form.cleaned_data["name"],
                created_by_id=request.user.id,
            )
            org = services.create_organization(dto)

            # Set the new org as active immediately
            services.set_active_organization(request, org.id)

            messages.success(request, f"'{org.name}' created successfully.")
            return redirect("organizations:settings", org_slug=org.slug)

        # handles any exceptions that might be raised during the organization creation process
        except (services.ServiceError, ValueError) as e:
            messages.error(request, str(e))

    # If GET or form is invalid, show the form (with errors if POST)
    return render(request, "organizations/create.html", {"form": form})


# Switch active organization
@login_required
@require_POST
def org_switch(request, org_slug):
    """
    Switch the user's active organization.
    POST only — switching org changes session state, should not be a GET.
    """
    # gets the organization object based on the provided slug
    org = get_object_or_404(Organization, slug=org_slug)

    try:
        # verifies membership and stores the active organization in the session
        services.set_active_organization(request, org.id)
        messages.success(request, f"Switched to '{org.name}'.")

    except services.PermissionDenied as e:
        messages.error(request, str(e))

    # Go back to wherever they were, fall back to dashboard
    next_url = request.POST.get("next", "")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("dashboard")


# Organization settings
@login_required
@org_member_required
@require_http_methods(["GET", "POST"])
def org_settings(request, org_slug):
    """
    Organization settings page.
    Shows org info, member list, and actions depending on user's role.
    """
    org = get_object_or_404(Organization, slug=org_slug)

    # gets all org members and a pre-filled update form with current org name
    membership = services.get_user_membership(request.user.id, org.id)
    if not membership:
        messages.error(request, "You are not a member of this organization.")
        return redirect("organizations:list")  

    services.set_active_organization(request, org.id)
    request.active_org = org
    request.membership = membership

    members = services.get_organization_members(org.id)
    
    form = UpdateOrganizationForm(initial={"name": org.name})  

    pending_invites = []
    pending_join_requests = []
    active_invite_link = None

    if membership.is_admin_or_owner:
        pending_invites = services.get_pending_invites_sent(org.id)
        pending_join_requests = services.get_pending_join_requests(org.id)
        active_invite_link = services.get_active_invite_link(org.id)

    return render(request, "organizations/settings.html", {
        "org": org,
        "membership": membership,
        "members": members,
        "form": form,
        "pending_invites": pending_invites,
        "pending_join_requests": pending_join_requests,
        "active_invite_link": active_invite_link,
    })


# Update organization name
@login_required
@org_admin_required
@require_POST
def org_update(request, org_slug):
    form = UpdateOrganizationForm(request.POST)

    if form.is_valid():
        try:
            dto = UpdateOrganizationDTO(
                organization_id=request.active_org.id,
                acting_user_id=request.user.id,
                name=form.cleaned_data["name"],
            )
            org = services.update_organization(dto)
            messages.success(request, "Organization name updated.")
            return redirect("organizations:settings", org_slug=org.slug)

        except (services.ServiceError, services.PermissionDenied, ValueError) as e:
            messages.error(request, str(e))

    else:
        messages.error(request, "Please correct the errors below.")

    return redirect("organizations:settings", org_slug=org_slug)


# Invite member
@login_required
@org_admin_required
@require_POST
def org_invite_member(request, org_slug):
    form = InviteMemberForm(request.POST)
    if form.is_valid():
        try:
            dto = InviteMemberDTO(
                organization_id=request.active_org.id,
                acting_user_id=request.user.id,
                target_username=form.cleaned_data["username"],
                role=form.cleaned_data["role"],
            )
            invite = services.send_org_invite(dto)
            messages.success(
                request,
                f"Invite sent to {invite.invited_user.username}. "
                "They'll see it in their inbox and can accept or decline."
            )
        except (services.ServiceError, services.PermissionDenied, ValueError) as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Please correct the errors below.")

    return redirect("organizations:settings", org_slug=org_slug)


# Remove member
@login_required
@org_admin_required
@require_POST
def org_remove_member(request, org_slug, membership_uuid):
    # org_admin_required attaches request.active_org — no manual lookup needed
    org = request.active_org

    try:
        dto = RemoveMemberDTO(
            organization_id=org.id,
            acting_user_id=request.user.id,
            target_membership_uuid=membership_uuid,
        )
        removed_user_id = services.remove_member(dto)

        if removed_user_id == request.user.id:
            request.session.pop("active_org_id", None)
            messages.success(request, f"You have left '{org.name}'.")
            return redirect("organizations:list")

        messages.success(request, "Member removed.")

    except (services.ServiceError, services.PermissionDenied) as e:
        messages.error(request, str(e))

    return redirect("organizations:settings", org_slug=org_slug)

# Leave organization
@login_required
@org_member_required
@require_POST
def org_leave(request, org_slug):
    """
    A non-owner member leaves the org themselves.
    Owners cannot leave — they must transfer ownership or delete the org.
    """
    org = request.active_org
    membership = request.membership

    if membership.is_owner:
        messages.error(
            request,
            "Owners cannot leave. Delete the organization or transfer ownership first."
        )
        return redirect("organizations:settings", org_slug=org_slug)

    try:
        dto = RemoveMemberDTO(
            organization_id=org.id,
            acting_user_id=request.user.id,
            target_membership_uuid=str(membership.uuid),
        )
        from projects.activity import member_left
        member_left(request.user, org)
        services.remove_member(dto)
        request.session.pop("active_org_id", None)
        messages.success(request, f"You have left '{org.name}'.")

    except (services.ServiceError, services.PermissionDenied) as e:
        messages.error(request, str(e))
        return redirect("organizations:settings", org_slug=org_slug)

    return redirect("organizations:list")

# Change member role 
@login_required
@org_owner_required
@require_POST
def org_change_member_role(request, org_slug, membership_uuid):
    form = ChangeMemberRoleForm(request.POST)

    if form.is_valid():
        try:
            dto = ChangeMemberRoleDTO(
                organization_id=request.active_org.id,
                acting_user_id=request.user.id,
                target_membership_uuid=membership_uuid,
                new_role=form.cleaned_data["role"],
            )
            services.change_member_role(dto)
            messages.success(request, "Role updated.")

        except (services.ServiceError, services.PermissionDenied, ValueError) as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Invalid role.")

    return redirect("organizations:settings", org_slug=org_slug)

# Delete organization
@login_required
@org_owner_required
@require_POST
def org_delete(request, org_slug):
    try:
        dto = DeleteOrganizationDTO(
            organization_id=request.active_org.id,
            acting_user_id=request.user.id,
        )
        org_name = request.active_org.name
        services.delete_organization(dto)

        # Clear org from session since it no longer exists
        request.session.pop("active_org_id", None)
        messages.success(request, f"'{org_name}' has been permanently deleted.")

    except (services.ServiceError, services.PermissionDenied) as e:
        messages.error(request, str(e))
        return redirect("organizations:settings", org_slug=org_slug)

    return redirect("organizations:list")

# Inbox
@login_required
def inbox(request):
    notifications = services.get_user_notifications(request.user.id)
    # Mark all as read when they open the inbox
    services.mark_all_notifications_read(request.user.id)
    return render(request, "organizations/inbox.html", {"notifications": notifications})


# Accept / reject a direct invite
@login_required
@require_POST
def accept_invite(request, invite_uuid):
    try:
        dto = RespondToInviteDTO(
            acting_user_id=request.user.id,
            invite_uuid=str(invite_uuid),
            accept=True,
        )
        success, msg = services.respond_to_invite(dto)
        if success:
            messages.success(request, msg)
            invite = OrganizationInvite.objects.get(uuid=invite_uuid)
            services.set_active_organization(request, invite.organization_id)
        else:
            messages.info(request, msg)
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("organizations:inbox")


@login_required
@require_POST
def reject_invite(request, invite_uuid):
    try:
        dto = RespondToInviteDTO(
            acting_user_id=request.user.id,
            invite_uuid=str(invite_uuid),
            accept=False,
        )
        _, msg = services.respond_to_invite(dto)
        messages.info(request, msg)
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("organizations:inbox")


# Generate invite link 
@login_required
@org_admin_required
@require_POST
def generate_invite_link_view(request, org_slug):
    try:
        dto = GenerateInviteLinkDTO(
            acting_user_id=request.user.id,
            organization_id=request.active_org.id,
        )
        services.generate_invite_link(dto)
        messages.success(
            request,
            "Invite link generated. It's active for 48 hours and up to 10 uses. "
            "Anyone who uses it must be approved by you first."
        )
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("organizations:settings", org_slug=org_slug)


# Join via link (landing page)
@login_required
@require_http_methods(["GET", "POST"])
def join_via_link(request, token):
    try:
        link = InviteLink.objects.select_related("organization").get(uuid=token)
    except InviteLink.DoesNotExist:
        messages.error(request, "This invite link is invalid.")
        return redirect("organizations:list")

    if not link.is_valid:
        messages.error(request, "This invite link has expired or is no longer active.")
        return redirect("organizations:list")

    already_member = Membership.objects.filter(
        user=request.user, organization=link.organization
    ).exists()

    already_requested = LinkJoinRequest.objects.filter(
        invite_link=link, user=request.user, status=LinkJoinRequest.STATUS_PENDING
    ).exists()

    if request.method == "POST":
        try:
            dto = ProcessLinkJoinDTO(token=str(token), user_id=request.user.id)
            services.process_link_join(dto)
            messages.success(
                request,
                f"Your request to join {link.organization.name} has been sent. "
                "You'll get a notification once an admin approves it."
            )
        except services.ServiceError as e:
            messages.error(request, str(e))
        return redirect("organizations:list")

    return render(request, "organizations/invite_join.html", {
        "link": link,
        "already_member": already_member,
        "already_requested": already_requested,
    })


# Approve / reject a join request 

@login_required
@org_admin_required
@require_POST
def approve_join_request(request, org_slug, join_request_uuid):
    try:
        dto = RespondToJoinRequestDTO(
            acting_user_id=request.user.id,
            join_request_uuid=str(join_request_uuid),
            approve=True,
        )
        _, msg = services.respond_to_join_request(dto)
        messages.success(request, msg)
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("organizations:settings", org_slug=org_slug)


@login_required
@org_admin_required
@require_POST
def reject_join_request(request, org_slug, join_request_uuid):
    try:
        dto = RespondToJoinRequestDTO(
            acting_user_id=request.user.id,
            join_request_uuid=str(join_request_uuid),
            approve=False,
        )
        _, msg = services.respond_to_join_request(dto)
        messages.info(request, msg)
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("organizations:settings", org_slug=org_slug)


# Transfer ownership 

@login_required
@org_owner_required
@require_POST
def transfer_ownership_view(request, org_slug):
    target_uuid = request.POST.get("target_membership_uuid", "").strip()
    if not target_uuid:
        messages.error(request, "Please select a member to transfer ownership to.")
        return redirect("organizations:settings", org_slug=org_slug)

    try:
        dto = TransferOwnershipDTO(
            acting_user_id=request.user.id,
            organization_id=request.active_org.id,
            target_membership_uuid=target_uuid,
        )
        services.transfer_ownership(dto)
        messages.success(request, "Ownership transferred. You are now an admin.")
    except (services.ServiceError, services.PermissionDenied) as e:
        messages.error(request, str(e))

    return redirect("organizations:settings", org_slug=org_slug)


# Disable invite link

@login_required
@org_admin_required
@require_POST
def disable_invite_link_view(request, org_slug):
    try:
        dto = DisableInviteLinkDTO(
            acting_user_id=request.user.id,
            organization_id=request.active_org.id,
        )
        services.disable_invite_link(dto)
        messages.success(request, "Invite link disabled. No new join requests can be submitted.")
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("organizations:settings", org_slug=org_slug)
