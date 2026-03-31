# All business logic for organizations and memberships.

# Rules:
# - Every function takes a DTO or simple primitives, never a request object
# - Role checks happen here, not in views
# - Multi-step DB operations use transaction.atomic()
# - Raise ServiceError on failure — never return None silently

import logging
from projects import activity as act
from django.contrib.auth import get_user_model
from django.db import transaction
from .models import Organization, Membership, OrganizationInvite, InviteLink, LinkJoinRequest, Notification
from django.utils import timezone
from datetime import timedelta
from django.db import IntegrityError
from .schemas import (
    RespondToInviteDTO,
    GenerateInviteLinkDTO,
    ProcessLinkJoinDTO,
    RespondToJoinRequestDTO,
    TransferOwnershipDTO,
    DisableInviteLinkDTO,
)

#creates a logger for this file
logger = logging.getLogger(__name__)

#gets current user model
User = get_user_model()

# Exceptions
class ServiceError(Exception):
    """Business logic failure — safe to show message to the user."""
    pass


class PermissionDenied(ServiceError):
    """The acting user does not have permission for this action."""
    pass


# Internal helpers
def _get_membership(user_id: int, organization_id: int) -> Membership:
    """
    Fetch a membership or raise ServiceError.
    Used internally to avoid repeating the same try/except everywhere.
    """
    try:
        return Membership.objects.get(
            user_id=user_id,
            organization_id=organization_id
        )
    except Membership.DoesNotExist:
        raise ServiceError("You are not a member of this organization.")


def _require_admin_or_owner(user_id: int, organization_id: int) -> Membership:
    """
    Fetch membership and confirm the user is admin or owner.
    Raises PermissionDenied if they're not.
    Returns the membership if they are.
    """
    membership = _get_membership(user_id, organization_id)
    if not membership.is_admin_or_owner:
        raise PermissionDenied("You do not have permission to perform this action.")
    return membership


def _require_owner(user_id: int, organization_id: int) -> Membership:
    """
    Fetch membership and confirm the user is the owner.
    Raises PermissionDenied if they're not.
    """
    membership = _get_membership(user_id, organization_id)
    if not membership.is_owner:
        raise PermissionDenied("Only the organization owner can perform this action.")
    return membership


# Organization CRUD 
def create_organization(dto):
    """
    Create a new organization and automatically make the creator the owner.

    Both the organization and the owner membership are created together
    in one transaction — if either fails, neither is saved.
    """
    with transaction.atomic():
        try:
            creator = User.objects.get(pk=dto.created_by_id)
        except User.DoesNotExist:
            raise ServiceError("User not found.")

        org = Organization.objects.create(
            name=dto.name,
            created_by=creator
        )

        # Automatically give the creator owner-level membership
        Membership.objects.create(
            user=creator,
            organization=org,
            role=Membership.Role.OWNER,
            invited_by=None
        )   

        # Log the creation event with organization name and creator username
        logger.info("Organization '%s' created by user %s", org.name, creator.username)
        return org



def update_organization(dto):
    """
    Update organization name. Only owners and admins can do this.
    """
    _require_admin_or_owner(dto.acting_user_id, dto.organization_id)

    try:
        org = Organization.objects.get(pk=dto.organization_id)
    except Organization.DoesNotExist:
        raise ServiceError("Organization not found.")

    org.name = dto.name
    # Slug is intentionally NOT regenerated — it was set once at creation.
    # Changing the slug would break all existing bookmarks and shared links.
    org.save()

    return org


def delete_organization(dto):
    """
    Permanently delete an organization. Only the owner can do this.
    Deleting an org cascades to all its memberships and projects.
    """
    _require_owner(dto.acting_user_id, dto.organization_id)

    try:
        org = Organization.objects.get(pk=dto.organization_id)
    except Organization.DoesNotExist:
        raise ServiceError("Organization not found.")

    org_name = org.name
    org.delete()
    # Log the deletion event with organization name and acting user ID
    logger.info("Organization '%s' deleted by user %s", org_name, dto.acting_user_id)
    return True


