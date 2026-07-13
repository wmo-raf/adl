import json
import logging
import time
from datetime import timedelta

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.schedules import crontab
from celery.signals import worker_ready
from celery_singleton import Singleton, clear_locks
from django.core.cache import cache
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from more_itertools import chunked

from django.utils import timezone as dj_timezone

from adl.config.celery import app
from adl.monitoring.models import StationLinkActivityLog
from .dispatchers import get_station_dispatch_records
from .logging import TaskLogger
from .utils import get_object_or_none

logger = logging.getLogger(__name__)

# Extra time allowed beyond the soft limit before the worker hard-kills a
# station dispatch task
DISPATCH_TIME_LIMIT_GRACE_SECONDS = 30

# The per-station dispatch lock always outlives the hard time limit by this
# margin, so a killed worker can never leave a station permanently locked
DISPATCH_LOCK_TTL_MARGIN_SECONDS = 60


def dispatch_station_lock_key(channel_id, station_link_id):
    return f"lock:dispatch:{channel_id}:{station_link_id}"


@app.task(base=Singleton, bind=True)
def run_backup(self):
    # TODO: defer until we find a fix with timescale db backup
    pass
    # # Run the `dbbackup` command
    # logger.info("[BACKUP] Running backup")
    # call_command('dbbackup', '--clean', '--noinput')
    #
    # # Run the `mediabackup` command
    # logger.info("[BACKUP] Running mediabackup")
    # call_command('mediabackup', '--clean', '--noinput')


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(hour=0, minute=0),
        run_backup.s(),
        name="run-backup-daily-at-midnight",
    )
    sender.add_periodic_task(
        300.0,
        sweep_stale_dispatch_logs.s(),
        name="sweep-stale-dispatch-logs-every-5-minutes",
    )


@shared_task(bind=True, name='adl.core.tasks.run_network_plugin')
def run_network_plugin(self, network_id):
    """
    Coordinator task that spawns batch processing subtasks.
    This task primarily logs orchestration events.
    """
    from .models import NetworkConnection
    
    task_id = self.request.id
    log = TaskLogger(task_id=task_id, plugin_label="NetworkPlugin")
    
    network_connection = get_object_or_none(NetworkConnection, id=network_id)
    
    if not network_connection:
        log.error("Network Connection with id %d does not exist. Skipping...", network_id)
        return
    
    log.info("Starting network plugin for connection: %s (ID: %d)",
             network_connection.name, network_id)
    
    batch_size = network_connection.batch_size or 10
    
    # only process enabled station links
    station_link_ids = list(
        network_connection.station_links.filter(enabled=True).values_list("id", flat=True)
    )
    
    if not station_link_ids:
        log.warning("No enabled station links found for connection %s", network_connection.name)
        return
    
    log.info("Found %d enabled station links. Batch size: %d",
             len(station_link_ids), batch_size)
    
    batch_count = 0
    spawned_tasks = []
    
    for batch in chunked(station_link_ids, batch_size):
        batch_count += 1
        batch_list = list(batch)
        
        log.info("Spawning batch %d with %d station links: %s",
                 batch_count, len(batch_list), batch_list)
        
        task = process_station_link_batch.apply_async(args=[network_id, batch_list], queue='adl')
        
        spawned_tasks.append(task.id)
    
    log.success("Successfully spawned %d batch tasks for connection %s",
                batch_count, network_connection.name)
    
    return {
        'status': 'success',
        'network_id': network_id,
        'connection_name': network_connection.name,
        'total_station_links': len(station_link_ids),
        'batch_count': batch_count,
        'spawned_tasks': spawned_tasks
    }


@shared_task(bind=True, name='adl.core.tasks.process_station_link_batch')
def process_station_link_batch(self, network_id, station_link_ids):
    from adl.core.registries import plugin_registry
    from .models import NetworkConnection
    from .models import StationLink
    
    # Create task logger for this batch task
    task_id = self.request.id
    log = TaskLogger(
        task_id=task_id,
        plugin_label="BatchProcessor",
    )
    
    log.info("Starting batch processing for network %d with %d station links: %s",
             network_id, len(station_link_ids), station_link_ids)
    
    network_connection = get_object_or_none(NetworkConnection, id=network_id)
    
    if not network_connection:
        log.error("Network Connection with id %d does not exist. Skipping...", network_id)
        return
    
    network_plugin_type = network_connection.plugin
    plugin = plugin_registry.get(network_plugin_type)
    
    # Set the task context on the plugin so it uses the same task_id for logging
    plugin.set_task_context(task_id)
    
    log.info("Using plugin: %s for network connection: %s",
             plugin.label, network_connection.name)
    
    total_processed = 0
    total_records = 0
    skipped = 0
    errors = 0
    
    for station_link_id in station_link_ids:
        station_link = get_object_or_none(StationLink, id=station_link_id)
        
        if not station_link:
            log.error("Station link with id %d does not exist. Skipping...", station_link_id)
            continue
        
        lock_key = f"lock:station:{station_link_id}"
        
        lock_acquired = cache.add(lock_key, "locked", timeout=None)
        
        if not lock_acquired:
            log.warning("Station link %s (ID: %d) is still processing. Skipping...",
                        station_link, station_link_id)
            skipped += 1
            continue
        
        start = time.monotonic()
        log.info("Processing station link: %s (ID: %d)", station_link, station_link_id)
        
        try:
            # This will now log to WebSocket via the plugin's logger
            saved_records_count = plugin.process_station(station_link)
            
            if saved_records_count > 0:
                log.success("Processed %d records for station link %s",
                            saved_records_count, station_link)
                total_records += saved_records_count
            else:
                log.info("No new records for station link %s", station_link)
            total_processed += 1
        except Exception as e:
            log.error("Error processing station link %s: %s", station_link, str(e), exc_info=True)
            errors += 1
        
        finally:
            # Release the lock after processing
            cache.delete(lock_key)
            duration_ms = (time.monotonic() - start) * 1000
            log.info("Station link %s completed in %.2fms", station_link, duration_ms)
    
    # Summary
    log.success(
        "Batch complete. Processed: %d, Records saved: %d, Skipped: %d, Errors: %d",
        total_processed, total_records, skipped, errors
    )
    
    return {
        'status': 'success',
        'network_id': network_id,
        'station_link_ids': station_link_ids,
        'processed': total_processed,
        'total_records': total_records,
        'skipped': skipped,
        'errors': errors
    }


