from django.core.exceptions import ImproperlyConfigured
import logging

from .registry import Registry, Instance
from .wis2box_upload import upload_to_wis2box

logger = logging.getLogger(__name__)


class Plugin(Instance):
    label = ""

    def __init__(self):
        if not self.label:
            raise ImproperlyConfigured("The label of a plugin must be set.")

    def get_data(self):
        raise NotImplementedError

    def run_process(self):
        ingestion_record_ids = self.get_data()

        if ingestion_record_ids and len(ingestion_record_ids) > 0:
            for record_id in ingestion_record_ids:
                upload_to_wis2box(record_id)
        else:
            logger.info("[WIS2BOX_ADL_PLUGIN] No ingestion records returned by plugin get_data")


class PluginRegistry(Registry):
    """
    With the plugin registry it is possible to register new plugins. A plugin is an
    abstraction made specifically for ADL. It allows to develop specific functionalities for different data sources
    """

    name = "adl_plugin"


plugin_registry = PluginRegistry()