# Membership queries 
def get_user_organizations(user_id: int):
    """
    Return all organizations the user is a member of.
    Ordered by org name.
    """
    return Organization.objects.filter(
        memberships__user_id=user_id
    ).order_by("name")


def get_user_membership(user_id: int, organization_id: int):
    """
    Return the user's membership in a specific org, or None.
    Use this when you need the role — e.g. to decide what UI to show.
    select_related('organization') means accessing membership.organization
    never fires an extra query.
    """
    try:
        return Membership.objects.select_related("organization").get(
            user_id=user_id,
            organization_id=organization_id
        )
    except Membership.DoesNotExist:
        return None


def get_organization_members(organization_id: int):
    """
    Return all memberships for an organization, with user data pre-fetched.
    select_related('user') avoids N+1 queries when rendering a member list.
    """
    return (
        Membership.objects
        .filter(organization_id=organization_id)
        .select_related("user")
        .order_by("joined_at")
    )


# Member management
def invite_member(dto):
    try:
        target_user = User.objects.get(username__iexact=dto.target_username, is_active=True)
    except User.DoesNotExist:
        raise ServiceError(f"No active user found with username '{dto.target_username}'.")

    if Membership.objects.filter(
        user=target_user,
        organization_id=dto.organization_id
    ).exists():
        raise ServiceError(f"{target_user.username} is already a member of this organization.")

    try:
        acting_user = User.objects.get(pk=dto.acting_user_id)
    except User.DoesNotExist:
        acting_user = None

    try:
        membership = Membership.objects.create(
            user=target_user,
            organization_id=dto.organization_id,
            role=dto.role,
            invited_by=acting_user # record who sent the invite
        )
    except Exception as e:
        # unique_together (user, organization) protects against concurrent duplicate invites.
        # Without this, two simultaneous requests would both pass the .exists() check above
        # and then one would raise an unhandled IntegrityError (500). Catch it cleanly.
        
        if isinstance(e, IntegrityError):
            raise ServiceError(f"{target_user.username} is already a member of this organization.")
        raise

    # Log the addition event with organization ID, target username and role, and acting user ID
    logger.info(
        "User %s added to org %s as %s by user %s",
        target_user.username, dto.organization_id, dto.role, dto.acting_user_id
    )
    try:
        org = Organization.objects.get(pk=dto.organization_id)
        act.member_invited(acting_user, org, target_user.username)
    except Exception:
        pass
    return membership

def remove_member(dto):
    """
    Remove a member from an organization by their membership UUID.
    Also unassigns any tasks across all org projects that were assigned
    to the departing member, so their name no longer appears in task content.
    """
    acting_membership = _get_membership(dto.acting_user_id, dto.organization_id)

    try:
        target_membership = Membership.objects.get(
            uuid=dto.target_membership_uuid,
            organization_id=dto.organization_id,
        )
    except Membership.DoesNotExist:
        raise ServiceError("That membership does not exist.")

    # Owners cannot be removed
    if target_membership.is_owner:
        raise PermissionDenied("The organization owner cannot be removed.")
    
    is_self = target_membership.user_id == dto.acting_user_id
    if target_membership.is_admin and not acting_membership.is_owner and not is_self:
        raise PermissionDenied("Only the owner can remove an admin.")

    if not is_self and not acting_membership.is_admin_or_owner:
        raise PermissionDenied("You don't have permission to remove this member.")

    try:
        org = Organization.objects.get(pk=dto.organization_id)
        acting = User.objects.get(pk=dto.acting_user_id)
        # Skip the removed log when someone leaves themselves —
        # org_leave already writes a member_left entry before calling this.
        if not is_self:
            act.member_removed(acting, org, target_membership.user.username)
    except Exception:
        pass
    target_membership.delete()

    # Unassign tasks across all org projects so the departed user's name
    # no longer appears in task content after they leave.
    from projects.models import Task
    Task.objects.filter(
        project__organization_id=dto.organization_id,
        assigned_to_id=target_membership.user_id,
    ).update(assigned_to=None)

    return target_membership.user_id   # return so view can detect self-removal


