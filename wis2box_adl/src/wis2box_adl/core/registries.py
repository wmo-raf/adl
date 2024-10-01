import logging

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .registry import Registry, Instance
from .wis2box import upload_to_wis2box

logger = logging.getLogger(__name__)


class Plugin(Instance):
    label = ""

    def __init__(self):
        if not self.label:
            raise ImproperlyConfigured("The label of a plugin must be set.")

    def get_data(self):
        raise NotImplementedError

    def run_process(self):
        from wis2box_adl.core.models import PluginExecutionEvent

        event = PluginExecutionEvent.objects.create(plugin=self.type)

        try:
            ingestion_record_ids = self.get_data()

            if ingestion_record_ids and len(ingestion_record_ids) > 0:
                for record_id in ingestion_record_ids:
                    upload_to_wis2box(record_id, event)
            else:
                logger.info("[WIS2BOX_ADL_PLUGIN] No ingestion records returned by plugin get_data")

            event.success = True
            event.finished_at = timezone.localtime()
            event.save()

        except Exception as e:
            logger.error(f"[WIS2BOX_ADL_PLUGIN] Error in plugin execution: {e}")
            event.error_message = str(e)
            event.success = False
            event.finished_at = timezone.localtime()
            event.save()
            return


class PluginRegistry(Registry):
    """
    With the plugin registry it is possible to register new plugins. A plugin is an
    abstraction made specifically for ADL. It allows to develop specific functionalities for different data sources
    """

    name = "adl_plugin"


plugin_registry = PluginRegistry()