@app.on_after_finalize.connect
def setup_network_plugin_processing_tasks(sender, **kwargs):
    from .models import NetworkConnection
    network_connections = NetworkConnection.objects.filter()
    
    for network_connection in network_connections:
        create_or_update_network_plugin_periodic_tasks(network_connection)


@worker_ready.connect
def unlock_all(**kwargs):
    clear_locks(app)
    
    # get lock keys
    cache_lock_keys = cache.keys("lock:station:*")
    
    # clear all locks
    if cache_lock_keys:
        logger.info(f"Unlocking all station links: {len(cache_lock_keys)}...")
        for cache_lock_key in cache_lock_keys:
            cache.delete(cache_lock_key)


def create_or_update_network_plugin_periodic_tasks(network_connection):
    interval = network_connection.plugin_processing_interval
    enabled = network_connection.plugin_processing_enabled
    
    sig = run_network_plugin.s(network_connection.id)
    name = repr(sig)
    
    # Create or update the periodic task
    schedule, created = IntervalSchedule.objects.get_or_create(
        every=interval,
        period=IntervalSchedule.MINUTES,
    )
    PeriodicTask.objects.update_or_create(
        name=name,
        defaults={
            'interval': schedule,
            'task': sig.name,
            'args': json.dumps([network_connection.id]),
            'enabled': enabled,
            'queue': 'adl',
        }
    )


def update_network_plugin_periodic_task(sender, instance, **kwargs):
    create_or_update_network_plugin_periodic_tasks(instance)


# Deliberately NOT a Singleton task: a stale singleton lock silently discards
# every subsequent beat tick. Overlap protection lives in the per-station
# cache lock inside dispatch_station instead.
@shared_task(bind=True, name="adl.core.tasks.perform_channel_dispatch")
def perform_channel_dispatch(self, channel_id, station_link_ids=None):
    from .models import DispatchChannel, DispatchChannelHeartbeat
    channel = get_object_or_none(DispatchChannel, id=channel_id)

    if not channel:
        message = f"Dispatch channel with id {channel_id} does not exist"
        logger.error(message)
        raise ValueError(message)

    eligible = channel.stations_allowed_to_send()
    if station_link_ids:
        eligible = eligible.filter(id__in=station_link_ids)

    ids = list(eligible.values_list("id", flat=True))

    soft_time_limit = channel.dispatch_timeout_seconds
    for station_link_id in ids:
        dispatch_station.apply_async(
            args=[channel_id, station_link_id],
            queue="adl",
            soft_time_limit=soft_time_limit,
            time_limit=soft_time_limit + DISPATCH_TIME_LIMIT_GRACE_SECONDS,
        )

    DispatchChannelHeartbeat.objects.update_or_create(
        channel=channel,
        defaults={"last_run_at": dj_timezone.now(), "stations_spawned": len(ids)},
    )

    logger.info("[DISPATCH] Channel %s: spawned %d station dispatch tasks", channel.name, len(ids))
    return {"stations_dispatched": len(ids)}