def change_member_role(dto):
    """
    Change a member's role within an organization.
    Only the owner can do this.
    """
    _require_owner(dto.acting_user_id, dto.organization_id)

    try:
        target_membership = Membership.objects.get(
            uuid=dto.target_membership_uuid,
            organization_id=dto.organization_id,
        )
    except Membership.DoesNotExist:
        raise ServiceError("That membership does not exist.")

    if target_membership.user_id == dto.acting_user_id:
        raise PermissionDenied("You cannot change your own role.")

    if target_membership.is_owner:
        raise PermissionDenied("The owner's role cannot be changed.")

    target_membership.role = dto.new_role
    target_membership.save()
    try:
        org = Organization.objects.get(pk=dto.organization_id)
        acting = User.objects.get(pk=dto.acting_user_id)
        act.role_changed(acting, org, target_membership.user.username, dto.new_role)
    except Exception:
        pass
    return target_membership


# Organization switching 
# The "active organization" is stored in the session.
# This is what allows a user to switch between orgs without losing context.

def set_active_organization(request, organization_id: int):
    """
    Set the active organization in the session.
    Also tracks the last 3 visited org IDs so the navbar switcher
    shows recently visited orgs instead of all of them.
    """
    membership = get_user_membership(request.user.id, organization_id)
    if not membership:
        raise PermissionDenied("You are not a member of that organization.")

    request.session["active_org_id"] = organization_id

    # Track last 3 visited orgs (most recent first, no duplicates)
    recent = request.session.get("_recent_org_ids", [])
    if organization_id in recent:
        recent.remove(organization_id)
    recent.insert(0, organization_id)
    request.session["_recent_org_ids"] = recent[:3]

    return membership.organization


def get_active_organization(request):
    """
    Return the currently active Organization for this session, or None.
    Called by the context processor AND the org decorators on every protected
    request. We cache the result on the request object so the second caller
    (whichever arrives first is the decorator; the context processor runs later
    during template rendering) pays zero DB cost.
    """
    if not request.user.is_authenticated:
        return None

    # Request-level cache
    # The sentinel distinguishes "not yet resolved" from "resolved to None".
    _UNSET = object.__new__(object)  # unique object; always falsy comparison fails
    cached = getattr(request, "_active_org_cache", _UNSET)
    if cached is not _UNSET:
        return cached

    org_id = request.session.get("active_org_id")

    if not org_id:
        # No org set in session — default to the first one the user belongs to
        first_org = get_user_organizations(request.user.id).first()
        if first_org:
            request.session["active_org_id"] = first_org.id
        request._active_org_cache = first_org
        return first_org

    # Verify the user still belongs to the stored org
    # (they could have been removed since last session).
    # select_related avoids a second query when we later access membership.organization.
    membership = get_user_membership(request.user.id, org_id)
    if not membership:
        # They no longer belong — clear the stale session value
        request.session.pop("active_org_id", None)
        # Fall back to first available org
        first_org = get_user_organizations(request.user.id).first()
        if first_org:
            request.session["active_org_id"] = first_org.id
        request._active_org_cache = first_org
        return first_org

    result = membership.organization
    # cache the result on the request object so subsequent calls are free and do not hit the DB again during the same request lifecycle.
    request._active_org_cache = result
    return result

# Invite by username

