import json
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import UserProfile

User = get_user_model()


@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
    SECURE_SSL_REDIRECT=False,
)
class RegisterViewTests(TestCase):
    def build_token(self, seconds_ago=10):
        return signing.dumps(
            {"issued_at": int(time.time()) - seconds_ago},
            salt="accounts.signup",
        )

    def test_register_get_json_includes_anti_bot_token(self):
        response = self.client.get(
            reverse("accounts:register"),
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertIn("anti_bot_token", payload["data"])
        self.assertEqual(payload["data"]["min_submit_seconds"], 3)

    def test_register_rejects_honeypot_submission(self):
        payload = {
            "username": "cleanuser",
            "first_name": "Clean",
            "last_name": "User",
            "email": "clean@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
            "honeypot": "bot filled this",
            "anti_bot_token": self.build_token(),
        }

        response = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("__all__", response.json()["data"]["errors"])
        self.assertFalse(User.objects.filter(username="cleanuser").exists())

    def test_register_rejects_fast_submission(self):
        payload = {
            "username": "fastuser",
            "first_name": "Fast",
            "last_name": "User",
            "email": "fast@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
            "honeypot": "",
            "anti_bot_token": self.build_token(seconds_ago=0),
        }

        response = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("__all__", response.json()["data"]["errors"])
        self.assertFalse(User.objects.filter(username="fastuser").exists())

    @patch("accounts.views.send_email_async")
    def test_register_reuses_inactive_email_instead_of_deleting_user(self, mock_send_email_async):
        existing_user = User.objects.create_user(
            username="oldname",
            email="owner@example.com",
            password="OldPass123!",
            first_name="Old",
            last_name="Name",
            is_active=False,
        )
        old_profile_id = UserProfile.objects.get(user=existing_user).id

        payload = {
            "username": "newname",
            "first_name": "Real",
            "last_name": "Owner",
            "email": "owner@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
            "honeypot": "",
            "anti_bot_token": self.build_token(),
        }

        response = self.client.post(
            reverse("accounts:register"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201)
        existing_user.refresh_from_db()
        self.assertEqual(existing_user.username, "newname")
        self.assertEqual(existing_user.first_name, "Real")
        self.assertEqual(existing_user.last_name, "Owner")
        self.assertFalse(existing_user.is_active)
        self.assertEqual(User.objects.filter(email="owner@example.com").count(), 1)
        self.assertEqual(UserProfile.objects.get(user=existing_user).id, old_profile_id)
        mock_send_email_async.assert_called_once()
