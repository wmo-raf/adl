import logging
from datetime import timedelta, datetime
from typing import Iterable, List, Dict, Any, Optional, Tuple

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as dj_timezone

from .registry import Registry, Instance
from .validators import StationRecordModel

logger = logging.getLogger(__name__)
from datetime import timezone as py_tz


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
        
        # Initialize QC pipeline cache
        self._qc_pipelines_cache = {}
    
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
    
    def after_save_records(self, station_link, station_records, saved_records, qc_fail_results=None) -> None:
        """
        Hook called after saving ObservationRecord instances for a station.
        Can be overridden by child plugins if needed.
        
        :param station_link: The StationLink instance for which records were saved.
        :param station_records: List of raw station records that were processed.
        :param saved_records: List of saved ObservationRecord instances.
        :param qc_fail_results:
        """
        pass
    
    def _create_qc_messages(self, saved_records, qc_results) -> None:
        from adl.core.models import QCMessage
        
        qc_result_objects = []
        for record in saved_records:
            utc_obs_time_key = dj_timezone.localtime(record.time, timezone=py_tz.utc).isoformat()
            record_qc_results = qc_results.get(utc_obs_time_key)
            if record_qc_results:
                for fail_result in record_qc_results:
                    check_type = fail_result.get("check_type")
                    reason = fail_result.get("reason")
                    qc_message_data = {
                        "obs_record_id": record.id,
                        "obs_time": record.time,
                        "station_id": record.station_id,
                        "parameter_id": record.parameter_id,
                        "check_type": check_type,
                        "message": reason,
                    }
                    fail_result_obj = QCMessage(**qc_message_data)
                    qc_result_objects.append(fail_result_obj)
        
        if qc_result_objects:
            QCMessage.objects.bulk_create(qc_result_objects, batch_size=1000)
    
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
    
    def save_records(self, station_link, station_records: Iterable[Dict[str, Any]]) -> Optional[List[Any]]:
        """
        Normalize and upsert observations into ObservationRecord using QCPipeline system.
        """
        from adl.core.models import ObservationRecord
        
        station = station_link.station
        variable_mappings = list(station_link.get_variable_mappings() or [])
        
        if not variable_mappings:
            logger.warning("[%s] No variable mappings for station %s.", self.label, station.name)
            return None
        
        observation_records = {}
        tz = station_link.timezone
        qc_results = {}
        
        # Initialize QC pipeline cache
        if not hasattr(self, '_qc_pipelines_cache'):
            self._qc_pipelines_cache = {}
        
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
                
                time_key = dj_timezone.localtime(obs_time, timezone=py_tz.utc).isoformat()
                utc_obs_key_with_param = f"{time_key}_{adl_param.id}"
                
                # QC PIPELINE SYSTEM: QC checks using pipeline
                qc_bits, qc_status, qc_messages = self.perform_qc_checks_with_pipeline(
                    value=value,
                    variable_mapping=mapping,
                    adl_param=adl_param,
                    station_link=station_link,
                    obs_time=obs_time
                )
                
                # Store QC results for message creation
                if qc_messages:
                    if utc_obs_key_with_param not in qc_results:
                        qc_results[utc_obs_key_with_param] = []
                    qc_results[utc_obs_key_with_param].extend(qc_messages)
                
                # Use a dict key to deduplicate in case of multiple records for same time/param
                if utc_obs_key_with_param in observation_records:
                    logger.info(
                        "[%s] Duplicate observation for station %s, time %s, parameter %s. Overwriting previous value.",
                        self.label, station.name, obs_time, adl_param.name
                    )
                
                observation_records[utc_obs_key_with_param] = ObservationRecord(
                    station=station,
                    parameter=adl_param,
                    time=obs_time,
                    value=value,
                    connection=station_link.network_connection,
                    is_daily=station_link.network_connection.is_daily_data,
                    qc_status=qc_status,
                    qc_bits=int(qc_bits),
                    qc_version=1,
                )
        
        observation_records_list = list(observation_records.values())
        
        if not observation_records_list:
            logger.warning("[%s] No valid observation records for station %s.", self.label, station.name)
            return None
        
        saved_records = ObservationRecord.objects.bulk_create(
            observation_records_list,
            update_conflicts=True,
            update_fields=["value", "is_daily", "qc_status", "qc_bits", "qc_version"],
            unique_fields=["time", "station", "connection", "parameter"],
            batch_size=1000
        )
        
        if saved_records:
            if qc_results:
                self._create_qc_messages(saved_records, qc_results)
            
            try:
                self.after_save_records(station_link, station_records, saved_records)
            except Exception as e:
                logger.error(
                    "[%s] after_save_records hook failed for station %s: %s",
                    self.label, station.name, e
                )
        
        return saved_records
    
    # ---------- Orchestration ----------
    def process_station(self, station_link, initial_start_date=None) -> int:
        start_date, end_date = self.get_dates_for_station(station_link)
        
        if initial_start_date:
            start_date = initial_start_date
        
        logger.info("[%s] Fetching %s from %s to %s.",
                    self.label, station_link, start_date, end_date)
        
        # get the station data
        station_records = self.get_station_data(station_link, start_date=start_date, end_date=end_date)
        
        if not station_records:
            logger.info("[%s] No new data for %s.", self.label, station_link)
            return 0
        
        earliest = min(station_records, key=lambda r: r["observation_time"])["observation_time"]
        latest = max(station_records, key=lambda r: r["observation_time"])["observation_time"]
        
        logger.info("[%s] Fetched %d records for %s from %s to %s.",
                    self.label, len(station_records), station_link, earliest, latest)
        
        # save the records to the database
        saved_obs_records = self.save_records(station_link, station_records)
        
        saved_obs_records_count = len(saved_obs_records) if saved_obs_records else 0
        
        return saved_obs_records_count
    
    def run_process(self, network_connection, start_date=None) -> Dict[int, int]:
        
        station_links = network_connection.station_links.all()
        
        results: Dict[int, int] = {}
        
        logger.info("[%s] Processing %d station links for %s.",
                    self.label, len(station_links), network_connection.name)
        
        # process each station link
        for station_link in station_links:
            if not station_link.enabled:
                logger.info("[%s] Skipping disabled station link: %s", self.label, station_link)
                continue
            
            results[station_link.station.id] = self.process_station(station_link, initial_start_date=start_date)
        
        return results
    
    def perform_qc_checks_with_pipeline(self, value: float, variable_mapping, adl_param, station_link,
                                        obs_time: datetime):
        """Perform QC checks using the QCPipeline system with optimized history fetching"""
        from adl.core.models import QCBits, QCStatus
        from adl.core.qc.config import QCConfigConverter, build_qc_context
        from adl.core.qc.validators import QCFlag
        
        if hasattr(variable_mapping, "qc_checks"):
            qc_checks = variable_mapping.qc_checks
        else:
            qc_checks = adl_param.qc_checks
        
        if qc_checks:
            return QCBits(0), QCStatus.NOT_EVALUATED, []
        
        # Create cache key with parameter version
        cache_key = f"{adl_param.id}_{adl_param.modified_at.timestamp()}"
        
        # Get or create pipeline
        if cache_key not in self._qc_pipelines_cache:
            old_keys = [k for k in self._qc_pipelines_cache.keys() if k.startswith(f"{adl_param.id}_")]
            for old_key in old_keys:
                del self._qc_pipelines_cache[old_key]
            
            try:
                pipeline = QCConfigConverter.streamfield_to_pipeline(qc_checks)
                self._qc_pipelines_cache[cache_key] = pipeline
                logger.debug(f"Created QC pipeline for parameter {adl_param.name}")
            except Exception as e:
                logger.error(f"Error creating QC pipeline for parameter {adl_param.name}: {e}")
                return QCBits(0), QCStatus.NOT_EVALUATED, []
        
        pipeline = self._qc_pipelines_cache[cache_key]
        
        # Determine history requirements from pipeline
        history_requirements = self._get_pipeline_history_requirements(pipeline)
        
        # Only fetch history if needed
        recent_history = []
        if history_requirements['needed']:
            recent_history = self._get_recent_history_for_qc(
                station_link,
                adl_param,
                obs_time,
                limit=history_requirements['limit']
            )
            
            # Check if we have minimum required history
            if len(recent_history) < history_requirements['min_required']:
                logger.debug(f"Insufficient history for {adl_param.name}: "
                             f"got {len(recent_history)}, need {history_requirements['min_required']}")
        
        # Build QC context
        mock_observation_record = {'observation_time': obs_time}
        context = build_qc_context(mock_observation_record, adl_param, station_link, recent_history)
        
        # Run the QC pipeline
        try:
            pipeline_result = pipeline.run_single(value, context)
        except Exception as e:
            logger.error(f"Error running QC pipeline for {adl_param.name}: {e}")
            return QCBits(0), QCStatus.NOT_EVALUATED, []
        
        qc_bits = QCBits(0)
        qc_messages = []
        
        # Map QC flags to QC bits
        flag_to_bit_mapping = {
            QCFlag.RANGE: QCBits.RANGE,
            QCFlag.STEP: QCBits.STEP,
            QCFlag.PERSISTENCE: QCBits.PERSISTENCE,
            QCFlag.SPIKE: QCBits.SPIKE,
        }
        
        # Set QC bits based on failed flags
        for flag in pipeline_result.flags:
            if flag in flag_to_bit_mapping:
                qc_bits |= flag_to_bit_mapping[flag]
        
        # Determine QC status
        if pipeline_result.passed:
            qc_status = QCStatus.PASS
        else:
            qc_status = QCStatus.SUSPECT
            
            # Create QC messages for failed checks
            failed_validators = pipeline_result.get_failed_validators()
            summary_message = pipeline_result.get_summary_message()
            
            for flag in pipeline_result.flags:
                if flag in flag_to_bit_mapping:
                    qc_messages.append({
                        "check_type": flag_to_bit_mapping[flag],
                        "reason": summary_message,
                    })
        
        logger.debug(f"QC result for {adl_param.name}: passed={pipeline_result.passed}, "
                     f"confidence={pipeline_result.confidence:.2f}, flags={[f.name for f in pipeline_result.flags]}")
        
        return qc_bits, qc_status, qc_messages
    
    def _get_pipeline_history_requirements(self, pipeline) -> Dict[str, Any]:
        """Determine history requirements for entire pipeline"""
        if not pipeline.validators:
            return {'needed': False, 'limit': 0, 'min_required': 0}
        
        needs_history = False
        max_limit = 0
        max_min_required = 0
        
        for validator_config in pipeline.validators:
            if not validator_config.enabled:
                continue
            
            requirements = validator_config.validator.get_history_requirements()
            
            if requirements['needed']:
                needs_history = True
                max_limit = max(max_limit, requirements['limit'])
                max_min_required = max(max_min_required, requirements['min_required'])
        
        return {
            'needed': needs_history,
            'limit': max_limit,
            'min_required': max_min_required
        }
    
    def _get_recent_history_for_qc(self, station_link, adl_param, current_time: datetime, limit: int = 20):
        """Get recent observation history for QC context"""
        from adl.core.models import ObservationRecord
        
        try:
            recent_obs = ObservationRecord.objects.filter(
                station=station_link.station,
                connection=station_link.network_connection,
                parameter=adl_param,
                time__lt=current_time
            ).order_by('-time')[:limit]
            
            return [
                {
                    'value': obs.value,
                    'time': obs.time,
                    'qc_status': obs.qc_status
                }
                for obs in recent_obs
            ]
        except Exception as e:
            logger.warning(f"Error getting recent history for QC: {e}")
            return []


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
