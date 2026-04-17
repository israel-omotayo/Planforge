"""
Thin helpers for writing ActivityLog entries. Import and call these
from views/services after a successful write — never inside a form
validation path.

Usage:
    from projects.activity import log
    log.project_created(request, project)
    log.task_created(request, task)
    log.task_completed(request, task)
    log.member_invited(request, org, invited_username)
"""

import logging
from .models import ActivityLog

logger = logging.getLogger(__name__)


def _write(*, org, actor, verb, detail="", project=None):
    """Low-level write — silently swallows errors so a logging failure
    never breaks the main request."""
    try:
        ActivityLog.objects.create(
            organization=org,
            project=project,
            actor=actor,
            verb=verb,
            detail=detail,
        )
    except Exception:
        logger.exception("ActivityLog write failed (verb=%s)", verb)


# Project events 

def project_created(request, project):
    _write(
        org=project.organization,
        actor=request.user,
        verb=ActivityLog.Verb.PROJECT_CREATED,
        detail=project.name,
        project=project,
    )

def project_updated(request, project):
    _write(
        org=project.organization,
        actor=request.user,
        verb=ActivityLog.Verb.PROJECT_UPDATED,
        detail=project.name,
        project=project,
    )

def project_deleted(request, org, project_name):
    """Call before the project is deleted; pass the name as a string."""
    _write(
        org=org,
        actor=request.user,
        verb=ActivityLog.Verb.PROJECT_DELETED,
        detail=project_name,
    )


# Task events 

def _org_from_task(task):
    return task.project.organization


def task_created(request, task):
    _write(
        org=_org_from_task(task),
        actor=request.user,
        verb=ActivityLog.Verb.TASK_CREATED,
        detail=f'"{task.title}" in {task.project.name}',
        project=task.project,
    )

def task_updated(request, task):
    _write(
        org=_org_from_task(task),
        actor=request.user,
        verb=ActivityLog.Verb.TASK_UPDATED,
        detail=f'"{task.title}" in {task.project.name}',
        project=task.project,
    )

def task_deleted(request, task):
    _write(
        org=_org_from_task(task),
        actor=request.user,
        verb=ActivityLog.Verb.TASK_DELETED,
        detail=f'"{task.title}" in {task.project.name}',
        project=task.project,
    )

def task_status_changed(request, task, new_status):
    verb = (
        ActivityLog.Verb.TASK_COMPLETED
        if new_status == "done"
        else ActivityLog.Verb.TASK_REOPENED
    )
    _write(
        org=_org_from_task(task),
        actor=request.user,
        verb=verb,
        detail=f'"{task.title}" in {task.project.name}',
        project=task.project,
    )


# Member events (called from organizations/services.py)

def member_invited(actor, org, invited_username):
    _write(
        org=org,
        actor=actor,
        verb=ActivityLog.Verb.MEMBER_INVITED,
        detail=f"@{invited_username}",
    )

def member_joined(user, org):
    _write(
        org=org,
        actor=user,
        verb=ActivityLog.Verb.MEMBER_JOINED,
        detail=org.name,
    )

def member_removed(actor, org, removed_username):
    _write(
        org=org,
        actor=actor,
        verb=ActivityLog.Verb.MEMBER_REMOVED,
        detail=f"@{removed_username}",
    )

def member_left(user, org):
    _write(
        org=org,
        actor=user,
        verb=ActivityLog.Verb.MEMBER_LEFT,
        detail=org.name,
    )

def role_changed(actor, org, target_username, new_role):
    _write(
        org=org,
        actor=actor,
        verb=ActivityLog.Verb.ROLE_CHANGED,
        detail=f"@{target_username} → {new_role}",
    )

# Attachment events 

def attachment_added(request, attachment):
    task = attachment.task
    _write(
        org=task.project.organization,
        actor=request.user,
        verb=ActivityLog.Verb.ATTACHMENT_ADDED,
        detail=f'"{attachment.original_filename}" to "{task.title}"',
        project=task.project,
    )

def attachment_removed(request, task, filename):
    _write(
        org=task.project.organization,
        actor=request.user,
        verb=ActivityLog.Verb.ATTACHMENT_REMOVED,
        detail=f'"{filename}" from "{task.title}"',
        project=task.project,
    )

# Comment events

def comment_added(request, comment):
    task = comment.task
    _write(
        org=task.project.organization,
        actor=request.user,
        verb=ActivityLog.Verb.COMMENT_ADDED,
        detail=f'on "{task.title}" in {task.project.name}',
        project=task.project,
    )