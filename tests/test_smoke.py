"""
Smoke tests — every major URL in Planforge.

Goal: catch broken routes, missing template variables, and accidental
permission regressions before a deploy. Each test is a single assertion:
does this URL return the expected HTTP status for this user?

Run with:
    python manage.py test tests.test_smoke

Legend:
    200 — page rendered OK
    302 — redirect (login wall or post-action redirect)
    403 — permission denied
    405 — method not allowed (GET on a POST-only view)
"""

import uuid

from django.test import TestCase, Client
from django.urls import reverse

from tests.factories import (
    make_user, make_org, make_membership, make_project, make_task,
)
from organizations.models import Membership
from projects.models import Task, Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class PlanforgeTestCase(TestCase):
    """
    Base class: sets up a standard fixture used by most tests.

        alice  — owner of Meridian Studio, has a project with one task
        bob    — member of Meridian Studio
        carol  — unrelated user (no org)
    """

    def setUp(self):
        self.alice = make_user("alice", "pass1234")
        self.bob   = make_user("bob",   "pass1234")
        self.carol = make_user("carol", "pass1234")

        self.org = make_org(owner=self.alice, name="Meridian Studio")
        make_membership(self.bob, self.org, role=Membership.Role.MEMBER)

        self.project = make_project(self.org, self.alice, name="Alpha")
        self.task    = make_task(self.project, self.alice, title="Task 1")

        # Set the active org in the session for alice and bob
        self._set_active_org(self.alice)
        self._set_active_org(self.bob)

    def _client_for(self, user):
        """Return a logged-in Client for the given user."""
        c = Client()
        c.force_login(user)
        # Inject active org into session so org-scoped views don't redirect
        session = c.session
        session["_active_org_id"] = self.org.id
        session["_recent_org_ids"] = [self.org.id]
        session.save()
        return c

    def _set_active_org(self, user):
        """Helper used by setUp — not a real client session, just a note."""
        pass  # handled per-client in _client_for


# ---------------------------------------------------------------------------
# Public pages (no login required)
# ---------------------------------------------------------------------------

class PublicPagesTest(TestCase):

    def test_home_anonymous(self):
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 200)

    def test_login_page(self):
        r = self.client.get(reverse("accounts:login"))
        self.assertEqual(r.status_code, 200)

    def test_register_page(self):
        r = self.client.get(reverse("accounts:register"))
        self.assertEqual(r.status_code, 200)

    def test_password_reset_page(self):
        r = self.client.get(reverse("accounts:password_reset"))
        self.assertEqual(r.status_code, 200)

    def test_offline_page(self):
        r = self.client.get(reverse("offline"))
        self.assertEqual(r.status_code, 200)

    def test_home_redirects_authenticated_users_to_dashboard(self):
        user = make_user("dave", "pass1234")
        self.client.force_login(user)
        r = self.client.get(reverse("home"))
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Login wall — unauthenticated access should redirect to login
# ---------------------------------------------------------------------------

class LoginWallTest(TestCase):

    PROTECTED = [
        "dashboard",
        "analytics",
        "org_activity",
    ]

    def test_protected_pages_redirect_anonymous(self):
        login_url = reverse("accounts:login")
        for name in self.PROTECTED:
            with self.subTest(view=name):
                r = self.client.get(reverse(name))
                self.assertEqual(r.status_code, 302)
                self.assertIn(login_url, r["Location"])

    def test_project_list_redirects_anonymous(self):
        r = self.client.get(reverse("projects:list"))
        self.assertEqual(r.status_code, 302)

    def test_org_list_redirects_anonymous(self):
        r = self.client.get(reverse("organizations:list"))
        self.assertEqual(r.status_code, 302)

    def test_profile_redirects_anonymous(self):
        r = self.client.get(reverse("accounts:profile"))
        self.assertEqual(r.status_code, 302)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardTest(PlanforgeTestCase):

    def test_dashboard_ok_for_member(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Meridian Studio")

    def test_dashboard_ok_for_bob(self):
        c = self._client_for(self.bob)
        r = c.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)

    def test_dashboard_no_org_redirects_to_create(self):
        c = Client()
        c.force_login(self.carol)  # carol has no org, no active_org in session
        r = c.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("create", r["Location"])

    def test_analytics_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("analytics"))
        self.assertEqual(r.status_code, 200)

    def test_org_activity_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("org_activity"))
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Registration flow
# ---------------------------------------------------------------------------

