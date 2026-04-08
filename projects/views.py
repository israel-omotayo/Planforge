import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_GET

from organizations.decorators import org_admin_required, org_member_required
from organizations.services import get_organization_members
from .decorators import project_access_required, project_admin_required
from .forms import CreateProjectForm, UpdateProjectForm, TaskForm
from .models import Project, Task, ActivityLog, TaskAttachment, ProjectMembership, ProjectGuestInvite, TaskComment
from .services import TaskAccess, get_task_access
from . import services
from . import activity as act
from .schemas import CreateTaskDTO, UpdateTaskDTO, DeleteTaskDTO, UpdateTaskStatusDTO, InviteGuestDTO, AcceptGuestInviteDTO
from django.http import JsonResponse
from django.urls import reverse

logger = logging.getLogger(__name__)

# Verbs visible to project guests — task, attachment, and comment events only.
# Member events, role changes, and project edits are hidden.
_TASK_VERBS = {
    ActivityLog.Verb.TASK_CREATED,
    ActivityLog.Verb.TASK_UPDATED,
    ActivityLog.Verb.TASK_DELETED,
    ActivityLog.Verb.TASK_COMPLETED,
    ActivityLog.Verb.TASK_REOPENED,
    ActivityLog.Verb.ATTACHMENT_ADDED,
    ActivityLog.Verb.ATTACHMENT_REMOVED,
    ActivityLog.Verb.COMMENT_ADDED,
}


# Project list 

@login_required
@require_GET
def project_list(request):
    """
    List projects accessible to the current user.
    - Org members: see all projects in the active org.
    - Always also shows any guest projects from other orgs as a separate section.
    - Pure guests (no org membership anywhere): see only their guest projects.
    """
    from organizations.services import get_active_organization, get_user_membership

    active_org = get_active_organization(request)
    membership = get_user_membership(request.user.id, active_org.id) if active_org else None

    # Guest projects — always fetch, regardless of org membership
    guest_memberships = ProjectMembership.objects.filter(
        user=request.user
    ).select_related("project", "project__organization").order_by("-project__created_at")

    # Exclude guest projects that belong to the active org (they already appear above)
    if active_org:
        guest_memberships = guest_memberships.exclude(project__organization=active_org)

    guest_projects = [gm.project for gm in guest_memberships]

    if membership:
        # Full org member — show all org projects + guest projects below
        from django.db.models import Count, Q

        q = request.GET.get("q", "").strip()
        status = request.GET.get("status", "")
        sort = request.GET.get("sort", "-created_at")

        ALLOWED_SORTS = {"-created_at", "created_at", "name", "-name"}
        if sort not in ALLOWED_SORTS:
            sort = "-created_at"

        projects = (
            Project.objects
            .filter(organization=active_org)
            .annotate(
                task_total=Count("tasks"),
                task_done=Count("tasks", filter=Q(tasks__status="done")),
            )
            .select_related("created_by")
        )
        if q:
            projects = projects.filter(name__icontains=q)
        if status:
            projects = projects.filter(status=status)
        projects = projects.order_by(sort)

        paginator = Paginator(projects, 25)
        page = paginator.get_page(request.GET.get("page"))

        return render(request, "projects/list.html", {
            "projects": page,
            "page_obj": page,
            "org": active_org,
            "membership": membership,
            "is_guest_only": False,
            "guest_projects": guest_projects,
            "q": q,
            "status_filter": status,
            "sort": sort,
            "status_choices": Project.Status.choices,
        })

    # No org membership — show only guest projects
    if guest_projects:
        return render(request, "projects/list.html", {
            "projects": [],
            "page_obj": None,
            "org": None,
            "membership": None,
            "is_guest_only": True,
            "guest_projects": guest_projects,
        })

    # No access at all
    messages.warning(request, "Please select or create an organization first.")
    return redirect("organizations:list")


# Project create 

@login_required
@org_admin_required
@require_http_methods(["GET", "POST"])
def project_create(request):
    """Only admins and owners can create projects."""
    form = CreateProjectForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.organization = request.active_org
        project.created_by = request.user
        project.save()

        # Optional cover image upload to Cloudinary
        cover = request.FILES.get("cover_image")
        if cover:
            import os, cloudinary.uploader
            ext = os.path.splitext(cover.name)[1].lower()
            if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                if cover.size <= 10 * 1024 * 1024:
                    try:
                        result = cloudinary.uploader.upload(
                            cover,
                            folder=f"planforge/project_covers/{project.uuid}",
                            resource_type="image",
                            use_filename=True,
                            unique_filename=True,
                            overwrite=True,
                        )
                        project.cover_image_url = result["secure_url"]
                        project.cover_image_public_id = result["public_id"]
                        project.save(update_fields=["cover_image_url", "cover_image_public_id"])
                    except Exception:
                        logger.exception("Cover image upload failed for project %s", project.uuid)

        act.project_created(request, project)
        messages.success(request, f"'{project.name}' created.")
        return redirect("projects:detail", project_uuid=project.uuid)

    return render(request, "projects/create.html", {
        "form": form,
        "org": request.active_org,
    })


# Project detail 

