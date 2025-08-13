import logging
from datetime import timedelta, datetime

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as dj_timezone

from .registry import Registry, Instance

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
    
    def get_station_data(self, station_link, start_date=None, end_date=None):
        raise NotImplementedError
    
    def get_default_end_date(self, station_link):
        timezone = station_link.timezone
        end_date = dj_timezone.localtime(timezone=timezone)
        
        # set the end date to the start of the next hour
        end_date = end_date.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        
        return end_date
    
    def get_default_start_date(self, station_link):
        end_date = self.get_default_end_date(station_link)
        # set to end_date of the previous hour
        start_date = end_date - timedelta(hours=1)
        return start_date
    
    def save_records(self, station_link, station_records):
        from adl.core.models import ObservationRecord
        station = station_link.station
        variable_mappings = station_link.get_variable_mappings()
        
        observation_records = []
        
        for record in station_records:
            observation_time = record.get("observation_time")
            
            if not observation_time:
                logger.warning(f"[{self.label}] No observation time found in record for station {station.name}.")
                continue
            
            if not isinstance(observation_time, datetime):
                error = (
                    f"[{self.label}] Observation time for station {station.name} is not a datetime object: {observation_time}. "
                    f"Please ensure your plugin returns a valid datetime object for observation_time.")
                logger.error(error)
                raise ValueError(error)
            
            if dj_timezone.is_aware(observation_time):
                # If the observation time is timezone-aware, convert it to naive
                observation_time = observation_time.replace(tzinfo=None)
            
            observation_time = dj_timezone.make_aware(observation_time, timezone=station_link.timezone)
            
            for variable in variable_mappings:
                if not hasattr(variable, "adl_parameter"):
                    logger.warning(f"[{self.label}] Variable mapping for station {station.name} does not have "
                                   f"adl_parameter set. Skipping.")
                    continue
                
                if not hasattr(variable, "source_parameter_name"):
                    logger.warning(f"[{self.label}] Variable mapping for station {station.name} does not have "
                                   f"source_parameter_name set. Skipping.")
                    continue
                
                if not hasattr(variable, "source_parameter_unit"):
                    logger.warning(f"[{self.label}] Variable mapping for station {station.name} does not have "
                                   f"source_parameter_unit set. Skipping.")
                    continue
                
                adl_parameter = variable.adl_parameter
                source_parameter_name = variable.source_parameter_name
                source_parameter_unit = variable.source_parameter_unit
                
                value = record.get(source_parameter_name)
                
                if value is None:
                    logger.debug(f"[{self.label}] No data record found for parameter {adl_parameter.name} "
                                 f"in station {station.name}. Skipping.")
                    continue
                
                if adl_parameter.unit != source_parameter_unit:
                    value = adl_parameter.convert_value_from_units(value, source_parameter_unit)
                
                record_data = {
                    "station": station,
                    "parameter": adl_parameter,
                    "time": observation_time,
                    "value": value,
                    "connection": station_link.network_connection,
                }
                
                param_obs_record = ObservationRecord(**record_data)
                observation_records.append(param_obs_record)
        
        if not observation_records:
            logger.warning(f"[{self.label}] No valid observation records found for station {station.name}.")
            return None
        
        return ObservationRecord.objects.bulk_create(
            observation_records,
            update_conflicts=True,
            update_fields=["value"],
            unique_fields=["station", "parameter", "time", "connection"]
        )
    
    def get_start_date_from_db(self, station_link):
        from adl.core.models import ObservationRecord
        
        # get the latest observation time for the station and connection
        latest_observation_time = ObservationRecord.objects.filter(
            connection=station_link.network_connection,
            station=station_link.station,
        ).order_by('-time').values_list('time', flat=True).first()
        
        return latest_observation_time
    
    def run_process(self, network_connection):
        
        station_links = network_connection.station_links.all()
        
        all_saved_records_count = {}
        
        logger.info(
            f"[{self.label}] Processing {len(station_links)} station links for connection {network_connection.name}.")
        
        # process each station link
        for station_link in station_links:
            if not station_link.enabled:
                logger.info(f"[{self.label}] Skipping disabled station link: {station_link}")
                continue
            
            saved_obs_records_count = self.process_station(station_link)
            
            all_saved_records_count[station_link.station.id] = saved_obs_records_count
        
        return all_saved_records_count
    
    @staticmethod
    def _get_station_first_collection_date(station_link):
        """Return station's first collection date in its local timezone, or None."""
        date = station_link.get_first_collection_date()
        if date:
            return dj_timezone.localtime(date, timezone=station_link.timezone)
        return None
    
    def get_dates_for_station(self, station_link, latest=False):
        """
        Determine start_date based on priority:
        
        If latest=True:
            → Always use the default start date (fresh fetch, ignore history)
        Else:
            → 1. Use the latest observation date from the DB (resume where left off)
            → 2. If missing, use Station's first collection date (apply station timezone)
            → 3. If still missing, use default start date (last resort)
        """
        
        if latest:
            start_date = self.get_default_start_date(station_link)
        else:
            start_date = (
                    self.get_start_date_from_db(station_link)
                    or self._get_station_first_collection_date(station_link)
                    or self.get_default_start_date(station_link)
            )
        
        end_date = self.get_default_end_date(station_link)
        
        if end_date == start_date:
            end_date += timedelta(hours=1)
        
        return start_date, end_date
    
    def process_station(self, station_link):
        start_date, end_date = self.get_dates_for_station(station_link)
        
        logger.info(
            f"[{self.label}] Getting data for station link: {station_link} from {start_date} to {end_date}.")
        
        # get the station data
        station_records = self.get_station_data(station_link, start_date=start_date, end_date=end_date)
        
        # save the records to the database
        saved_obs_records = self.save_records(station_link, station_records)
        
        saved_obs_records_count = len(saved_obs_records) if saved_obs_records else 0
        
        return saved_obs_records_count


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


class CustomUnitContextRegistry(Registry):
    name = "adl_unit_context_registry"
    
    def get_choices(self):
        """
        Returns the choices for the custom unit context.

        :return: The choices for the custom unit context.
        :rtype: List[Tuple[str, str]]
        """
        
        return [(k, v.label) for k, v in self.registry.items()]


custom_unit_context_registry = CustomUnitContextRegistry()


class ViewSetRegistry(Registry):
    def __init__(self, name, allow_instance_override=True):
        self.name = name
        super().__init__(allow_instance_override=allow_instance_override)


dispatch_channel_viewset_registry = ViewSetRegistry(name="dispatch_channel_viewset_registry")
connection_viewset_registry = ViewSetRegistry(name="connection_viewset_registry")
station_link_viewset_registry = ViewSetRegistry(name="station_link_viewset_registry")
