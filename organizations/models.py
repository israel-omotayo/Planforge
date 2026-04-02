from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
import uuid
from django.utils import timezone

# Create your models here.

# Organization — the top-level SaaS tenant.
# A user can create or belong to multiple organizations.
#
# Membership — the join table between User and Organization.
# Every user inside an organization has exactly one membership record,
# which carries their role (owner, admin, or member)

class Organization(models.Model):
    # The organization name shown in the UI
    name = models.CharField(max_length=30)

    # URL-safe version of the name — used in routes like /org/meridian-studio/
    # Unique so two orgs can't share a URL slug.
    slug = models.SlugField(max_length=160, unique=True, blank=True)

    # Who created this organization — they become the owner automatically.
    # SET_NULL so the org survives if the creator deletes their account.
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_organizations"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Auto-generate slug from name if not already set.
        # Appends a short unique suffix to prevent collisions
        # e.g. "Meridian Studio" → "meridian-studio-a1b2"
        if not self.slug:
            #slugify converts the name to a slug
            base_slug = slugify(self.name)
            #unique_bit is a random 6-character string to ensure uniqueness of the slug
            unique_bit = uuid.uuid4().hex[:6]
            #combine base_slug and unique_bit to create the final slug
            self.slug = f"{base_slug}-{unique_bit}"
        # Call the parent save method to actually save the object to the database
        super().save(*args, **kwargs)


class Membership(models.Model):

    class Role(models.TextChoices):
        OWNER  = "owner",  "Owner"
        ADMIN  = "admin",  "Admin"
        MEMBER = "member", "Member"

    #gives each membership a unique UUID for easy reference in URLs and APIs
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships"
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Membership"
        verbose_name_plural = "Memberships"
        # A user can only have ONE membership per organization.
        # This is enforced at the database level, not just application level.
        unique_together = ("user", "organization")
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user.username} — {self.organization.name} ({self.role})"

    # Convenience role-check properties
    # Use these in templates and views instead of comparing strings directly.
    # e.g.  {% if membership.is_owner %}  rather than  {% if membership.role == 'owner' %}

    @property
    # is_owner is a property that returns True if the membership role is 'owner'
    # allows you to use membership.is_owner instead of checking membership.role == 'owner' everywhere
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_admin_or_owner(self):
        # is_admin_or_owner is a property that returns True if the membership role is either 'admin' or 'owner'
        #This is useful for permission checks where both admins and owners should have access.
        return self.role in (self.Role.OWNER, self.Role.ADMIN)
    
class OrganizationInvite(models.Model):
    """
    A direct invite from an admin/owner to a specific user by username.
    The invited user gets an inbox notification and can accept or reject.
    Expires 3 days after creation.
    """
    STATUS_PENDING  = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED  = "expired"
    STATUS_CHOICES  = [
        (STATUS_PENDING,  "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED,  "Expired"),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invites")
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_org_invites")
    invited_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_org_invites")
    role = models.CharField(max_length=10, choices=Membership.Role.choices, default=Membership.Role.MEMBER)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite: {self.invited_user.username} -> {self.organization.name} ({self.status})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING
    
class InviteLink(models.Model):
    """
    A shareable link. Anyone with it can request to join.
    Requires admin/owner approval. Max 10 uses, 48-hour expiry.
    """
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invite_links")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_invite_links")
    role = models.CharField(max_length=10, choices=Membership.Role.choices, default=Membership.Role.MEMBER)
    max_uses = models.PositiveIntegerField(default=10)
    use_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"InviteLink for {self.organization.name}"

    @property
    def is_valid(self):
        return (
            self.is_active
            and timezone.now() < self.expires_at
            and self.use_count < self.max_uses
        )

    @property
    def spots_remaining(self):
        return self.max_uses - self.use_count


class LinkJoinRequest(models.Model):
    """
    Created when a logged-in user clicks an InviteLink.
    Stays pending until an admin/owner approves or rejects it.
    """
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES  = [
        (STATUS_PENDING,  "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    invite_link = models.ForeignKey(InviteLink, on_delete=models.CASCADE, related_name="join_requests")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="join_requests")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("invite_link", "user")
        ordering = ["-created_at"]

    def __str__(self):
        return f"JoinRequest: {self.user.username} -> {self.invite_link.organization.name} ({self.status})"


class Notification(models.Model):
    """
    A single inbox message for a user.
    Linked to either an OrganizationInvite or a LinkJoinRequest
    so the user can take action directly from the inbox.
    """
    class Type(models.TextChoices):
        ORG_INVITE = "org_invite", "Organization Invite"
        JOIN_REQUEST = "join_request", "Join Request"
        INVITE_ACCEPTED = "invite_accepted", "Invite Accepted"
        INVITE_REJECTED = "invite_rejected", "Invite Rejected"
        REQUEST_APPROVED = "request_approved", "Request Approved"
        REQUEST_REJECTED = "request_rejected", "Request Rejected"
        TASK_ASSIGNED = "task_assigned", "Task Assigned"
        PROJECT_GUEST_INVITE = "project_guest_invite", "Project Guest Invite" 

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    is_read = models.BooleanField(default=False, db_index=True)
    org_invite = models.ForeignKey(
        OrganizationInvite, on_delete=models.CASCADE,
        null=True, blank=True, related_name="notifications"
    )
    join_request = models.ForeignKey(
        LinkJoinRequest, on_delete=models.CASCADE,
        null=True, blank=True, related_name="notifications"
    )
    project_guest_invite = models.ForeignKey(
    'projects.ProjectGuestInvite',
    on_delete=models.CASCADE,
    null=True,
    blank=True,
    related_name="notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [models.Index(fields=["recipient", "is_read"])]

    def __str__(self):
        return f"Notification ({self.type}) for {self.recipient.username}"