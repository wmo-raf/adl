import json
import logging

from celery.signals import worker_ready
from celery_singleton import Singleton, clear_locks
from django.utils import timezone as dj_timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask, CrontabSchedule

from adl.config.celery import app
from .utils import get_object_or_none

logger = logging.getLogger(__name__)


@app.task(
    base=Singleton,
    bind=True
)
def run_network_plugin(self, network_id):
    from adl.core.registries import plugin_registry
    from .models import NetworkConnection
    network_connection = get_object_or_none(NetworkConnection, id=network_id)
    
    if not network_connection:
        logger.error(f"Network Connection with id {network_id} does not exist. Skipping...")
        return
    
    network_plugin_type = network_connection.plugin
    plugin = plugin_registry.get(network_plugin_type)
    
    if plugin:
        plugin_processing_enabled = network_connection.plugin_processing_enabled
        
        if not plugin_processing_enabled:
            logger.info(f"Network plugin processing is disabled for network {network_connection.name}.Skipping...")
            return
        
        logger.info(f"Starting plugin processing '{plugin}' for network {network_connection.name}...")
        plugin.run_process(network_connection)


@app.task(
    base=Singleton,
    bind=True
)
def check_plugin_unploaded_records(self, network_connection_id):
    from adl.core.registries import plugin_registry
    from .models import NetworkConnection
    
    network_connection = get_object_or_none(NetworkConnection, id=network_connection_id)
    
    if not network_connection:
        logger.error(f"NetworkConnection with id {network_connection_id} does not exist. Skipping...")
        return
    
    network_plugin_type = network_connection.plugin
    plugin = plugin_registry.get(network_plugin_type)
    
    if plugin:
        plugin_processing_enabled = network_connection.plugin_processing_enabled
        
        if not plugin_processing_enabled:
            logger.info(
                f"Network plugin processing is disabled for network connection {network_connection.name}.Skipping...")
            return
        
        logger.info(f"Starting unploaded records check for '{plugin}' for network {network_connection.name}...")
        plugin.check_unploaded_records(network_connection)


@app.on_after_finalize.connect
def setup_network_plugin_processing_tasks(sender, **kwargs):
    from .models import NetworkConnection
    network_connections = NetworkConnection.objects.filter()
    
    for network_connection in network_connections:
        create_or_update_network_plugin_periodic_tasks(network_connection)


@worker_ready.connect
def unlock_all(**kwargs):
    clear_locks(app)


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
def perform_hourly_aggregation(self):
    from .aggregation import aggregate_hourly
    aggregate_hourly()


@app.task(
    base=Singleton,
    bind=True
)
def perform_daily_aggregation(self):
    from .aggregation import aggregate_daily
    aggregate_daily()


def create_or_update_aggregation_periodic_tasks(settings):
    hourly_aggregation_interval = settings.hourly_aggregation_interval
    daily_aggregation_time = settings.daily_aggregation_time
    
    sig_hourly = perform_hourly_aggregation.s()
    name_hourly = repr(sig_hourly)
    
    sig_daily = perform_daily_aggregation.s()
    name_daily = repr(sig_daily)
    
    # Create or update the periodic task
    hourly_schedule, _ = IntervalSchedule.objects.get_or_create(
        every=hourly_aggregation_interval,
        period=IntervalSchedule.MINUTES,
    )
    PeriodicTask.objects.update_or_create(
        name=name_hourly,
        defaults={
            'interval': hourly_schedule,
            'task': sig_hourly.name,
            'enabled': True,
        }
    )
    
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
    
    if channel:
        channel.dispatch()


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
