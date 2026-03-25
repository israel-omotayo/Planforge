from django.core.validators import MaxLengthValidator
from django.db import models
from django.contrib.auth.models import User
from organizations.models import Organization
import uuid

# Create your models here.

# Project — a unit of work that belongs to an Organization.
#
# Design decisions:
# - Projects belong to ONE organization
# - created_by is SET_NULL so projects survive if their creator leaves
# - Status is a controlled vocabulary (TextChoices) not a free-text field

class Project(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On Hold"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    class Currency(models.TextChoices):
        USD = "USD", "USD — US Dollar"
        EUR = "EUR", "EUR — Euro"
        GBP = "GBP", "GBP — British Pound"
        CAD = "CAD", "CAD — Canadian Dollar"
        AUD = "AUD", "AUD — Australian Dollar"
        NGN = "NGN", "NGN — Nigerian Naira"
        GHS = "GHS", "GHS — Ghanaian Cedi"
        KES = "KES", "KES — Kenyan Shilling"
        ZAR = "ZAR", "ZAR — South African Rand"  

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )      

    name = models.CharField(max_length=50)

    description = models.TextField(blank=True, default="", validators=[MaxLengthValidator(1000)])

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="projects"
    )

    # Who created the project inside the org.
    # SET_NULL — if they leave, the project stays.
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_projects"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    budget = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )

    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.USD,
    )

    cover_image_url = models.CharField(max_length=1000, blank=True, default="")
    cover_image_public_id = models.CharField(max_length=500,  blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    # Convenience status-check properties
    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def is_archived(self):
        return self.status == self.Status.ARCHIVED
    
    @property
    def budget_display(self):
        """Human-readable budget string, e.g. 'USD 12,500.00' or 'Not set'."""
        if self.budget is None:
            return "Not set"
        return f"{self.currency} {self.budget:,.2f}"


class Task(models.Model):
    """
    A unit of work inside a Project.

    Design decisions:
    - Tasks belong to ONE project (and inherit the org through the project)
    - assigned_to and created_by are SET_NULL so tasks survive member removal
    - due_date is optional — not all tasks have deadlines
    - Status and Priority use TextChoices for type safety
    """

    class Status(models.TextChoices):
        TODO = "todo", "To Do"
        IN_PROGRESS = "in_progress", "In Progress"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks"
    )

    title = models.CharField(max_length=50)

    description = models.TextField(blank=True, default="", validators=[MaxLengthValidator(500)])

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
        db_index=True,
    )

    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )

    due_date = models.DateField(null=True, blank=True, db_index=True)

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks"
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tasks"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Task"
        verbose_name_plural = "Tasks"
        ordering = ["status", "-priority", "due_date", "created_at"]

    def __str__(self):
        return f"{self.title} ({self.project.name})"

    @property
    def is_done(self):
        return self.status == self.Status.DONE

    @property
    def is_overdue(self):
        """True if the task has a due date in the past and is not done."""
        if not self.due_date or self.is_done:
            return False
        from django.utils import timezone
        return self.due_date < timezone.now().date()

class ActivityLog(models.Model):
    """
    An immutable record of something that happened inside an organization.

    Design decisions:
    - Org-scoped so we can show a full org feed as well as per-project feeds.
    - project is nullable — some events (member invited, role changed) don't
      belong to a specific project.
    - actor is SET_NULL so logs survive when a user is deleted.
    - verb + detail are plain text; no foreign-key to the affected object so
      logs survive deletions without orphaned rows.
    - Deliberately no update/delete on this model — logs are append-only.
    """

    class Verb(models.TextChoices):
        # Project events
        PROJECT_CREATED = "project_created", "created project"
        PROJECT_UPDATED = "project_updated", "updated project"
        PROJECT_DELETED = "project_deleted", "deleted project"
        # Task events
        TASK_CREATED = "task_created", "created task"
        TASK_UPDATED = "task_updated", "updated task"
        TASK_DELETED = "task_deleted", "deleted task"
        TASK_COMPLETED = "task_completed", "completed task"
        TASK_REOPENED = "task_reopened", "reopened task"
        # Member events
        MEMBER_INVITED = "member_invited", "invited member"
        MEMBER_JOINED = "member_joined", "joined organization"
        MEMBER_REMOVED = "member_removed", "removed member"
        MEMBER_LEFT = "member_left", "left"
        ROLE_CHANGED = "role_changed", "changed role"
        # Attachment events
        ATTACHMENT_ADDED = "attachment_added", "attached file"
        ATTACHMENT_REMOVED = "attachment_removed", "removed attachment"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="activity_logs",
        db_index=True,
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )

    verb = models.CharField(max_length=30, choices=Verb.choices, db_index=True)
    detail = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["project", "-created_at"]),
        ]

    def __str__(self):
        actor = self.actor.username if self.actor else "Someone"
        return f"{actor} {self.get_verb_display()} — {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def actor_name(self):
        if not self.actor:
            return "Someone"
        full_name = self.actor.get_full_name()
        if full_name:
            return f"{full_name} (@{self.actor.username})"
        return f"@{self.actor.username}"

    @property
    def icon(self):
        """Returns a simple category string used for icon selection in templates."""
        if self.verb.startswith("project_"):
            return "project"
        if self.verb.startswith("task_"):
            return "task"
        return "member"

