import logging
from datetime import timedelta, datetime
from typing import Iterable, List, Dict, Any, Optional, Tuple

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as dj_timezone

from .registry import Registry, Instance
from .validators import StationRecordModel

logger = logging.getLogger(__name__)


class Plugin(Instance):
    """
     Base class for ADL data-source plugins.
 
     Child plugins must:
       - set `label` (human-readable)
       - implement `get_station_data(station_link, start_date, end_date)`
 
     Contract for `get_station_data`:
       - Input dates are timezone-aware (station timezone) or None.
       - Return an iterable of records. Each record MUST contain:
           - "observation_time": datetime (aware or naive interpreted as station tz)
         And MAY contain any number of source-parameter fields whose names match
         StationVariableMapping.source_parameter_name.
     """
    label = ""
    
    # ---------- Lifecycle ----------
    def __init__(self):
        super().__init__()
        if not self.label:
            raise ImproperlyConfigured("The label of a plugin must be set.")
    
    # ---------- URL exposure ----------
    def get_urls(self) -> list:
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
    
    # ---------- Data collection (abstract) ----------
    def get_station_data(
            self,
            station_link,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None,
    ) -> Iterable[Dict[str, Any]]:
        """
        Fetch raw observations for a station between [start_date, end_date).
       
        Must be implemented by child plugins.
        """
        raise NotImplementedError
    
    # ---------- Date helpers ----------
    def get_default_end_date(self, station_link) -> datetime:
        """
        Station-local 'top of next hour' as an aware datetime.
        """
        timezone = station_link.timezone
        end_date = dj_timezone.localtime(timezone=timezone)
        
        # set the end date to the start of the next hour
        end_date = end_date.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        
        return end_date
    
    def get_default_start_date(self, station_link) -> datetime:
        """
        One hour window ending at default_end_date.
        """
        end_date = self.get_default_end_date(station_link)
        # set to end_date of the previous hour
        start_date = end_date - timedelta(hours=1)
        return start_date
    
    def get_start_date_from_db(self, station_link) -> Optional[datetime]:
        """
        Latest saved ObservationRecord.time for this station+connection.
        Returns an aware UTC datetime (Django stores as UTC) or None.
        """
        from adl.core.models import ObservationRecord
        
        latest_observation_time = ObservationRecord.objects.filter(
            connection=station_link.network_connection,
            station=station_link.station,
        ).order_by('-time').values_list('time', flat=True).first()
        
        return latest_observation_time
    
    @staticmethod
    def _get_station_first_collection_date(station_link) -> Optional[datetime]:
        """
        Station's first collection date, localized to station tz if present.
        """
        date = station_link.get_first_collection_date()
        if date:
            return dj_timezone.localtime(date, timezone=station_link.timezone)
        return None
    
    def get_dates_for_station(self, station_link, latest=False) -> Tuple[datetime, datetime]:
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
        
        # localize to station tz (safe if already aware)
        tz = station_link.timezone
        start_date = dj_timezone.localtime(start_date, timezone=tz)
        end_date = dj_timezone.localtime(end_date, timezone=tz)
        
        return start_date, end_date
    
    # ---------- Persistence ----------
    def save_records(self, station_link, station_records: Iterable[Dict[str, Any]]):
        """
        Normalize and upsert observations into ObservationRecord.
        
        Expects each record to contain:
         - "observation_time": datetime
         - zero or more source parameter fields named exactly as in variable_mappings'
           `source_parameter_name`.
       """
        
        from adl.core.models import ObservationRecord
        station = station_link.station
        variable_mappings = list(station_link.get_variable_mappings() or [])
        
        if not variable_mappings:
            logger.warning("[%s] No variable mappings for station %s.", self.label, station.name)
            return None
        
        observation_records: List[ObservationRecord] = []
        tz = station_link.timezone
        
        for record in (station_records or []):
            try:
                rec = StationRecordModel(observation_time=record.get("observation_time"),
                                         values={k: v for k, v in record.items() if k != "observation_time"})
            except Exception as e:
                logger.warning("[%s] Bad record for station %s: %s", self.label, station.name, e)
                continue
            
            obs_time = rec.observation_time
            
            if not obs_time:
                logger.warning("[%s] Missing observation_time for station %s.", self.label, station.name)
                continue
            
            if not isinstance(obs_time, datetime):
                msg = (f"[{self.label}] observation_time for station {station.name} must be datetime, "
                       f"got {type(obs_time)}: {obs_time!r}")
                logger.error(msg)
                raise ValueError(msg)
            
            # Normalize to aware station-local time WITHOUT shifting the instant
            if dj_timezone.is_aware(obs_time):
                obs_time = obs_time.astimezone(tz)
            else:
                # Interpret naive as station-local
                obs_time = dj_timezone.make_aware(obs_time, timezone=tz)
            
            for mapping in variable_mappings:
                adl_param = getattr(mapping, "adl_parameter", None)
                src_name = getattr(mapping, "source_parameter_name", None)
                src_unit = getattr(mapping, "source_parameter_unit", None)
                
                # Validate required mapping attributes
                if not (adl_param and src_name and src_unit):
                    logger.warning(
                        "[%s] Bad variable mapping for station %s (id=%s): adl=%s src=%s unit=%s",
                        self.label, station.name, getattr(mapping, "id", "?"),
                        bool(adl_param), bool(src_name), bool(src_unit),
                    )
                    continue
                
                # convert to string for consistency
                src_name = str(src_name)
                
                if src_name not in rec.values:
                    # Fine to skip silently; use debug
                    logger.debug(
                        "[%s] No value for parameter %s (%s) in station %s at %s. Skipping.",
                        self.label, adl_param.name, src_name, station.name, obs_time
                    )
                    continue
                
                value = rec.values.get(src_name)
                
                # Skip if value is None or not a number
                if value is None or not (isinstance(value, (int, float))):
                    continue
                
                # Unit conversion if needed
                try:
                    if adl_param.unit != src_unit:
                        value = adl_param.convert_value_from_units(value, src_unit)
                except Exception as e:
                    logger.warning(
                        "[%s] Unit conversion failed for %s (%s→%s) on station %s: %s",
                        self.label, adl_param.name, src_unit, adl_param.unit, station.name, e
                    )
                    continue
                
                observation_records.append(
                    ObservationRecord(
                        station=station,
                        parameter=adl_param,
                        time=obs_time,
                        value=value,
                        connection=station_link.network_connection,
                        is_daily=station_link.network_connection.is_daily_data
                    )
                )
        
        if not observation_records:
            logger.warning("[%s] No valid observation records for station %s.", self.label, station.name)
            return None
        
        return ObservationRecord.objects.bulk_create(
            observation_records,
            update_conflicts=True,
            update_fields=["value", "is_daily"],
            unique_fields=["time", "station", "connection", "parameter"],
            batch_size=1000
        )
    
    # ---------- Orchestration ----------
    def process_station(self, station_link) -> int:
        start_date, end_date = self.get_dates_for_station(station_link)
        
        logger.info("[%s] Fetching %s from %s to %s.",
                    self.label, station_link, start_date, end_date)
        
        # get the station data
        station_records = self.get_station_data(station_link, start_date=start_date, end_date=end_date)
        
        # save the records to the database
        saved_obs_records = self.save_records(station_link, station_records)
        
        saved_obs_records_count = len(saved_obs_records) if saved_obs_records else 0
        
        return saved_obs_records_count
    
    def run_process(self, network_connection) -> Dict[int, int]:
        
        station_links = network_connection.station_links.all()
        
        results: Dict[int, int] = {}
        
        logger.info("[%s] Processing %d station links for %s.",
                    self.label, len(station_links), network_connection.name)
        
        # process each station link
        for station_link in station_links:
            if not station_link.enabled:
                logger.info("[%s] Skipping disabled station link: %s", self.label, station_link)
                continue
            
            results[station_link.station.id] = self.process_station(station_link)
        
        return results


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
