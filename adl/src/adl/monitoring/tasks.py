import logging
from datetime import timedelta

from celery.schedules import crontab
from celery_singleton import Singleton
from django.utils import timezone

from adl.config.celery import app
from .models import NetworkConnectionHealthTransition, StationLinkActivityLog

logger = logging.getLogger(__name__)


@app.task(base=Singleton, bind=True)
def run_station_link_activity_log_cleanup(self):
    logger.info("[StationLinkActivityLog Cleanup] Starting cleanup...")
    cutoff = timezone.now() - timedelta(days=7)
    deleted_count, _ = StationLinkActivityLog.objects.filter(time__lt=cutoff).delete()
    logger.info(f"[StationLinkActivityLog Cleanup] Deleted {deleted_count} old logs")

    transition_cutoff = timezone.now() - timedelta(days=NetworkConnectionHealthTransition.RETENTION_DAYS)
    deleted_transitions, _ = NetworkConnectionHealthTransition.objects.filter(
        at__lt=transition_cutoff
    ).delete()
    logger.info(f"[HealthTransition Cleanup] Deleted {deleted_transitions} old transitions")


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(hour=0, minute=0),
        run_station_link_activity_log_cleanup.s(),
        name="run-station-link-activity-log-cleanup-daily-at-midnight"
    )
