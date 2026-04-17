from django.urls import path
from . import views

app_name = "projects"

urlpatterns = [
    # Project CRUD
    path("", views.project_list, name="list"),
    path("create/", views.project_create, name="create"),
    path("<uuid:project_uuid>/", views.project_detail, name="detail"),
    path("<uuid:project_uuid>/edit/", views.project_edit, name="edit"),
    path("<uuid:project_uuid>/delete/", views.project_delete, name="delete"),

    # Task CRUD (scoped under their project)
    path("<uuid:project_uuid>/tasks/create/", views.task_create, name="task_create"),
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/edit/", views.task_edit, name="task_edit"),
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/delete/", views.task_delete, name="task_delete"),
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/status/", views.task_status, name="task_status"),
    path("my-tasks/", views.my_tasks, name="my_tasks"),

    # Task attachments
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/attachments/upload/",
         views.task_attachment_upload, name="attachment_upload"),
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/attachments/<int:attachment_id>/view/", 
         views.attachment_view, name="attachment_view"),     
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/attachments/<int:attachment_id>/delete/",
         views.task_attachment_delete, name="attachment_delete"),
    # AI task generator
    path("<uuid:project_uuid>/tasks/ai-generate/", views.ai_generate_tasks, name="ai_generate_tasks"),
    path("<uuid:project_uuid>/tasks/ai-create/", views.ai_create_tasks, name="ai_create_tasks"), 

    # Activity log
    path("<uuid:project_uuid>/activity/", views.project_activity, name="project_activity"),

    # Project guest access
    path("<uuid:project_uuid>/guests/invite/", views.invite_guest, name="invite_guest"),
    path("<uuid:project_uuid>/leave/", views.leave_project, name="leave_project"),
    path("<uuid:project_uuid>/guests/<uuid:guest_uuid>/remove/", views.remove_guest, name="remove_guest"),
    path("guest-invite/<uuid:invite_uuid>/accept/", views.accept_guest_invite, name="accept_guest_invite"),
    path("guest-invite/<uuid:invite_uuid>/decline/", views.decline_guest_invite, name="decline_guest_invite"),

    # Task comments
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/comments/add/",
         views.task_comment_add, name="task_comment_add"),
    path("<uuid:project_uuid>/tasks/<uuid:task_uuid>/comments/<int:comment_id>/delete/",
         views.task_comment_delete, name="task_comment_delete"),
]