@login_required
@require_GET
@project_access_required
def project_detail(request, project_uuid):
    project = request.project   # set by project_access_required
    form = UpdateProjectForm(instance=project)
    org_members = get_organization_members(request.active_org.id) if not request.is_project_guest else []
    guest_memberships = ProjectMembership.objects.filter(project=project).select_related("user", "invited_by")
    task_form = TaskForm(org_members=org_members, guest_members=guest_memberships)
    task_stats = services.get_task_stats(project.id)
    task_q = request.GET.get("task_q", "").strip()
    task_priority = request.GET.get("priority", "")
    task_assignee = request.GET.get("assignee", "")
    task_sort = request.GET.get("task_sort", "created_at")
    overdue_only = request.GET.get("overdue_only") == "1"

    assignee_id = None
    if task_assignee:
        try:
            assignee_id = int(task_assignee)
        except ValueError:
            pass

    tasks = services.get_tasks_for_project(
        project.id,
        q=task_q,
        priority=task_priority,
        assignee_id=assignee_id,
        overdue_only=overdue_only,
        sort=task_sort,
    )
    org_members_ids = [m.user_id for m in org_members]
    # Group tasks by status for the kanban-style section display
    all_todo = [t for t in tasks if t.status == Task.Status.TODO]
    all_in_progress = [t for t in tasks if t.status == Task.Status.IN_PROGRESS]
    all_done = [t for t in tasks if t.status == Task.Status.DONE]
    todo_page = Paginator(all_todo, 15).get_page(request.GET.get("todo_page"))
    ip_page = Paginator(all_in_progress, 15).get_page(request.GET.get("ip_page"))
    done_page = Paginator(all_done, 15).get_page(request.GET.get("done_page"))

    joined_at = (
    request.membership.joined_at if request.membership
    else request.project_membership.joined_at if request.project_membership
    else None
)
    log_qs = ActivityLog.objects.filter(project=project)
    if joined_at:
        log_qs = log_qs.filter(created_at__gte=joined_at)
    if request.is_project_guest:
        log_qs = log_qs.filter(verb__in=_TASK_VERBS)
    activity_logs = log_qs.select_related("actor")[:1]
    
    return render(request, "projects/detail.html", {
        "project": project,
        "org": request.active_org,
        "membership": request.membership,
        "is_project_guest": request.is_project_guest,
        "project_membership": request.project_membership,
        "guest_memberships": guest_memberships,
        "form": form,
        "task_form": task_form,
        "task_stats": task_stats,
        "priority_choices": Task.Priority.choices,
        "org_members_ids": org_members_ids,
        "tasks_todo": todo_page,
        "tasks_in_progress": ip_page,
        "tasks_done": done_page,
        "todo_page_obj": todo_page,
        "ip_page_obj": ip_page,
        "done_page_obj": done_page,
        "org_members": org_members,
        "activity_logs": activity_logs,
        "activity_see_all_url": reverse("projects:project_activity", kwargs={"project_uuid": project.uuid}),
    })


# Project edit 

@login_required
@org_admin_required
@require_http_methods(["GET", "POST"])
def project_edit(request, project_uuid):
    """Only admins and owners can edit projects."""
    project = get_object_or_404(
        Project,
        uuid=project_uuid,
        organization=request.active_org
    )
    form = UpdateProjectForm(request.POST or None, request.FILES or None, instance=project)

    if request.method == "POST" and form.is_valid():
        form.save()

        # Optional cover image update
        cover = request.FILES.get("cover_image")
        if cover:
            import os, cloudinary.uploader
            ext = os.path.splitext(cover.name)[1].lower()
            if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                if cover.size <= 10 * 1024 * 1024:
                    try:
                        # Delete old cover if it exists
                        if project.cover_image_public_id:
                            try:
                                cloudinary.uploader.destroy(project.cover_image_public_id, resource_type="image")
                            except Exception:
                                pass
                        result = cloudinary.uploader.upload(
                            cover,
                            folder=f"planforge/project_covers/{project.uuid}",
                            resource_type="image",
                            use_filename=True,
                            unique_filename=True,
                            overwrite=True,
                        )
                        project.cover_image_url = result["secure_url"]
                        project.cover_image_public_id = result["public_id"]
                        project.save(update_fields=["cover_image_url", "cover_image_public_id"])
                    except Exception:
                        logger.exception("Cover image update failed for project %s", project.uuid)
        elif request.POST.get("remove_cover") == "1" and project.cover_image_public_id:
            import cloudinary.uploader
            try:
                cloudinary.uploader.destroy(project.cover_image_public_id, resource_type="image")
            except Exception:
                pass
            project.cover_image_url = ""
            project.cover_image_public_id = ""
            project.save(update_fields=["cover_image_url", "cover_image_public_id"])

        act.project_updated(request, project)
        messages.success(request, f"'{project.name}' updated.")
        return redirect("projects:detail", project_uuid=project.uuid)

    return render(request, "projects/edit.html", {
        "form": form,
        "project": project,
        "org": request.active_org,
    })


# Project delete 