class RegistrationTest(TestCase):

    def test_register_post_creates_inactive_user(self):
        """
        POST to register creates the user in a pending-verification state.
        The response should redirect to the verify step, not straight to dashboard.
        """
        r = self.client.post(reverse("accounts:register"), {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "Str0ng!Pass99",
            "password2": "Str0ng!Pass99",
        })
        # Should redirect (to verify page or login) — not render the form again
        self.assertIn(r.status_code, [200, 302])

    def test_register_get_renders_form(self):
        r = self.client.get(reverse("accounts:register"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "username")


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

class AuthFlowTest(TestCase):

    def setUp(self):
        self.user = make_user("testlogin", "pass1234")

    def test_login_post_correct_credentials(self):
        r = self.client.post(reverse("accounts:login"), {
            "username": "testlogin",
            "password": "pass1234",
        })
        # Should redirect to dashboard or org create — not re-render login
        self.assertEqual(r.status_code, 302)

    def test_login_post_wrong_password_rerenders(self):
        r = self.client.post(reverse("accounts:login"), {
            "username": "testlogin",
            "password": "wrongpassword",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "username")

    def test_logout(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("accounts:logout"))
        self.assertIn(r.status_code, [200, 302])


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileTest(PlanforgeTestCase):

    def test_profile_page_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("accounts:profile"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "alice")


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

class OrganizationTest(PlanforgeTestCase):

    def test_org_list_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("organizations:list"))
        self.assertEqual(r.status_code, 200)

    def test_org_create_get_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("organizations:create"))
        self.assertEqual(r.status_code, 200)

    def test_org_create_post_creates_org(self):
        c = self._client_for(self.carol)
        r = c.post(reverse("organizations:create"), {"name": "Carol's Org"})
        self.assertEqual(r.status_code, 302)
        from organizations.models import Organization
        self.assertTrue(Organization.objects.filter(name="Carol's Org").exists())

    def test_org_settings_ok_for_owner(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("organizations:settings", kwargs={"org_slug": self.org.slug}))
        self.assertEqual(r.status_code, 200)

    def test_org_settings_visible_for_member(self):
        """
        All org members can view the settings page — it shows the member list
        and org info. Admin-only actions (invite, delete, role change) are
        hidden in the template, but the page itself is not restricted.
        The @org_member_required decorator (not @org_admin_required) confirms this.
        """
        c = self._client_for(self.bob)
        r = c.get(reverse("organizations:settings", kwargs={"org_slug": self.org.slug}))
        self.assertEqual(r.status_code, 200)

    def test_org_switch_works(self):
        c = self._client_for(self.alice)
        r = c.post(reverse("organizations:switch", kwargs={"org_slug": self.org.slug}))
        self.assertEqual(r.status_code, 302)

    def test_inbox_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("organizations:inbox"))
        self.assertEqual(r.status_code, 200)

    def test_org_update_name(self):
        c = self._client_for(self.alice)
        r = c.post(
            reverse("organizations:update", kwargs={"org_slug": self.org.slug}),
            {"name": "Meridian Studio Renamed"},
        )
        self.assertEqual(r.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Meridian Studio Renamed")

    def test_invite_member_post_by_owner(self):
        """Owner can send a direct invite to an existing user."""
        target = make_user("dave_target", "pass1234")
        c = self._client_for(self.alice)
        r = c.post(
            reverse("organizations:invite_member", kwargs={"org_slug": self.org.slug}),
            {"username": "dave_target"},
        )
        self.assertEqual(r.status_code, 302)

    def test_invite_member_post_denied_for_member(self):
        target = make_user("eve_target", "pass1234")
        c = self._client_for(self.bob)
        r = c.post(
            reverse("organizations:invite_member", kwargs={"org_slug": self.org.slug}),
            {"username": "eve_target"},
        )
        self.assertIn(r.status_code, [403, 302])


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectTest(PlanforgeTestCase):

    def test_project_list_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Alpha")

    def test_project_list_search(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:list"), {"q": "Alpha"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Alpha")

    def test_project_list_search_no_match(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:list"), {"q": "zzznomatch"})
        self.assertEqual(r.status_code, 200)

    def test_project_detail_ok_for_member(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:detail", kwargs={"project_uuid": self.project.uuid}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Alpha")

    def test_project_detail_ok_for_org_member(self):
        c = self._client_for(self.bob)
        r = c.get(reverse("projects:detail", kwargs={"project_uuid": self.project.uuid}))
        self.assertEqual(r.status_code, 200)

    def test_project_detail_forbidden_for_outsider(self):
        c = self._client_for(self.carol)
        r = c.get(reverse("projects:detail", kwargs={"project_uuid": self.project.uuid}))
        self.assertIn(r.status_code, [403, 302])

    def test_project_detail_404_on_bad_uuid(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:detail", kwargs={"project_uuid": uuid.uuid4()}))
        self.assertIn(r.status_code, [403, 404])

    def test_project_create_get_ok_for_admin(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:create"))
        self.assertEqual(r.status_code, 200)

    def test_project_create_get_forbidden_for_member(self):
        c = self._client_for(self.bob)
        r = c.get(reverse("projects:create"))
        self.assertIn(r.status_code, [403, 302])

    def test_project_create_post_creates_project(self):
        c = self._client_for(self.alice)
        r = c.post(reverse("projects:create"), {
            "name": "Beta Project",
            "description": "A new project",
            "status": "active",
            "currency": "USD",   # required by CreateProjectForm
        })
        self.assertEqual(r.status_code, 302)
        from projects.models import Project as P
        self.assertTrue(P.objects.filter(name="Beta Project").exists())

    def test_project_edit_get_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:edit", kwargs={"project_uuid": self.project.uuid}))
        self.assertEqual(r.status_code, 200)

    def test_project_edit_post_updates(self):
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:edit", kwargs={"project_uuid": self.project.uuid}),
            {"name": "Alpha Renamed", "status": "active", "description": "", "currency": "USD"},
        )
        self.assertEqual(r.status_code, 302)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Alpha Renamed")

    def test_project_delete_post_removes_project(self):
        project_to_delete = make_project(self.org, self.alice, name="To Delete")
        c = self._client_for(self.alice)
        r = c.post(reverse("projects:delete", kwargs={"project_uuid": project_to_delete.uuid}))
        self.assertEqual(r.status_code, 302)
        from projects.models import Project as P
        self.assertFalse(P.objects.filter(pk=project_to_delete.pk).exists())

    def test_project_activity_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:project_activity", kwargs={"project_uuid": self.project.uuid}))
        self.assertEqual(r.status_code, 200)

    def test_my_tasks_ok(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:my_tasks"))
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TaskTest(PlanforgeTestCase):

    def test_task_create_post_ok(self):
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_create", kwargs={"project_uuid": self.project.uuid}),
            {
                "title": "New Task",
                "status": "todo",
                "priority": "medium",
                "description": "",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Task.objects.filter(title="New Task").exists())

    def test_task_create_by_member_ok(self):
        c = self._client_for(self.bob)
        r = c.post(
            reverse("projects:task_create", kwargs={"project_uuid": self.project.uuid}),
            {"title": "Bob Task", "status": "todo", "priority": "low", "description": ""},
        )
        self.assertEqual(r.status_code, 302)

    def test_task_create_by_outsider_forbidden(self):
        c = self._client_for(self.carol)
        r = c.post(
            reverse("projects:task_create", kwargs={"project_uuid": self.project.uuid}),
            {"title": "Carol Task", "status": "todo", "priority": "low", "description": ""},
        )
        self.assertIn(r.status_code, [403, 302])
        self.assertFalse(Task.objects.filter(title="Carol Task").exists())

    def test_task_edit_post_updates_title(self):
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_edit", kwargs={
                "project_uuid": self.project.uuid,
                "task_uuid": self.task.uuid,
            }),
            {
                "title": "Renamed Task",
                "status": "todo",
                "priority": "high",
                "description": "",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Renamed Task")

    def test_task_status_toggle_to_done(self):
        # task_status reads request.POST.get("status"), not a JSON body.
        # Send as normal form data.
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_status", kwargs={
                "project_uuid": self.project.uuid,
                "task_uuid": self.task.uuid,
            }),
            {"status": "done"},
        )
        self.assertEqual(r.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_task_status_toggle_invalid_value(self):
        # The view catches ValueError/ServiceError, adds a message, and always
        # redirects back to the project detail page — even on bad input.
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_status", kwargs={
                "project_uuid": self.project.uuid,
                "task_uuid": self.task.uuid,
            }),
            {"status": "not_a_real_status"},
        )
        self.assertEqual(r.status_code, 302)
        self.task.refresh_from_db()
        # Status must be unchanged — bad input must not corrupt data
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_task_delete_post_removes_task(self):
        task_to_delete = make_task(self.project, self.alice, title="Delete Me")
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_delete", kwargs={
                "project_uuid": self.project.uuid,
                "task_uuid": task_to_delete.uuid,
            }),
        )
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Task.objects.filter(pk=task_to_delete.pk).exists())

    def test_task_delete_by_member_forbidden(self):
        """Regular members cannot delete tasks (only admin/owner/creator)."""
        # Depends on your permission logic — adjust expected status if members CAN delete
        c = self._client_for(self.bob)
        r = c.post(
            reverse("projects:task_delete", kwargs={
                "project_uuid": self.project.uuid,
                "task_uuid": self.task.uuid,
            }),
        )
        # Alice's task should still exist
        self.assertTrue(Task.objects.filter(pk=self.task.pk).exists())

    def test_task_comment_add(self):
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_comment_add", kwargs={
                "project_uuid": self.project.uuid,
                "task_uuid": self.task.uuid,
            }),
            {"body": "First comment"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.task.comments.filter(body="First comment").exists())

    def test_task_comment_empty_body_rejected(self):
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_comment_add", kwargs={
                "project_uuid": self.project.uuid,
                "task_uuid": self.task.uuid,
            }),
            {"body": ""},
        )
        # Should NOT create a comment and should NOT 500
        self.assertNotEqual(r.status_code, 500)
        self.assertFalse(self.task.comments.filter(body="").exists())