def send_org_invite(dto) -> OrganizationInvite:
    """
    Send a direct invite to a user by username.
    Creates an OrganizationInvite + inbox Notification + email.
    The invite must be accepted or rejected from the inbox — it does NOT add
    the user immediately.
    """
    _require_admin_or_owner(dto.acting_user_id, dto.organization_id)

    try:
        org = Organization.objects.get(pk=dto.organization_id)
    except Organization.DoesNotExist:
        raise ServiceError("Organization not found.")

    try:
        target_user = User.objects.get(username__iexact=dto.target_username, is_active=True)
    except User.DoesNotExist:
        raise ServiceError(f"No active user found with username '{dto.target_username}'.")

    if Membership.objects.filter(user=target_user, organization_id=dto.organization_id).exists():
        raise ServiceError(f"{target_user.username} is already a member of this organization.")

    # Block duplicate pending invites
    if OrganizationInvite.objects.filter(
        organization_id=dto.organization_id,
        invited_user=target_user,
        status=OrganizationInvite.STATUS_PENDING,
    ).exists():
        raise ServiceError(f"{target_user.username} already has a pending invite to this organization.")

    acting_user = User.objects.get(pk=dto.acting_user_id)

    invite = OrganizationInvite.objects.create(
        organization_id=dto.organization_id,
        invited_by=acting_user,
        invited_user=target_user,
        role=dto.role,
        expires_at=timezone.now() + timedelta(days=3),
    )

    # Inbox notification for the invited user
    Notification.objects.create(
        recipient=target_user,
        type=Notification.Type.ORG_INVITE,
        title=f"You've been invited to {org.name}",
        body=(
            f"{acting_user.get_full_name() or acting_user.username} invited you to join "
            f"{org.name} as {invite.role}. This invite expires in 3 days."
        ),
        org_invite=invite,
    )

    logger.info("Invite sent to %s for org %s by user %s",
                target_user.username, org.name, acting_user.username)
    return invite


def respond_to_invite(dto: RespondToInviteDTO):
    """Accept or reject a pending org invite from the inbox."""
    try:
        invite = OrganizationInvite.objects.select_related(
            "organization", "invited_by", "invited_user"
        ).get(uuid=dto.invite_uuid, invited_user_id=dto.acting_user_id)
        
    except OrganizationInvite.DoesNotExist:
        raise ServiceError("Invite not found.")

    if invite.status != OrganizationInvite.STATUS_PENDING:
        raise ServiceError("This invite has already been responded to.")

    if timezone.now() > invite.expires_at:
        invite.status = OrganizationInvite.STATUS_EXPIRED
        invite.save()
        raise ServiceError("This invite has expired.")

    # Accepting the invite creates a new membership. We check for an existing membership first
    if dto.accept:
        if Membership.objects.filter(user_id=dto.acting_user_id, organization=invite.organization).exists():
            invite.status = OrganizationInvite.STATUS_ACCEPTED
            invite.save()
            raise ServiceError("You are already a member of this organization.")

        with transaction.atomic():
            Membership.objects.create(
                user_id=dto.acting_user_id,
                organization=invite.organization,
                role=invite.role,
                invited_by=invite.invited_by,
            )
            invite.status = OrganizationInvite.STATUS_ACCEPTED
            invite.save()

        # Notify the person who sent the invite
        Notification.objects.create(
            recipient=invite.invited_by,
            type=Notification.Type.INVITE_ACCEPTED,
            title="Invite accepted",
            body=(
                f"{invite.invited_user.get_full_name() or invite.invited_user.username} "
                f"accepted your invite to {invite.organization.name}."
            ),
        )

        logger.info("Invite %s accepted by user %s", dto.invite_uuid, dto.acting_user_id)
        try:
            joined_user = User.objects.get(pk=dto.acting_user_id)
            act.member_joined(joined_user, invite.organization)
        except Exception:
            pass
        return True, f"You've joined {invite.organization.name}!"

    else:
        invite.status = OrganizationInvite.STATUS_REJECTED
        invite.save()

        Notification.objects.create(
            recipient=invite.invited_by,
            type=Notification.Type.INVITE_REJECTED,
            title="Invite declined",
            body=(
                f"{invite.invited_user.get_full_name() or invite.invited_user.username} "
                f"declined your invite to {invite.organization.name}."
            ),
        )

        logger.info("Invite %s rejected by user %s", dto.invite_uuid, dto.acting_user_id)
        return False, "Invite declined."


