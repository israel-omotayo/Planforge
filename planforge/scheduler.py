import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django_apscheduler.jobstores import DjangoJobStore
from django.core.management import call_command

logger = logging.getLogger(__name__)


def send_daily_digest():
    logger.info("Scheduler: running daily digest...")
    call_command("send_digest", frequency="daily")


def send_weekly_digest():
    logger.info("Scheduler: running weekly digest...")
    call_command("send_digest", frequency="weekly")


def run_cleanup_invites():
    logger.info("Scheduler: running cleanup_invites...")
    call_command("cleanup_invites")


def start():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_jobstore(DjangoJobStore(), "default")

    # 6am daily — clean up expired invites before emails go out
    scheduler.add_job(
        run_cleanup_invites,
        trigger=CronTrigger(hour=6, minute=0),
        id="cleanup_invites",
        name="Expire stale guest invites",
        jobstore="default",
        replace_existing=True,
        max_instances=1,
    )

    # 7am daily — urgent digest for users with overdue tasks
    scheduler.add_job(
        send_daily_digest,
        trigger=CronTrigger(hour=7, minute=0),
        id="daily_digest",
        name="Daily urgent digest",
        jobstore="default",
        replace_existing=True,
        max_instances=1,
    )

    # 8am every Monday — weekly summary
    scheduler.add_job(
        send_weekly_digest,
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_digest",
        name="Weekly summary digest",
        jobstore="default",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("Scheduler started — cleanup 06:00, daily 07:00, weekly Mon 08:00 UTC.")