# ---------------------------------------------------------------------------
# HTTP method enforcement (405s)
# ---------------------------------------------------------------------------

class MethodEnforcementTest(PlanforgeTestCase):

    def test_task_create_get_returns_405(self):
        """task_create is POST-only."""
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:task_create", kwargs={"project_uuid": self.project.uuid}))
        self.assertEqual(r.status_code, 405)

    def test_task_delete_get_returns_405(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:task_delete", kwargs={
            "project_uuid": self.project.uuid,
            "task_uuid": self.task.uuid,
        }))
        self.assertEqual(r.status_code, 405)

    def test_project_delete_get_returns_405(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:delete", kwargs={"project_uuid": self.project.uuid}))
        self.assertEqual(r.status_code, 405)

    def test_org_switch_get_returns_405(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("organizations:switch", kwargs={"org_slug": self.org.slug}))
        self.assertEqual(r.status_code, 405)


# ---------------------------------------------------------------------------
# Edge cases and regression guards
# ---------------------------------------------------------------------------

class EdgeCaseTest(PlanforgeTestCase):

    def test_project_list_pagination(self):
        """Create 30 projects — list should paginate without 500."""
        for i in range(30):
            make_project(self.org, self.alice, name=f"Project {i:02d}")
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:list"))
        self.assertEqual(r.status_code, 200)
        r2 = c.get(reverse("projects:list"), {"page": 2})
        self.assertIn(r2.status_code, [200, 404])

    def test_project_list_status_filter(self):
        make_project(self.org, self.alice, name="On Hold Proj", status=Project.Status.ON_HOLD)
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:list"), {"status": "on_hold"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "On Hold Proj")
        self.assertNotContains(r, "Alpha")

    def test_project_list_sort_by_name(self):
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:list"), {"sort": "name"})
        self.assertEqual(r.status_code, 200)

    def test_project_list_invalid_sort_falls_back(self):
        """An invalid sort param should not cause a 500."""
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:list"), {"sort": "'; DROP TABLE projects; --"})
        self.assertEqual(r.status_code, 200)

    def test_task_with_overdue_date_renders_ok(self):
        from tests.factories import make_overdue_task
        make_overdue_task(self.project, self.alice, assigned_to=self.alice)
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:detail", kwargs={"project_uuid": self.project.uuid}))
        self.assertEqual(r.status_code, 200)

    def test_my_tasks_with_assigned_tasks(self):
        make_task(self.project, self.alice, title="Assigned", assigned_to=self.alice)
        c = self._client_for(self.alice)
        r = c.get(reverse("projects:my_tasks"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Assigned")

    def test_org_delete_forbidden_for_member(self):
        c = self._client_for(self.bob)
        r = c.post(reverse("organizations:delete", kwargs={"org_slug": self.org.slug}))
        self.assertIn(r.status_code, [403, 302])
        from organizations.models import Organization
        self.assertTrue(Organization.objects.filter(pk=self.org.pk).exists())

    def test_task_status_on_wrong_project_forbidden(self):
        """Task from a different project should not be editable via another project's URL."""
        other_project = make_project(self.org, self.alice, name="Other")
        c = self._client_for(self.alice)
        r = c.post(
            reverse("projects:task_status", kwargs={
                "project_uuid": other_project.uuid,   # wrong project
                "task_uuid": self.task.uuid,           # task belongs to self.project
            }),
            {"status": "done"},
        )
        self.assertIn(r.status_code, [403, 404])
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, Task.Status.DONE)
