import logging

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .registry import Registry, Instance
from .utils import create_ingestion_file_with_hourly_time

logger = logging.getLogger(__name__)


class Plugin(Instance):
    label = ""
    
    def __init__(self):
        if not self.label:
            raise ImproperlyConfigured("The label of a plugin must be set.")
    
    def get_urls(self):
        """
        If needed root urls related to the plugin can be added here.

        Example:

            def get_urls(self):
                from . import plugin_urls

                return [
                    path('some-url/', include(plugin_urls, namespace=self.type)),
                ]

            # plugin_urls.py
            from django.urls import path

            urlpatterns = [
                path('plugin-name/some-view', SomeView.as_view(), name='some_view'),
            ]

        :return: A list containing the urls.
        :rtype: list
        """
        
        return []
    
    def get_data(self):
        raise NotImplementedError
    
    def run_process(self, network):
        from adl.core.models import PluginExecutionEvent
        
        event = PluginExecutionEvent.objects.create(plugin=self.type)
        
        try:
            ingestion_record_ids = self.get_data()
            
            if ingestion_record_ids:
                self.ingest_records(ingestion_record_ids, network, event)
            
            event.success = True
            event.finished_at = timezone.localtime()
            event.save()
        
        except Exception as e:
            logger.error(f"[ADL_PLUGIN] Error in plugin execution: {e}")
            event.error_message = str(e)
            event.success = False
            event.finished_at = timezone.localtime()
            event.save()
    
    def check_unploaded_records(self, network):
        from adl.core.models import PluginExecutionEvent, DataIngestionRecord
        
        unuploaded_record_ids = DataIngestionRecord.objects.filter(uploaded_to_wis2box=False,
                                                                   station__network=network).values_list('id',
                                                                                                         flat=True)
        
        logger.info(f"[ADL_PLUGIN] Found {len(unuploaded_record_ids)} records not yet uploaded. "
                    f"Trying to upload now...")
        
        if unuploaded_record_ids:
            event = PluginExecutionEvent.objects.create(plugin=self.type)
            
            try:
                self.ingest_records(unuploaded_record_ids, network, event)
                
                event.success = True
                event.finished_at = timezone.localtime()
                event.save()
            
            except Exception as e:
                logger.error(f"[ADL_PLUGIN] Error in plugin execution: {e}")
                event.error_message = str(e)
                event.success = False
                event.finished_at = timezone.localtime()
                event.save()
        else:
            logger.info(f"[ADL_PLUGIN] No records not uploaded for network {network.name}")
    
    def ingest_records(self, ingestion_record_ids, network, event):
        from adl.core.models import DataIngestionRecord
        
        if ingestion_record_ids and len(ingestion_record_ids) > 0:
            ingestion_records = DataIngestionRecord.objects.filter(id__in=ingestion_record_ids)
            
            # hourly aggregation not set
            if not network.wis2box_hourly_aggregate:
                logger.info("[ADL_PLUGIN] Hourly aggregation not set, uploading every record to WIS2BOX")
                for record in ingestion_records:
                    pass
                    # upload_to_wis2box(record.id, event.id)
            else:
                # hourly aggregation set
                if network.wis2box_hourly_aggregate_strategy == "latest":
                    logger.info("[ADL_PLUGIN] Hourly aggregation set to latest, checking for latest records")
                    
                    # group by stations
                    stations = {}
                    for record in ingestion_records:
                        if record.station_id not in stations:
                            stations[record.station_id] = []
                        stations[record.station_id].append(record)
                    
                    current_time = timezone.localtime()
                    
                    # iterate over stations
                    for station_id, records in stations.items():
                        station = records[0].station
                        
                        # group station records by day by hour
                        data = {}
                        
                        for record in records:
                            # skip if record time is today and record hour is equal to current hour
                            # we want to aggregate data from full hours. If record hour is equal to current hour,
                            # we do not know if we have all the data for the current hour
                            if record.time.date() == current_time.date() and record.time.hour == current_time.hour:
                                logger.info(
                                    f"[ADL_PLUGIN] Skipping record for station {station.name} "
                                    f"as it is from the current hour, {record.time}")
                                continue
                            
                            key = record.time.strftime("%Y-%m-%d")
                            
                            if key not in data:
                                data[key] = {}
                            
                            # group by hour
                            hour_key = record.time.strftime("%H")
                            if hour_key not in data[key]:
                                data[key][hour_key] = []
                            
                            data[key][hour_key].append(record)
                        
                        # pick the latest record of each hour
                        for day, hourly_data in data.items():
                            for hour, hourly_records in hourly_data.items():
                                latest_record = None
                                for h_record in hourly_records:
                                    if not latest_record or h_record.time > latest_record.time:
                                        latest_record = h_record
                                
                                if latest_record:
                                    logger.info(f"[ADL_PLUGIN] Found latest record for station {station.name}")
                                    
                                    print(latest_record)
                                    
                                    # mark the record as hourly aggregate
        
        else:
            logger.info("[ADL_PLUGIN] No ingestion records returned by plugin get_data")


class PluginRegistry(Registry):
    """
    With the plugin registry it is possible to register new plugins. A plugin is an
    abstraction made specifically for ADL. It allows to develop specific functionalities for different data sources
    """
    
    name = "adl_plugin"
    
    @property
    def urls(self):
        """
        Returns a list of all the urls that are in the registered instances. They
        are going to be added to the root url config.

        :return: The urls of the registered instances.
        :rtype: list
        """
        
        urls = []
        for types in self.registry.values():
            urls += types.get_urls()
        return urls


plugin_registry = PluginRegistry()