def get_pending_invites_sent(organization_id: int):
    """Pending outgoing invites (for admin view in settings)."""
    return OrganizationInvite.objects.filter(
        organization_id=organization_id,
        status=OrganizationInvite.STATUS_PENDING,
        expires_at__gt=timezone.now(),
    ).select_related("invited_user", "invited_by")


# Invite links

def generate_invite_link(dto: GenerateInviteLinkDTO) -> InviteLink:
    """
    Generate a new invite link for the org.
    Deactivates any existing active links first — one link at a time.
    Expires in 48 hours, max 10 uses, requires approval.
    """
    _require_admin_or_owner(dto.acting_user_id, dto.organization_id)

    # Deactivate old links
    InviteLink.objects.filter(organization_id=dto.organization_id, is_active=True).update(is_active=False)

    # Create new link
    link = InviteLink.objects.create(
        organization_id=dto.organization_id,
        created_by_id=dto.acting_user_id,
        expires_at=timezone.now() + timedelta(hours=48),
    )

    logger.info("Invite link generated for org %s by user %s", dto.organization_id, dto.acting_user_id)
    return link


def get_active_invite_link(organization_id: int):
    """Return the current valid invite link, or None."""
    link = InviteLink.objects.filter(
        organization_id=organization_id,
        is_active=True,
        expires_at__gt=timezone.now(),
    ).first()

    if link and link.use_count >= link.max_uses:
        return None
    return link


def process_link_join(dto: ProcessLinkJoinDTO) -> LinkJoinRequest:
    """
    Called when a logged-in user submits the join form via an invite link.
    Creates a pending join request and notifies all admins/owners via inbox.
    """
    try:
        link = InviteLink.objects.select_related("organization").get(uuid=dto.token)
    except InviteLink.DoesNotExist:
        raise ServiceError("This invite link is invalid.")

    if not link.is_valid:
        raise ServiceError("This invite link has expired or reached its maximum uses.")

    if Membership.objects.filter(user_id=dto.user_id, organization=link.organization).exists():
        raise ServiceError("You are already a member of this organization.")

    # Prevent double-requesting on the same link
    if LinkJoinRequest.objects.filter(
        invite_link=link, user_id=dto.user_id, status=LinkJoinRequest.STATUS_PENDING
    ).exists():
        raise ServiceError("You already have a pending request to join this organization.")

    from django.db.models import F
 
    join_request = LinkJoinRequest.objects.create(invite_link=link, user_id=dto.user_id)
 
    # Use F() to atomically increment — avoids a read-modify-write race where
    # two simultaneous requests both read the same count and one increment is lost.
    InviteLink.objects.filter(pk=link.pk).update(use_count=F("use_count") + 1)

    user = User.objects.get(pk=dto.user_id)
    org = link.organization

    # Notify all admins and owners via inbox
    admin_memberships = Membership.objects.filter(
        organization=org,
        role__in=[Membership.Role.OWNER, Membership.Role.ADMIN],
    ).select_related("user")

    for m in admin_memberships:
        Notification.objects.create(
            recipient=m.user,
            type=Notification.Type.JOIN_REQUEST,
            title=f"New join request for {org.name}",
            body=f"{user.get_full_name() or user.username} (@{user.username}) wants to join {org.name}.",
            join_request=join_request,
        )

    logger.info("Join request created: user %s -> org %s", dto.user_id, org.name)
    return join_request


def get_pending_join_requests(organization_id: int):
    """Pending join requests for all active links in an org (for admin view)."""
    return LinkJoinRequest.objects.filter(
        invite_link__organization_id=organization_id,
        status=LinkJoinRequest.STATUS_PENDING,
    ).select_related("user", "invite_link__organization")


