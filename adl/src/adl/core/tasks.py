import json
import logging
import time

from celery import shared_task
from celery.signals import worker_ready
from celery_singleton import Singleton, clear_locks
from django.core.cache import cache
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_time
from django_celery_beat.models import IntervalSchedule, PeriodicTask, CrontabSchedule
from more_itertools import chunked

from adl.config.celery import app
from .utils import get_object_or_none

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_network_plugin(self, network_id):
    from .models import NetworkConnection
    network_connection = get_object_or_none(NetworkConnection, id=network_id)
    
    if not network_connection:
        logger.error(f"Network Connection with id {network_id} does not exist. Skipping...")
        return
    
    batch_size = network_connection.batch_size or 10
    
    station_link_ids = network_connection.station_links.filter(enabled=True).values_list("id", flat=True)
    for batch in chunked(station_link_ids, batch_size):
        process_station_link_batch_task.delay(network_id, batch)


@shared_task(bind=True)
def process_station_link_batch_task(self, network_id, station_link_ids):
    from adl.core.registries import plugin_registry
    from .models import NetworkConnection
    from .models import StationLink
    from adl.monitoring.models import StationLinkActivityLog
    
    network_connection = get_object_or_none(NetworkConnection, id=network_id)
    
    if not network_connection:
        logger.error(f"Network Connection with id {network_id} does not exist. Skipping...")
        return
    
    network_plugin_type = network_connection.plugin
    plugin = plugin_registry.get(network_plugin_type)
    
    for station_link_id in station_link_ids:
        station_link = get_object_or_none(StationLink, id=station_link_id)
        
        if not station_link:
            logger.error(f"Station link with id {station_link_id} does not exist. Skipping...")
            continue
        
        lock_key = f"lock:station:{station_link_id}"
        
        lock_acquired = cache.add(lock_key, "locked", timeout=None)
        
        if not lock_acquired:
            logger.warning(f"Station link {station_link_id} is still processing. Skipping...")
            continue
        
        start = time.monotonic()
        log = StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=station_link,
            direction='pull',
        )
        
        try:
            saved_records_count = plugin.process_station(station_link)
            
            log.success = True
            log.records_count = saved_records_count
        except Exception as e:
            log.success = False
            log.message = str(e)
            logger.error(f"Error processing station link {station_link_id}: {e}")
        finally:
            
            log.duration_ms = (time.monotonic() - start) * 1000
            log.save()
            
            # Release the lock after processing
            cache.delete(lock_key)


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
def perform_daily_aggregation(self):
    from .aggregation import aggregate_daily
    aggregate_daily()


@app.task(
    base=Singleton,
    bind=True
)
def perform_hourly_aggregation(self, network_connection_id):
    from .aggregation import aggregate_hourly_network_connection
    aggregate_hourly_network_connection(network_connection_id)


def create_or_update_aggregation_periodic_tasks(settings):
    if not settings.daily_aggregation_time:
        logger.error("Daily aggregation time is not set. Skipping...")
        return
    
    daily_aggregation_time = settings.daily_aggregation_time
    
    # Parse the daily aggregation time if it is a string
    # This is used before the settings are updated/saved for the first time
    if isinstance(daily_aggregation_time, str):
        daily_aggregation_time = parse_time(daily_aggregation_time)
    
    sig_daily = perform_daily_aggregation.s()
    name_daily = repr(sig_daily)
    
    # Create or update the periodic task
    
    daily_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute=daily_aggregation_time.minute,
        hour=daily_aggregation_time.hour,
        day_of_week='*',
        day_of_month='*',
        month_of_year='*',
        timezone=dj_timezone.get_current_timezone()
    )
    
    PeriodicTask.objects.update_or_create(
        name=name_daily,
        defaults={
            'crontab': daily_schedule,
            'task': sig_daily.name,
            'enabled': True,
        }
    )


@app.task(
    base=Singleton,
    bind=True
)
def perform_channel_dispatch(self, channel_id):
    from .models import DispatchChannel
    channel = get_object_or_none(DispatchChannel, id=channel_id)
    
    if not channel:
        message = f"Dispatch channel with id {channel_id} does not exist"
        logger.error(message)
        raise ValueError(message)
    
    num_of_sent_records = channel.dispatch()
    
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
