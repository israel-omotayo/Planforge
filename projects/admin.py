from django.contrib import admin
from .models import Project, ActivityLog, TaskAttachment, ProjectMembership, ProjectGuestInvite

# Register your models here.
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "status", "created_by", "created_at")
    list_filter = ("status", "organization")
    search_fields = ("name", "organization__name", "created_by__username")
    readonly_fields = ("created_at", "updated_at")

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "verb", "detail", "project", "organization", "created_at")
    list_filter = ("verb", "organization")
    search_fields = ("detail", "actor__username", "project__name")
    readonly_fields = ("actor", "verb", "detail", "project", "organization", "created_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False   # logs are append-only

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "task", "uploaded_by", "file_size", "created_at")
    list_filter = ("created_at",)
    search_fields = ("original_filename", "task__title", "uploaded_by__username")
    readonly_fields = ("task", "uploaded_by", "cloudinary_public_id", "cloudinary_url", "original_filename", "file_size", "created_at")
 
    def has_add_permission(self, request):
        return False

@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "project", "role", "invited_by", "joined_at")
    list_filter = ("role",)
    search_fields = ("user__username", "project__name")
    readonly_fields = ("joined_at",)

@admin.register(ProjectGuestInvite)
class ProjectGuestInviteAdmin(admin.ModelAdmin):
    list_display = ("email", "project", "status", "invited_by", "created_at", "expires_at")
    list_filter = ("status",)
    search_fields = ("email", "project__name")
    readonly_fields = ("created_at",)