def respond_to_join_request(dto: RespondToJoinRequestDTO):
    """Admin/owner approves or rejects a join request."""
    try:
        join_req = LinkJoinRequest.objects.select_related(
            "invite_link__organization", "user"
        ).get(uuid=dto.join_request_uuid)
    except LinkJoinRequest.DoesNotExist:
        raise ServiceError("Join request not found.")

    org = join_req.invite_link.organization
    _require_admin_or_owner(dto.acting_user_id, org.id)

    if join_req.status != LinkJoinRequest.STATUS_PENDING:
        raise ServiceError("This request has already been handled.")

    if dto.approve:
        if Membership.objects.filter(user=join_req.user, organization=org).exists():
            join_req.status = LinkJoinRequest.STATUS_APPROVED
            join_req.save()
            raise ServiceError(f"{join_req.user.username} is already a member.")

        with transaction.atomic():
            Membership.objects.create(
                user=join_req.user,
                organization=org,
                role=join_req.invite_link.role,
                invited_by_id=dto.acting_user_id,
            )
            join_req.status = LinkJoinRequest.STATUS_APPROVED
            join_req.save()

        Notification.objects.create(
            recipient=join_req.user,
            type=Notification.Type.REQUEST_APPROVED,
            title="Join request approved",
            body=f"Your request to join {org.name} has been approved. Welcome!",
        )

        logger.info("Join request %s approved: user %s -> org %s",
                    dto.join_request_uuid, join_req.user.username, org.name)
        return True, f"{join_req.user.username} has been added to {org.name}."

    else:
        join_req.status = LinkJoinRequest.STATUS_REJECTED
        join_req.save()

        Notification.objects.create(
            recipient=join_req.user,
            type=Notification.Type.REQUEST_REJECTED,
            title="Join request declined",
            body=f"Your request to join {org.name} was not approved.",
        )

        logger.info("Join request %s rejected for user %s", dto.join_request_uuid, join_req.user.username)
        return False, f"{join_req.user.username}'s request has been declined."


# Notifications (inbox)

def get_user_notifications(user_id: int):
    return Notification.objects.filter(recipient_id=user_id).select_related(
        "org_invite__organization",
        "org_invite__invited_by",
        "join_request__invite_link__organization",
        "join_request__user",
    )


def get_unread_notification_count(user_id: int) -> int:
    return Notification.objects.filter(recipient_id=user_id, is_read=False).count()


def mark_all_notifications_read(user_id: int):
    Notification.objects.filter(recipient_id=user_id, is_read=False).update(is_read=True)


# Transfer ownership 

def transfer_ownership(dto: TransferOwnershipDTO):
    """
    Transfer ownership from the current owner to another member.
    - The current owner becomes an admin.
    - The target member becomes the owner.
    Both changes happen in one atomic transaction so there is never
    a moment with zero owners or two owners.
    """
    current_owner_membership = _require_owner(dto.acting_user_id, dto.organization_id)

    try:
        target_membership = Membership.objects.select_related("user").get(
            uuid=dto.target_membership_uuid,
            organization_id=dto.organization_id,
        )
    except Membership.DoesNotExist:
        raise ServiceError("That member does not exist in this organization.")

    if target_membership.user_id == dto.acting_user_id:
        raise ServiceError("You are already the owner.")

    if target_membership.is_owner:
        raise ServiceError("That member is already the owner.")

    with transaction.atomic():
        current_owner_membership.role = Membership.Role.ADMIN
        current_owner_membership.save(update_fields=["role"])

        target_membership.role = Membership.Role.OWNER
        target_membership.save(update_fields=["role"])

    logger.info(
        "Ownership of org %s transferred from user %s to user %s",
        dto.organization_id, dto.acting_user_id, target_membership.user_id,
    )
    return target_membership


# Disable invite link
def disable_invite_link(dto: DisableInviteLinkDTO):
    """
    Deactivate the current active invite link without generating a new one.
    After this, no link is active until the admin generates a fresh one.
    """
    _require_admin_or_owner(dto.acting_user_id, dto.organization_id)

    deactivated = InviteLink.objects.filter(
        organization_id=dto.organization_id,
        is_active=True,
    ).update(is_active=False)

    if not deactivated:
        raise ServiceError("There is no active invite link to disable.")

    logger.info("Invite link disabled for org %s by user %s", dto.organization_id, dto.acting_user_id)