@login_required
@org_admin_required
@require_POST
def project_delete(request, project_uuid):
    """Only admins and owners can delete projects."""
    project = get_object_or_404(
        Project,
        uuid=project_uuid,
        organization=request.active_org
    )
    project_name = project.name
    act.project_deleted(request, request.active_org, project_name)
    project.delete()
    messages.success(request, f"'{project_name}' deleted.")
    return redirect("projects:list")


# Task create 

def _render_detail_with_errors(request, project, task_form, open_modal, task_uuid=None):
    """
    Re-render the project detail page with a form error, keeping the modal open.
    Used by task_create and task_edit when validation fails.
    """
    is_guest = getattr(request, "is_project_guest", False)
    org_members = get_organization_members(request.active_org.id) if not is_guest else []
    # Bug fix: org_members_ids was missing from this context, causing KeyError in the
    # task edit modal template which uses it to de-duplicate guest entries.
    org_members_ids = [m.user_id for m in org_members]
    guest_memberships = ProjectMembership.objects.filter(project=project).select_related("user", "invited_by")
    task_stats = services.get_task_stats(project.id)
    task_q = request.GET.get("task_q", "").strip()
    task_priority = request.GET.get("priority", "")
    task_assignee = request.GET.get("assignee", "")
    task_sort = request.GET.get("task_sort", "created_at")
    overdue_only = request.GET.get("overdue_only") == "1"

    # Bug fix: apply the same sort whitelist as project_detail to prevent
    # arbitrary ORDER BY values reaching the database.
    ALLOWED_SORTS = {"created_at", "-created_at", "due_date", "-priority", "title"}
    if task_sort not in ALLOWED_SORTS:
        task_sort = "created_at"

    assignee_id = None
    if task_assignee:
        try:
            assignee_id = int(task_assignee)
        except ValueError:
            pass

    tasks = services.get_tasks_for_project(
        project.id,
        q=task_q,
        priority=task_priority,
        assignee_id=assignee_id,
        overdue_only=overdue_only,
        sort=task_sort,
    )
    all_todo = [t for t in tasks if t.status == Task.Status.TODO]
    all_in_progress = [t for t in tasks if t.status == Task.Status.IN_PROGRESS]
    all_done = [t for t in tasks if t.status == Task.Status.DONE]
    todo_page = Paginator(all_todo, 15).get_page(request.GET.get("todo_page"))
    ip_page = Paginator(all_in_progress, 15).get_page(request.GET.get("ip_page"))
    done_page = Paginator(all_done, 15).get_page(request.GET.get("done_page"))
    update_form = UpdateProjectForm(instance=project)

    joined_at = (
        request.membership.joined_at if request.membership
        else request.project_membership.joined_at if request.project_membership
        else None
    )
    log_qs = ActivityLog.objects.filter(project=project)
    if joined_at:
        log_qs = log_qs.filter(created_at__gte=joined_at)
    if is_guest:
        log_qs = log_qs.filter(verb__in=_TASK_VERBS)
    activity_logs = log_qs.select_related("actor")[:1]

    return render(request, "projects/detail.html", {
        "project": project,
        "org": request.active_org,
        "membership": request.membership,
        "is_project_guest": is_guest,
        "project_membership": getattr(request, "project_membership", None),
        "guest_memberships": guest_memberships,
        "form": update_form,
        "task_form": task_form,
        "task_stats": task_stats,
        "org_members_ids": org_members_ids,
        "tasks_todo": todo_page,
        "tasks_in_progress": ip_page,
        "tasks_done": done_page,
        "todo_page_obj": todo_page,
        "ip_page_obj": ip_page,
        "done_page_obj": done_page,
        "org_members": org_members,
        "open_modal": open_modal,
        "error_task_uuid": task_uuid,
        "activity_logs": activity_logs,
        "activity_see_all_url": reverse("projects:project_activity", kwargs={"project_uuid": project.uuid}),
    })


@login_required
@project_access_required
@project_admin_required
@require_POST
def task_create(request, project_uuid):
    """Any project member or guest can create tasks."""
    project = request.project
    org_members = get_organization_members(request.active_org.id) if not request.is_project_guest else []
    guest_members = ProjectMembership.objects.filter(project=project)
    form = TaskForm(request.POST, org_members=org_members, guest_members=guest_members)

    if form.is_valid():
        assigned_to = form.cleaned_data.get("assigned_to")
        due_date = form.cleaned_data.get("due_date")
        try:
            dto = CreateTaskDTO(
                project_id=project.id,
                created_by_id=request.user.id,
                title=form.cleaned_data["title"],
                description=form.cleaned_data.get("description", ""),
                status=form.cleaned_data["status"],
                priority=form.cleaned_data["priority"],
                due_date=due_date.isoformat() if due_date else None,
                assigned_to_id=assigned_to.id if assigned_to else None,
            )
            task = services.create_task(dto)
            act.task_created(request, task)
            messages.success(request, "Task added.")
            return redirect("projects:detail", project_uuid=project.uuid)
        except (services.ServiceError, ValueError) as e:
            messages.error(request, str(e))
            return redirect("projects:detail", project_uuid=project.uuid)
    else:
        return _render_detail_with_errors(
            request, project, form, open_modal="modal-add-task"
        )

# AI task generator — GET returns suggestions, POST creates selected tasks

