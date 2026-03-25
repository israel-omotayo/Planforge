import sys
from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    name = "projects"

    def ready(self):
        """
        Schedule a once-per-day ActivityLog cleanup in a background thread.
        Running it in a thread avoids the Django warning about DB access
        during app initialisation — the query fires after the server is up.
        Skipped entirely during migrate / makemigrations.
        """
        if any(cmd in sys.argv for cmd in (
            "migrate", "makemigrations", "sqlmigrate",
            "showmigrations", "squashmigrations",
        )):
            return

        import threading

        def _cleanup():
            import time
            import logging
            from django.core.cache import cache
            from django.utils import timezone
            from datetime import timedelta

            # Give the server a few seconds to finish starting
            time.sleep(10)

            CACHE_KEY = "activitylog_last_cleanup"
            try:
                if cache.get(CACHE_KEY):
                    return  # already ran within the last 24 h

                from projects.models import ActivityLog
                cutoff  = timezone.now() - timedelta(days=30)
                deleted, _ = ActivityLog.objects.filter(created_at__lt=cutoff).delete()

                if deleted:
                    logging.getLogger(__name__).info(
                        "ActivityLog auto-cleanup: deleted %d entries older than 30 days.", deleted
                    )

                cache.set(CACHE_KEY, True, timeout=86_400)  # 24 h

            except Exception:
                logging.getLogger(__name__).exception("ActivityLog auto-cleanup failed silently.")

        t = threading.Thread(target=_cleanup, daemon=True, name="activitylog-cleanup")
        t.start()