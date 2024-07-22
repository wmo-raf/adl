import json
import logging

from celery.signals import worker_ready
from celery_singleton import Singleton, clear_locks
from django_celery_beat.models import PeriodicTask, IntervalSchedule

from wis2box_adl.config.celery import app
from .models import Network
from .utils import get_object_or_none

logger = logging.getLogger(__name__)


@app.task(
    base=Singleton,
    bind=True
)
def run_network_plugin(self, network_id):
    from wis2box_adl.core.registries import plugin_registry
    network = get_object_or_none(Network, id=network_id)

    if not network:
        logger.error(f"Network with id {network_id} does not exist. Skipping...")
        return

    network_plugin_type = network.plugin
    plugin = plugin_registry.get(network_plugin_type)

    if plugin:
        plugin_processing_enabled = network.plugin_processing_enabled

        if not plugin_processing_enabled:
            logger.info(f"Network plugin processing is disabled for network {network.name}.Skipping...")
            return

        logger.info(f"Starting plugin processing '{plugin}' for network {network.name}...")
        plugin.get_data()


@app.on_after_finalize.connect
def setup_network_plugin_processing_tasks(sender, **kwargs):
    networks = Network.objects.filter(plugin__isnull=False)

    for network in networks:
        create_or_update_network_plugin_periodic_task(network)


@worker_ready.connect
def unlock_all(**kwargs):
    clear_locks(app)


def create_or_update_network_plugin_periodic_task(network):
    interval = network.plugin_processing_interval
    enabled = network.plugin_processing_enabled

    sig = run_network_plugin.s(network.id)
    name = repr(sig)

    schedule, created = IntervalSchedule.objects.get_or_create(
        every=interval,
        period=IntervalSchedule.MINUTES,
    )

    PeriodicTask.objects.update_or_create(
        name=name,
        defaults={
            'interval': schedule,
            'task': sig.name,
            'args': json.dumps([network.id]),
            'enabled': enabled,
        }
    )