class ProjectMembership(models.Model):
    """
    Grants a user access to a single project as a guest or editor.
    Used for external collaborators who should NOT have full org access.
    Org members already have implicit project access via their Membership.
    """
    class Role(models.TextChoices):
        GUEST = "guest", "Guest"   # read + create/edit tasks, no admin actions
        EDITOR = "editor", "Editor"  # same as guest for now, reserved for expansion

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="guest_memberships",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="project_memberships",
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.GUEST,
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_project_invites",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Project Membership"
        verbose_name_plural = "Project Memberships"
        unique_together = ("project", "user")
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user.username} — {self.project.name} ({self.role})"


class ProjectGuestInvite(models.Model):
    """
    An email-based invitation to join a specific project as a guest.
    Works for both existing Planforge users and brand-new users.
    Expires 7 days after creation.
    """
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING,  "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_EXPIRED,  "Expired"),
    ]

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="guest_invites")
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="sent_guest_invites")
    email = models.EmailField()
    # Set if the email matched an existing account at invite time. May be null
    # for invites sent to people who don't have a Planforge account yet.
    invited_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_guest_invites",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "Project Guest Invite"
        verbose_name_plural = "Project Guest Invites"
        ordering = ["-created_at"]

    def __str__(self):
        return f"GuestInvite: {self.email} → {self.project.name} ({self.status})"

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING


class TaskAttachment(models.Model):
    """
    A file attached to a Task.
    Files are stored on Cloudinary. The DB only stores the public_id (for
    deletion) and secure_url (for serving). No files are kept on the server.
    Cloudinary is configured via the CLOUDINARY_URL environment variable.
    """

    ALLOWED_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".pdf",
        ".doc", ".docx",
        ".xls", ".xlsx",
        ".ppt", ".pptx",
        ".txt", ".csv",
        ".zip",
    }
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    uploaded_by = models.ForeignKey(
        "auth.User", # use string reference to avoid circular import with auth.User
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_attachments",
    )

    cloudinary_public_id = models.CharField(max_length=500)   # used for deletion
    cloudinary_url = models.CharField(max_length=1000)  # CDN URL for serving
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()   # bytes
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Task Attachment"
        verbose_name_plural = "Task Attachments"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.original_filename} → {self.task.title}"

    @property
    def size_display(self):
        """Human-readable file size."""
        kb = self.file_size / 1024
        if kb < 1024:
            return f"{kb:.0f} KB"
        return f"{kb / 1024:.1f} MB"

    @property
    def extension(self):
        import os
        return os.path.splitext(self.original_filename)[1].lower()

    @property
    def is_image(self):
        return self.extension in {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    @property
    def icon_type(self):
        """Returns 'image', 'pdf', 'doc', 'sheet', 'slide', or 'file'."""
        ext = self.extension
        if self.is_image:
            return "image"
        if ext == ".pdf":
            return "pdf"
        if ext in {".doc", ".docx", ".txt"}:
            return "doc"
        if ext in {".xls", ".xlsx", ".csv"}:
            return "sheet"
        if ext in {".ppt", ".pptx"}:
            return "slide"
        return "file"