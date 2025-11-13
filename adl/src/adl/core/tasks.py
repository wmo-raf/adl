import json
import logging
import time

from celery import shared_task
from celery.schedules import crontab
from celery.signals import worker_ready
from celery_singleton import Singleton, clear_locks
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone as dj_timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from more_itertools import chunked

from adl.config.celery import app
from .dispatchers import run_dispatch_channel
from .logging import TaskLogger
from .utils import get_object_or_none

logger = logging.getLogger(__name__)


@app.task(base=Singleton, bind=True)
def run_backup(self):
    # Run the `dbbackup` command
    logger.info("[BACKUP] Running backup")
    call_command('dbbackup', '--clean', '--noinput')
    
    # Run the `mediabackup` command
    logger.info("[BACKUP] Running mediabackup")
    call_command('mediabackup', '--clean', '--noinput')


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(hour=0, minute=0),
        run_backup.s(),
        name="run-backup-daily-at-midnight",
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
        
        task = process_station_link_batch.delay(network_id, batch_list)
        
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
    from adl.monitoring.models import StationLinkActivityLog
    
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
        activity_log = StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=station_link,
            direction='pull',
        )
        
        log.info("Processing station link: %s (ID: %d)", station_link, station_link_id)
        
        try:
            # This will now log to WebSocket via the plugin's logger
            saved_records_count = plugin.process_station(station_link)
            
            activity_log.success = True
            activity_log.records_count = saved_records_count
            
            if saved_records_count > 0:
                log.success("Processed %d records for station link %s",
                            saved_records_count, station_link)
                total_records += saved_records_count
            else:
                log.info("No new records for station link %s", station_link)
            
            total_processed += 1
        
        except Exception as e:
            activity_log.success = False
            activity_log.message = str(e)
            log.error("Error processing station link %s: %s", station_link, str(e), exc_info=True)
            errors += 1
        
        finally:
            activity_log.duration_ms = (time.monotonic() - start) * 1000
            activity_log.save()
            
            # Release the lock after processing
            cache.delete(lock_key)
            
            log.info("Station link %s completed in %.2fms",
                     station_link, activity_log.duration_ms)
    
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
        }
    )


def update_network_plugin_periodic_task(sender, instance, **kwargs):
    create_or_update_network_plugin_periodic_tasks(instance)


@app.task(
    base=Singleton,
    bind=True
)
def perform_channel_dispatch(self, channel_id, station_link_ids=None):
    from .models import DispatchChannel
    channel = get_object_or_none(DispatchChannel, id=channel_id)
    
    if not channel:
        message = f"Dispatch channel with id {channel_id} does not exist"
        logger.error(message)
        raise ValueError(message)
    
    num_of_sent_records = run_dispatch_channel(channel.id, station_link_ids=station_link_ids)
    
    return {"records_count": num_of_sent_records}


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
        }
    )


def update_dispatch_channel_periodic_tasks(sender, instance, **kwargs):
    create_or_update_dispatch_channel_periodic_tasks(instance)