@shared_task(bind=True, name="adl.core.tasks.dispatch_station")
def dispatch_station(self, channel_id, station_link_id):
    from .models import DispatchChannel, StationChannelDispatchStatus, StationLink

    channel = get_object_or_none(DispatchChannel, id=channel_id)
    station_link = get_object_or_none(StationLink, id=station_link_id)

    if not channel or not station_link:
        logger.error("[DISPATCH] dispatch_station: channel %s or station_link %s not found",
                     channel_id, station_link_id)
        return

    lock_key = dispatch_station_lock_key(channel_id, station_link_id)
    lock_ttl = (channel.dispatch_timeout_seconds
                + DISPATCH_TIME_LIMIT_GRACE_SECONDS
                + DISPATCH_LOCK_TTL_MARGIN_SECONDS)

    if not cache.add(lock_key, "locked", timeout=lock_ttl):
        logger.warning("[DISPATCH] Station %s on channel %s still dispatching. Skipping...",
                       station_link, channel.name)
        StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=station_link,
            direction="push",
            dispatch_channel=channel,
            success=True,
            status=StationLinkActivityLog.ActivityStatus.SKIPPED,
            message="Skipped — previous dispatch still running",
        )
        return {"records_sent": 0, "skipped": True}

    start = time.monotonic()
    log = StationLinkActivityLog.objects.create(
        time=dj_timezone.now(),
        station_link=station_link,
        direction="push",
        dispatch_channel=channel,
    )

    try:
        data_records = get_station_dispatch_records(channel, station_link)

        if not data_records:
            log.success = True
            log.records_count = 0
            log.message = "No data records to send"
            log.status = StationLinkActivityLog.ActivityStatus.COMPLETED
            return {"records_sent": 0}

        num_sent, last_sent_obs_time = channel.send_station_data(station_link, data_records)

        previous_sent_obs_time = None
        if num_sent > 0 and last_sent_obs_time:
            status = get_object_or_none(
                StationChannelDispatchStatus,
                channel_id=channel_id,
                station_id=station_link.station_id,
            )
            if status:
                previous_sent_obs_time = status.last_sent_obs_time
                status.last_sent_obs_time = last_sent_obs_time
                status.save()
            else:
                StationChannelDispatchStatus.objects.create(
                    channel_id=channel_id,
                    station_id=station_link.station_id,
                    last_sent_obs_time=last_sent_obs_time,
                )

        log.success = True
        log.records_count = num_sent
        if previous_sent_obs_time:
            log.obs_start_time = previous_sent_obs_time
        if last_sent_obs_time:
            log.obs_end_time = last_sent_obs_time
        log.status = StationLinkActivityLog.ActivityStatus.COMPLETED
        log.message = f"Sent {num_sent} records successfully."
        return {"records_sent": num_sent}

    except SoftTimeLimitExceeded:
        timeout = channel.dispatch_timeout_seconds
        log.success = False
        log.message = f"Dispatch timed out after {timeout} seconds"
        log.status = StationLinkActivityLog.ActivityStatus.FAILED
        logger.error("[DISPATCH] Dispatch for station %s on channel %s timed out after %s seconds",
                     station_link, channel.name, timeout)
        return {"records_sent": 0, "timed_out": True}

    except Exception as e:
        log.success = False
        log.message = str(e)
        log.status = StationLinkActivityLog.ActivityStatus.FAILED
        logger.error("[DISPATCH] Error dispatching station %s on channel %s: %s",
                     station_link, channel.name, e)
        raise

    finally:
        cache.delete(lock_key)
        log.duration_ms = (time.monotonic() - start) * 1000
        log.save()


@shared_task(name="adl.core.tasks.sweep_stale_dispatch_logs")
def sweep_stale_dispatch_logs():
    """
    Mark push activity logs stranded in STARTED as failed.

    A dispatch that dies with the worker (hard time limit, OOM, container
    kill) never reaches the code that finalizes its activity log, leaving the
    row in STARTED forever. Rows older than their channel's dispatch timeout
    plus the same grace + margin used for the station lock TTL cannot still
    be running, so they are swept to FAILED.
    """
    from .models import DispatchChannel  # noqa: F401  (FK target must be loaded)

    now = dj_timezone.now()
    swept = 0

    candidates = StationLinkActivityLog.objects.filter(
        direction="push",
        status=StationLinkActivityLog.ActivityStatus.STARTED,
        dispatch_channel__isnull=False,
    )

    for log in candidates:
        threshold_seconds = (log.dispatch_channel.dispatch_timeout_seconds
                             + DISPATCH_TIME_LIMIT_GRACE_SECONDS
                             + DISPATCH_LOCK_TTL_MARGIN_SECONDS)
        if log.time < now - timedelta(seconds=threshold_seconds):
            log.status = StationLinkActivityLog.ActivityStatus.FAILED
            log.success = False
            log.message = "Dispatch worker died mid-dispatch (no completion recorded)"
            log.save(update_fields=["status", "success", "message"])
            swept += 1

    if swept:
        logger.warning("[DISPATCH] Swept %d stale dispatch activity log(s) to FAILED", swept)

    return swept


def create_or_update_dispatch_channel_periodic_tasks(dispatch_channel):
    interval = dispatch_channel.data_check_interval
    enabled = dispatch_channel.enabled
    
    sig = perform_channel_dispatch.s(dispatch_channel.id)
    name = repr(sig)
    
    # Create or update the periodic task
    schedule, created = IntervalSchedule.objects.get_or_create(
        every=interval,
        period=IntervalSchedule.MINUTES,
    )
    
    PeriodicTask.objects.update_or_create(
        name=name,
        defaults={
            'interval': schedule,
            'task': sig.name,
            'args': json.dumps([dispatch_channel.id]),
            'enabled': enabled,
            'queue': 'adl',
        }
    )


def update_dispatch_channel_periodic_tasks(sender, instance, **kwargs):
    create_or_update_dispatch_channel_periodic_tasks(instance)
