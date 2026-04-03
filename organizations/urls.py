from django.urls import path
from . import views

app_name = "organizations"

urlpatterns = [
    # Organization list & create
    path("", views.org_list, name="list"),
    path("create/", views.org_create, name="create"),

    # Inbox
    path("inbox/", views.inbox, name="inbox"),

    # Direct invite accept/reject (no org_slug — the invite knows its org)
    path("invites/<uuid:invite_uuid>/accept/", views.accept_invite, name="accept_invite"),
    path("invites/<uuid:invite_uuid>/reject/", views.reject_invite, name="reject_invite"),

    # Invite link landing page (token = InviteLink UUID)
    path("join/<uuid:token>/", views.join_via_link, name="join_via_link"),

    # Per-org actions
    path("<slug:org_slug>/switch/", views.org_switch, name="switch"),
    path("<slug:org_slug>/settings/", views.org_settings, name="settings"),
    path("<slug:org_slug>/update/", views.org_update, name="update"),
    path("<slug:org_slug>/delete/", views.org_delete, name="delete"),
    path("<slug:org_slug>/leave/", views.org_leave, name="leave"),

    # Member management
    path("<slug:org_slug>/members/invite/",
         views.org_invite_member, name="invite_member"),
    path("<slug:org_slug>/members/<uuid:membership_uuid>/remove/",
         views.org_remove_member, name="remove_member"),
    path("<slug:org_slug>/members/<uuid:membership_uuid>/role/",
         views.org_change_member_role, name="change_member_role"),

    # Invite link
    path("<slug:org_slug>/invite-link/generate/",
         views.generate_invite_link_view, name="generate_invite_link"),

    # Join requests (approve/reject)
    path("<slug:org_slug>/join-requests/<uuid:join_request_uuid>/approve/",
         views.approve_join_request, name="approve_join_request"),
    path("<slug:org_slug>/join-requests/<uuid:join_request_uuid>/reject/",
         views.reject_join_request, name="reject_join_request"),

    # Transfer ownership
    path("<slug:org_slug>/transfer-ownership/",
         views.transfer_ownership_view, name="transfer_ownership"),

    # Disable invite link
    path("<slug:org_slug>/invite-link/disable/",
         views.disable_invite_link_view, name="disable_invite_link"),

    # Org logo upload / remove
    path("<slug:org_slug>/logo/upload/", views.org_upload_logo, name="upload_logo"),
    path("<slug:org_slug>/logo/remove/", views.org_remove_logo, name="remove_logo"),
]