@login_required
@project_access_required
@project_admin_required
@require_POST
def ai_generate_tasks(request, project_uuid):
    """
    Call Groq to generate task suggestions for a project.
    Returns JSON — consumed by the modal via fetch().
    """
    import json
    from django.http import JsonResponse
    from django.conf import settings
    from groq import Groq

    project = request.project
    description = request.POST.get("description", "").strip()

    if not description:
        return JsonResponse({"error": "Please describe what needs to be done."}, status=400)

    if len(description) > 500:
        return JsonResponse({"error": "Description too long. Keep it under 500 characters."}, status=400)

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        return JsonResponse({"error": "AI generation is not configured."}, status=503)

    # Build context from the project so suggestions are relevant
    existing_tasks = list(
        Task.objects
        .filter(project=project)
        .values_list("title", flat=True)
        .order_by("-created_at")[:10]
    )
    existing_context = ""
    if existing_tasks:
        existing_context = (
            f"\n\nExisting tasks already in this project (do not repeat these):\n"
            + "\n".join(f"- {t}" for t in existing_tasks)
        )

    prompt = f"""You are a project management assistant. Generate 5 to 7 clear, actionable tasks for the following project.

Project name: {project.name}
Project description: {project.description or "Not provided"}
User request: {description}{existing_context}

Rules:
- Each task title must be a full, descriptive action sentence (e.g. "Create wireframes for homepage and landing pages") — up to 100 characters
- Each description must be a complete, helpful sentence explaining the task in detail — up to 200 characters
- Priority must be exactly one of: low, medium, high
- Make tasks realistic and specific to the project context — avoid vague filler tasks
- Do not repeat existing tasks
- Return ONLY valid JSON, no explanation, no markdown, no code fences

Return this exact JSON structure:
{{
  "tasks": [
    {{"title": "Create wireframes for homepage and landing pages", "description": "Develop low-fidelity layouts to plan the structure and content placement of the homepage and key landing pages.", "priority": "high"}},
    {{"title": "Design new UI/UX mockups", "description": "Create high-fidelity visual designs including color schemes, typography, buttons, forms, and overall interface flow.", "priority": "medium"}}
  ]
}}"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if the model adds them anyway
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        tasks = data.get("tasks", [])

        # Sanitise — enforce field constraints before sending to frontend
        clean = []
        for t in tasks[:7]: # allow up to 7 tasks
            title = str(t.get("title", "")).strip()[:100]
            desc = str(t.get("description", "")).strip()[:200]
            pri = t.get("priority", "medium")
            if pri not in {"low", "medium", "high"}:
                pri = "medium"
            if title:
                clean.append({"title": title, "description": desc, "priority": pri})

        if not clean:
            return JsonResponse({"error": "No tasks generated. Try a more specific description."}, status=400)

        return JsonResponse({"tasks": clean})

    except json.JSONDecodeError:
        logger.exception("AI task generator: invalid JSON from Groq")
        return JsonResponse({"error": "AI returned an unexpected response. Please try again."}, status=500)
    except Exception:
        logger.exception("AI task generator: Groq API error")
        return JsonResponse({"error": "AI generation failed. Please try again."}, status=500)


@login_required
@project_access_required
@project_admin_required
@require_POST
def ai_create_tasks(request, project_uuid):
    """
    Bulk-create the tasks the user selected from the AI suggestions.
    """
    import json

    project = request.project

    try:
        body = json.loads(request.body)
        tasks = body.get("tasks", [])
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    if not tasks:
        return JsonResponse({"error": "No tasks selected."}, status=400)

    if len(tasks) > 7:
        return JsonResponse({"error": "Maximum 7 tasks at a time."}, status=400)

    created = []
    errors = []

    for t in tasks:
        try:
            dto = CreateTaskDTO(
                project_id=project.id,
                created_by_id=request.user.id,
                title=str(t.get("title", "")).strip(),
                description=str(t.get("description", "")).strip(),
                status="todo",
                priority=t.get("priority", "medium"),
            )
            task = services.create_task(dto)
            act.task_created(request, task)
            created.append(task.title)
        except (services.ServiceError, ValueError) as e:
            errors.append(str(e))

    return JsonResponse({
        "created": created,
        "errors":  errors,
        "redirect": f"/projects/{project.uuid}/",
    })

# Task edit

@login_required
@project_access_required
@require_POST
def task_edit(request, project_uuid, task_uuid):
    """Admins/owners can edit any task. Members and guests can only edit tasks assigned to them."""
    project = request.project
    task = get_object_or_404(Task, uuid=task_uuid, project=project)
    access = get_task_access(request, task)

    if access == TaskAccess.READONLY:
        messages.error(request, "You don't have permission to edit this task.")
        return redirect("projects:detail", project_uuid=project.uuid)

    if access == TaskAccess.ASSIGNEE:
        messages.error(request, "You can only update the status and attachments on tasks assigned to you.")
        return redirect("projects:detail", project_uuid=project.uuid)

    org_members = get_organization_members(request.active_org.id) if not request.is_project_guest else []
    guest_members = ProjectMembership.objects.filter(project=project)
    form = TaskForm(request.POST, instance=task, org_members=org_members, guest_members=guest_members)

    if form.is_valid():
        assigned_to = form.cleaned_data.get("assigned_to")
        due_date = form.cleaned_data.get("due_date")
        try:
            dto = UpdateTaskDTO(
                task_uuid=str(task_uuid),
                acting_user_id=request.user.id,
                project_id=project.id,
                title=form.cleaned_data["title"],
                description=form.cleaned_data.get("description", ""),
                status=form.cleaned_data["status"],
                priority=form.cleaned_data["priority"],
                due_date=due_date.isoformat() if due_date else None,
                assigned_to_id=assigned_to.id if assigned_to else None,
            )
            updated_task = services.update_task(dto)
            act.task_updated(request, updated_task)
            messages.success(request, "Task updated.")
            return redirect("projects:detail", project_uuid=project.uuid)
        except (services.ServiceError, ValueError) as e:
            messages.error(request, str(e))
            return redirect("projects:detail", project_uuid=project.uuid)
    else:
        return _render_detail_with_errors(
            request, project, form,
            open_modal=f"modal-edit-task-{task_uuid}",
            task_uuid=str(task_uuid),
        )


# Task delete

@login_required
@project_access_required
@project_admin_required
@require_POST
def task_delete(request, project_uuid, task_uuid):
    """Only admins and owners can delete tasks."""
    project = request.project
    task = get_object_or_404(Task, uuid=task_uuid, project=project)
    try:
        dto = DeleteTaskDTO(
            task_uuid=str(task_uuid),
            acting_user_id=request.user.id,
            project_id=project.id,
        )
        act.task_deleted(request, task)   # log before delete so task.project is still intact
        services.delete_task(dto)
        messages.success(request, "Task deleted.")
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("projects:detail", project_uuid=project.uuid)


# Task status toggle

@login_required
@project_access_required
@require_POST
def task_status(request, project_uuid, task_uuid):
    """
    Quick inline status update — called from the checkbox / status button.
    Expects POST field: status = todo | in_progress | done
    Admins/owners can update any task. Members and guests can only update tasks assigned to them.
    """
    project = request.project
    new_status = request.POST.get("status", "")
    task = get_object_or_404(Task, uuid=task_uuid, project=project)
    access = get_task_access(request, task)

    if access == TaskAccess.READONLY:
        messages.error(request, "You can only update tasks assigned to you.")
        return redirect("projects:detail", project_uuid=project.uuid)

    try:
        dto = UpdateTaskStatusDTO(
            task_uuid=str(task_uuid),
            acting_user_id=request.user.id,
            project_id=project.id,
            status=new_status,
        )
        services.update_task_status(dto)
        act.task_status_changed(request, task, new_status)
    except (services.ServiceError, ValueError) as e:
        messages.error(request, str(e))

    return redirect("projects:detail", project_uuid=project.uuid)


# Project activity history 

@login_required
@project_access_required
@require_GET
def project_activity(request, project_uuid):
    """Full paginated activity log for a project. Guests only see task events."""
    project = request.project
    joined_at = (
    request.membership.joined_at if request.membership
    else request.project_membership.joined_at if getattr(request, "project_membership", None)
    else None)
    log_qs = ActivityLog.objects.filter(project=project).select_related("actor")
    if joined_at:
        log_qs = log_qs.filter(created_at__gte=joined_at) # members only see activity since they joined
    if request.is_project_guest:
        log_qs = log_qs.filter(verb__in=_TASK_VERBS) # guests only see task-related events
    # Add after the existing log_qs filters in both views
    verb = request.GET.get("verb", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if verb:
        # Guests can only filter within allowed task verbs
        if not getattr(request, "is_project_guest", False) or verb in _TASK_VERBS:
            log_qs = log_qs.filter(verb=verb)

    if date_from:
        try:
            from datetime import date
            date.fromisoformat(date_from)   # validate before passing to ORM
            log_qs = log_qs.filter(created_at__date__gte=date_from)
        except ValueError:
            pass

    if date_to:
        try:
            from datetime import date
            date.fromisoformat(date_to)
            log_qs = log_qs.filter(created_at__date__lte=date_to)
        except ValueError:
            pass

    paginator = Paginator(log_qs, 20)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "projects/activity.html", {
        "project": project,
        "org": request.active_org,
        "membership": request.membership,
        "page_obj": page,
        "logs": page,
    })

@login_required
@require_GET
def my_tasks(request):
    """
    All tasks assigned to the current user across every project they can access.
    Guests only see tasks in their guest projects automatically — no extra check
    needed because the query scopes to assigned_to=request.user.
    """
    status = request.GET.get("status", "")
    sort = request.GET.get("sort", "due_date")

    ALLOWED_SORTS = {"due_date", "-due_date", "created_at", "-priority", "title"}
    if sort not in ALLOWED_SORTS:
        sort = "due_date"

    tasks = (
        Task.objects
        .filter(assigned_to=request.user)
        .select_related("project", "project__organization", "created_by")
        .prefetch_related("attachments")
    )
    if status:
        tasks = tasks.filter(status=status)

    tasks = tasks.order_by(sort)

    return render(request, "projects/my_tasks.html", {
        "tasks": tasks,
        "status_filter": status,
        "sort": sort,
        "status_choices": Task.Status.choices,
    })

# Org-wide activity history 

@login_required
@org_member_required
@require_GET
def org_activity(request):
    """Full paginated org-wide activity. Members only see activity since they joined."""
    joined_at = request.membership.joined_at if request.membership else None
    log_qs = ActivityLog.objects.filter(
        organization=request.active_org
    ).select_related("actor", "project")
    if joined_at:
        log_qs = log_qs.filter(created_at__gte=joined_at)
    # Add after the existing log_qs filters in both views
    verb = request.GET.get("verb", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if verb:
        # Guests can only filter within allowed task verbs
        if not getattr(request, "is_project_guest", False) or verb in _TASK_VERBS:
            log_qs = log_qs.filter(verb=verb)

    if date_from:
        try:
            from datetime import date
            date.fromisoformat(date_from)   # validate before passing to ORM
            log_qs = log_qs.filter(created_at__date__gte=date_from)
        except ValueError:
            pass

    if date_to:
        try:
            from datetime import date
            date.fromisoformat(date_to)
            log_qs = log_qs.filter(created_at__date__lte=date_to)
        except ValueError:
            pass

    paginator = Paginator(log_qs, 20)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "projects/org_activity.html", {
        "org": request.active_org,
        "membership": request.membership,
        "page_obj": page,
        "logs": page,
    })

# Task attachment upload

@login_required
@project_access_required
@require_POST
def task_attachment_upload(request, project_uuid, task_uuid):
    """Upload a file to Cloudinary and record public_id + secure_url.
    Admins/owners: any task. Members and guests: only tasks assigned to them."""
    import os
    import cloudinary.uploader

    project = request.project
    task = get_object_or_404(Task, uuid=task_uuid, project=project)
    access = get_task_access(request, task)
    
    if access == TaskAccess.READONLY:
        messages.error(request, "You can only attach files to tasks assigned to you.")
        return redirect("projects:detail", project_uuid=project.uuid)

    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "No file selected.")
        return redirect("projects:detail", project_uuid=project.uuid)

    ext = os.path.splitext(uploaded.name)[1].lower()
    if ext not in TaskAttachment.ALLOWED_EXTENSIONS:
        messages.error(request, f"File type '{ext}' is not allowed.")
        return redirect("projects:detail", project_uuid=project.uuid)

    if uploaded.size > TaskAttachment.MAX_UPLOAD_BYTES:
        messages.error(request, "File is too large. Maximum size is 10 MB.")
        return redirect("projects:detail", project_uuid=project.uuid)

    if task.attachments.count() >= 5:
        messages.error(request, "This task already has 5 attachments, the maximum allowed.")
        return redirect("projects:detail", project_uuid=project.uuid)
    
    try:
        resource_type = "image" if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else "raw"
        result = cloudinary.uploader.upload(
            uploaded,
            folder=f"planforge/task_attachments/{task.uuid}",
            resource_type=resource_type,
            use_filename=True,
            unique_filename=True,
            overwrite=False,
        )
    except Exception:
        logger.exception("Cloudinary upload failed for task %s", task.uuid)
        messages.error(request, "Upload failed. Please try again.")
        return redirect("projects:detail", project_uuid=project.uuid)

    attachment = TaskAttachment.objects.create(
        task=task,
        uploaded_by=request.user,
        cloudinary_public_id=result["public_id"], # public_id is opaque string used for deletion, 
        cloudinary_url=result["secure_url"], # secure_url is HTTPS URL for access
        original_filename=uploaded.name[:255],
        file_size=uploaded.size,
    )

    act.attachment_added(request, attachment)
    messages.success(request, f"'{uploaded.name}' attached.")
    return redirect("projects:detail", project_uuid=project.uuid)

# Task attachment view

@login_required
@project_access_required
@require_GET
def attachment_view(request, project_uuid, task_uuid, attachment_id):
    import requests as req
    from urllib.parse import quote
    from django.http import HttpResponse, Http404

    attachment = get_object_or_404(
        TaskAttachment.objects.select_related("task__project__organization"),
        id=attachment_id,
        task__uuid=task_uuid,
        task__project__uuid=project_uuid,
    )
    project = attachment.task.project

    from organizations.services import get_active_organization, get_user_membership
    active_org = get_active_organization(request)
    membership = get_user_membership(request.user.id, project.organization_id) if active_org else None
    is_guest= ProjectMembership.objects.filter(project=project, user=request.user).exists()

    if not membership and not is_guest:
        raise Http404

    try:
        r = req.get(attachment.cloudinary_url, timeout=30)
        r.raise_for_status()
    except Exception:
        logger.exception("attachment_view: fetch failed for attachment %s", attachment_id)
        raise Http404

    import os
    ext = os.path.splitext(attachment.original_filename)[1].lower()
    is_image = ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    if is_image:
        content_type = r.headers.get("Content-Type", "image/jpeg")
        disposition = f'inline; filename="{attachment.original_filename}"'
    else:
        content_type = "application/octet-stream"
        encoded = quote(attachment.original_filename, safe="")
        disposition = (
            f'attachment; filename="{attachment.original_filename}"; '
            f"filename*=UTF-8''{encoded}"
        )

    response = HttpResponse(r.content, content_type=content_type)
    response["Content-Disposition"] = disposition
    response["Content-Length"] = len(r.content)
    return response

# Task attachment delete

@login_required
@project_access_required
@require_POST
def task_attachment_delete(request, project_uuid, task_uuid, attachment_id):
    """Delete from Cloudinary then remove the DB row.
    Admins/owners: any task. Members and guests: only tasks assigned to them."""
    import os
    import cloudinary.uploader

    project = request.project
    task = get_object_or_404(Task, uuid=task_uuid, project=project)
    attachment = get_object_or_404(TaskAttachment, id=attachment_id, task=task)
    access = get_task_access(request, task)
    
    if access == TaskAccess.READONLY:
        messages.error(request, "You can only attach files to tasks assigned to you.")
        return redirect("projects:detail", project_uuid=project.uuid)

    filename = attachment.original_filename
    act.attachment_removed(request, task, filename)

    ext = os.path.splitext(filename)[1].lower()
    resource_type = "image" if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else "raw"
    try:
        cloudinary.uploader.destroy(attachment.cloudinary_public_id, resource_type=resource_type)
    except Exception:
        logger.exception("Cloudinary delete failed for public_id %s", attachment.cloudinary_public_id)

    attachment.delete()
    messages.success(request, f"'{filename}' removed.")
    return redirect("projects:detail", project_uuid=project.uuid)

# Project guest access 

@login_required
@require_POST
@project_access_required
@project_admin_required
def invite_guest(request, project_uuid):
    """Admin/owner sends a guest invite to an email address."""
    email = request.POST.get("email", "").strip()
    try:
        dto = InviteGuestDTO(
            project_id=request.project.id,
            invited_by_id=request.user.id,
            email=email,
        )
        invite, is_existing_user = services.invite_project_guest(dto)
    except services.ServiceError as e:
        messages.error(request, str(e))
        return redirect("projects:detail", project_uuid=project_uuid)
    except Exception:
        logger.exception("Guest invite failed for project %s", project_uuid)
        messages.error(request, "Something went wrong. Please try again.")
        return redirect("projects:detail", project_uuid=project_uuid)

    accept_url = request.build_absolute_uri(
        f"/projects/guest-invite/{invite.uuid}/accept/"
    )

    from core.utils import send_email_async
    inviter_name = request.user.get_full_name() or request.user.username

    if is_existing_user:
        subject = f"{inviter_name} invited you to a project on Planforge"
        body = (
            f"<p>Hi,</p>"
            f"<p><strong>{inviter_name}</strong> has invited you to collaborate on "
            f"<strong>{request.project.name}</strong> as a guest.</p>"
            f"<p><a href='{accept_url}'>Accept invitation</a></p>"
            f"<p>This link expires in 7 days.</p>"
        )
    else:
        subject = f"{inviter_name} invited you to Planforge"
        body = (
            f"<p>Hi,</p>"
            f"<p><strong>{inviter_name}</strong> has invited you to collaborate on "
            f"<strong>{request.project.name}</strong> on Planforge.</p>"
            f"<p><a href='{accept_url}'>Accept invitation & create your account</a></p>"
            f"<p>This link expires in 7 days.</p>"
        )

    send_email_async(email, subject, body, "guest_invite")
    messages.success(request, f"Invitation sent to {email}.")
    return redirect("projects:detail", project_uuid=project_uuid)


@require_http_methods(["GET", "POST"])
def accept_guest_invite(request, invite_uuid):
    """
    Landing page for a guest invite link.
    GET  — shows a confirmation page (or redirects to login if not authenticated).
    POST — accepts the invite and creates the ProjectMembership.
    """
    from django.utils import timezone

    try:
        invite = ProjectGuestInvite.objects.select_related(
            "project", "project__organization", "invited_by"
        ).get(uuid=invite_uuid)
    except ProjectGuestInvite.DoesNotExist:
        messages.error(request, "This invite link is invalid or has already been used.")
        return redirect("accounts:login")

    if invite.is_expired or invite.status != ProjectGuestInvite.STATUS_PENDING:
        messages.error(request, "This invite link has expired or has already been used.")
        return redirect("accounts:login")

    # Not logged in — send them to login/register with the invite URL preserved
    if not request.user.is_authenticated:
        from django.utils.http import urlencode
        next_url = request.build_absolute_uri()
        login_url = f"/accounts/login/?{urlencode({'next': request.path})}"
        messages.info(
            request,
            f"Please sign in or create an account with {invite.email} to accept this invitation."
        )
        return redirect(login_url)

    if request.method == "GET":
        return render(request, "projects/guest_invite_accept.html", {
            "invite": invite,
            "project": invite.project,
        })

    # POST — accept
    try:
        dto = AcceptGuestInviteDTO(
            invite_uuid=str(invite_uuid),
            accepting_user_id=request.user.id,
        )
        services.accept_guest_invite(dto)
        messages.success(
            request,
            f"You now have guest access to {invite.project.name}."
        )
        return redirect("projects:detail", project_uuid=invite.project.uuid)
    except services.ServiceError as e:
        messages.error(request, str(e))
        return render(request, "projects/guest_invite_accept.html", {
            "invite": invite,
            "project": invite.project,
        })
    
@login_required
@require_POST
def decline_guest_invite(request, invite_uuid):
    """
    Decline a pending project guest invite from the inbox.
    Marks the invite as expired so it can no longer be accepted,
    and marks the notification as read.
    """
    from django.utils import timezone

    try:
        invite = ProjectGuestInvite.objects.select_related("project").get(
            uuid=invite_uuid
        )
    except ProjectGuestInvite.DoesNotExist:
        messages.error(request, "This invite link is invalid.")
        return redirect("organizations:inbox")

    # Only the invited user can decline it
    if invite.invited_user and invite.invited_user_id != request.user.id:
        messages.error(request, "This invite is not for your account.")
        return redirect("organizations:inbox")

    if not invite.is_pending:
        messages.info(request, "This invite has already been responded to.")
        return redirect("organizations:inbox")

    invite.status = ProjectGuestInvite.STATUS_EXPIRED
    invite.save(update_fields=["status"])

    # Mark the associated notification as read so it clears from the inbox
    from organizations.models import Notification
    Notification.objects.filter(
        recipient=request.user,
        project_guest_invite=invite,
    ).update(is_read=True)

    messages.success(request, f"You declined the invitation to {invite.project.name}.")
    return redirect("organizations:inbox")


@login_required
@require_POST
@project_access_required
def leave_project(request, project_uuid):
    """Allows a project guest to remove themselves from a project.
    Any tasks in this project assigned to them are unassigned so their
    name no longer appears in task content after they leave.
    """
    from django.db import transaction
 
    project = get_object_or_404(Project, uuid=project_uuid)
    try:
        membership = ProjectMembership.objects.get(project=project, user=request.user)
        # Atomic: if the task unassignment fails after the membership is deleted
        # the user would be locked out with no way to fix their own tasks.
        with transaction.atomic():
            membership.delete()
            Task.objects.filter(project=project, assigned_to=request.user).update(assigned_to=None)
        messages.success(request, f"You have left {project.name}.")
    except ProjectMembership.DoesNotExist:
        messages.error(request, "You are not a guest on this project.")
    return redirect("projects:list")

@login_required
@require_POST
@project_access_required
@project_admin_required
def remove_guest(request, project_uuid, guest_uuid):
    """Admin/owner removes a guest from a project."""
    try:
        guest_membership = ProjectMembership.objects.select_related("user").get(
            uuid=guest_uuid,
            project=request.project,
        )
        username = guest_membership.user.get_full_name() or guest_membership.user.username
        services.remove_project_guest(
            project_id=request.project.id,
            guest_user_id=guest_membership.user_id,
            acting_user_id=request.user.id,
        )
        messages.success(request, f"{username} has been removed from this project.")
    except ProjectMembership.DoesNotExist:
        messages.error(request, "Guest not found.")
    except services.ServiceError as e:
        messages.error(request, str(e))

    return redirect("projects:detail", project_uuid=project_uuid)

#  Task comments 

@login_required
@project_access_required
@require_POST
def task_comment_add(request, project_uuid, task_uuid):
    """
    Any project member or guest can leave a comment on a task.
    After saving, redirects back to the project detail page with a URL fragment
    that keeps the task's modal open.
    """
    project = request.project
    task = get_object_or_404(Task, uuid=task_uuid, project=project)

    body = request.POST.get("body", "").strip()
    if not body:
        messages.error(request, "Comment cannot be empty.")
        return redirect(
            reverse("projects:detail", kwargs={"project_uuid": project.uuid})
            + f"#modal-edit-task-{task.uuid}"
        )
    if len(body) > 1000:
        messages.error(request, "Comment must be 1000 characters or fewer.")
        return redirect(
            reverse("projects:detail", kwargs={"project_uuid": project.uuid})
            + f"#modal-edit-task-{task.uuid}"
        )

    comment = TaskComment.objects.create(
        task=task,
        author=request.user,
        body=body,
    )
    act.comment_added(request, comment)

    return redirect(
        reverse("projects:detail", kwargs={"project_uuid": project.uuid})
        + f"#modal-edit-task-{task.uuid}"
    )


@login_required
@project_access_required
@require_POST
def task_comment_delete(request, project_uuid, task_uuid, comment_id):
    """
    Delete a comment. Allowed for the comment author or an admin/owner.
    """
    project = request.project
    task = get_object_or_404(Task, uuid=task_uuid, project=project)
    comment = get_object_or_404(TaskComment, id=comment_id, task=task)

    is_author = comment.author_id == request.user.id
    is_admin = request.membership and request.membership.is_admin_or_owner
    if not (is_author or is_admin):
        messages.error(request, "You can only delete your own comments.")
        return redirect(
            reverse("projects:detail", kwargs={"project_uuid": project.uuid})
            + f"#modal-edit-task-{task.uuid}"
        )

    comment.delete()
    messages.success(request, "Comment deleted.")
    return redirect(
        reverse("projects:detail", kwargs={"project_uuid": project.uuid})
        + f"#modal-edit-task-{task.uuid}"
    )
