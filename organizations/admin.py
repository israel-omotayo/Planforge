from django.contrib import admin
from .models import Organization, Membership

# Register your models here.

class MembershipInline(admin.TabularInline):
    """
    Show memberships directly inside the Organization admin page.
    Inline means you see all members on the org detail screen
    without navigating to a separate Membership page.
    """
    model = Membership
    extra = 0  # Don't show empty extra rows by default
    fields = ("user", "role", "joined_at")
    readonly_fields = ("joined_at",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_by", "created_at")
    search_fields = ("name", "slug", "created_by__username")
    readonly_fields = ("slug", "created_at", "updated_at")
    # when you view an organization in the admin, also show the membershipinline table
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display  = ("user", "organization", "role", "joined_at")
    list_filter = ("role",)
    search_fields = ("user__username", "organization__name")
    readonly_fields = ("joined_at",)
