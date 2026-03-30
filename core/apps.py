import os
import sys
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        if self._should_start_scheduler():
            from planforge.scheduler import start
            start()

    def _should_start_scheduler(self):
        # Never run during management commands
        management_commands = {
            "migrate", "makemigrations", "collectstatic",
            "shell", "test", "cleanup_activity", "send_digest", "cleanup_invites",
            "createsuperuser", "check",
        }
        if len(sys.argv) > 1 and sys.argv[1] in management_commands:
            return False

        # Never run during tests
        if "test" in sys.argv:
            return False

        # Never run in local dev unless explicitly opted in
        from django.conf import settings
        if settings.DEBUG and not os.environ.get("ENABLE_SCHEDULER"):
            return False

        return True