import logging
from datetime import timedelta

from celery import shared_task
from celery.schedules import crontab
from celery_singleton import Singleton
from django.utils import timezone

from adl.config.celery import app
from .models import (
    AvailabilityCheck,
    NetworkConnectionHealthTransition,
    SourceProbeResult,
    StationLinkActivityLog,
)

logger = logging.getLogger(__name__)


@app.task(base=Singleton, bind=True)
def run_station_link_activity_log_cleanup(self):
    logger.info("[StationLinkActivityLog Cleanup] Starting cleanup...")
    cutoff = timezone.now() - timedelta(days=7)
    deleted_count, _ = StationLinkActivityLog.objects.filter(time__lt=cutoff).delete()
    logger.info(f"[StationLinkActivityLog Cleanup] Deleted {deleted_count} old logs")

    # One retention policy: availability checks go with the activity log
    deleted_checks, _ = AvailabilityCheck.objects.filter(created_at__lt=cutoff).delete()
    logger.info(f"[AvailabilityCheck Cleanup] Deleted {deleted_checks} old availability checks")

    transition_cutoff = timezone.now() - timedelta(days=NetworkConnectionHealthTransition.RETENTION_DAYS)
    deleted_transitions, _ = NetworkConnectionHealthTransition.objects.filter(
        at__lt=transition_cutoff
    ).delete()
    logger.info(f"[HealthTransition Cleanup] Deleted {deleted_transitions} old transitions")

    probe_cutoff = timezone.now() - timedelta(days=SourceProbeResult.RETENTION_DAYS)
    deleted_probes, _ = SourceProbeResult.objects.filter(at__lt=probe_cutoff).delete()
    logger.info(f"[SourceProbeResult Cleanup] Deleted {deleted_probes} old probe results")


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(hour=0, minute=0),
        run_station_link_activity_log_cleanup.s(),
        name="run-station-link-activity-log-cleanup-daily-at-midnight"
    )


@shared_task(bind=True, name="adl.monitoring.tasks.run_availability_check")
def run_availability_check(self, station_link_id, start_iso, end_iso, parameter_id=None):
    """The fetch tier of an availability check (see ``gap_service``): fetches and
    parses the window without saving anything, and returns the stored result's
    id. Releases the station link's in-flight claim however it ends."""
    from . import gap_service
    return gap_service.run_fetch_task(station_link_id, start_iso, end_iso, parameter_id)


@shared_task(bind=True, name="adl.monitoring.tasks.run_gap_recovery")
def run_gap_recovery(self, station_link_id, check_id):
    """Gap recovery (see ``gap_service``): ingests a stored check's window through
    the normal pipeline and returns the fetched/saved report, or ``busy`` when a
    scheduled pull holds the station's ingestion lock. Releases the station
    link's in-flight claim however it ends."""
    from . import gap_service
    return gap_service.run_recovery_task(station_link_id, check_id)


@shared_task(bind=True, name="adl.monitoring.tasks.run_late_dispatch")
def run_late_dispatch(self, station_link_id, check_id, channel_id):
    """Late dispatch (see ``gap_service``): sends a recovered check's window to a
    dispatch channel without touching its dispatch cursor, and returns the
    ``sent`` count, or ``busy`` when a normal dispatch holds the station's lock."""
    from . import gap_service
    return gap_service.run_late_dispatch_task(station_link_id, check_id, channel_id)
