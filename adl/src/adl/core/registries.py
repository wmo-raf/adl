"""
ADL Plugin Registry - Optimized for Memory Efficiency

This module provides generator-based processing to handle large datasets
without loading everything into memory at once.
"""

import time
from datetime import timedelta, datetime
from datetime import timezone as py_tz
from typing import Iterable, List, Dict, Any, Optional, Tuple, Generator

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as dj_timezone

from .date_utils import make_record_timezone_aware
from .logging import TaskLogger
from .registry import Registry, Instance
from .validators import StationRecordModel


class Plugin(Instance):
    """
    Base class for ADL data-source plugins - Optimized for memory efficiency.

    Child plugins must:
      - set `label` (human-readable)
      - implement `get_station_data(station_link, start_date, end_date)`

    Contract for `get_station_data`:
      - Input dates are timezone-aware (station timezone) or None.
      - Return/yield an iterable of records. Each record MUST contain:
          - "observation_time": datetime (aware or naive interpreted as station tz)
        And MAY contain any number of source-parameter fields whose names match
        StationVariableMapping.source_parameter_name.
        
    OPTIMIZATION: get_station_data should yield records (generator) rather than
    returning a complete list to minimize memory usage.
    """
    label = ""
    
    # Configurable chunk size for batch processing
    SAVE_CHUNK_SIZE = 500
    
    # ---------- Lifecycle ----------
    def __init__(self):
        super().__init__()
        if not self.label:
            raise ImproperlyConfigured("The label of a plugin must be set.")
        
        # Initialize QC pipeline cache
        self._qc_pipelines_cache = {}
        
        self._task_logger = None
    
    def get_logger(self) -> TaskLogger:
        """Get or create task logger"""
        if self._task_logger is None:
            self._task_logger = TaskLogger(plugin_label=self.label)
        return self._task_logger
    
    def set_task_context(self, task_id: str):
        """Set the current task context for logging"""
        self._task_logger = TaskLogger(task_id=task_id, plugin_label=self.label)
    
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
        
        OPTIMIZATION: Should yield records one at a time (generator) rather than
        returning a complete list to minimize memory usage.
        """
        raise NotImplementedError
    
    # ---------- Date helpers ----------
    def get_default_end_date(self, station_link) -> datetime:
        """
        Station-local 'top of next hour' as an aware datetime.
        """
        timezone = station_link.timezone
        end_date = dj_timezone.localtime(timezone=timezone)
        end_date = end_date.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return end_date
    
    def get_default_start_date(self, station_link) -> datetime:
        """
        One hour window ending at default_end_date.
        """
        end_date = self.get_default_end_date(station_link)
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
        
        tz = station_link.timezone
        start_date = dj_timezone.localtime(start_date, timezone=tz)
        end_date = dj_timezone.localtime(end_date, timezone=tz)
        
        return start_date, end_date
    
    # ---------- Iterator utilities ----------
    def _chunk_iterator(self, iterable: Iterable, chunk_size: int) -> Generator[List, None, None]:
        log = self.get_logger()
        chunk = []
        total = 0
        
        for item in iterable:
            chunk.append(item)
            total += 1
            
            if len(chunk) >= chunk_size:
                log.info(f"Yielding chunk of {len(chunk)} records (total so far: {total})")
                yield chunk
                chunk = []
        
        if chunk:
            log.info(f"Yielding final chunk of {len(chunk)} records (total: {total})")
            yield chunk
    
    # ---------- Persistence (Chunked) ----------
    
    def _process_single_record(
            self,
            record: Dict[str, Any],
            station_link,
            station,
            variable_mappings: List,
            tz,
            log: TaskLogger
    ) -> Tuple[List[Any], Dict[str, List], Optional[datetime]]:
        """
        Process a single raw record into ObservationRecord objects.
        
        Returns:
            - List of ObservationRecord objects (not yet saved)
            - Dict of QC results keyed by time+param
            - The observation time (for tracking earliest/latest)
        """
        from adl.core.models import ObservationRecord
        
        observation_records = []
        qc_results = {}
        
        try:
            rec = StationRecordModel(
                observation_time=record.get("observation_time"),
                values={k: v for k, v in record.items() if k != "observation_time"}
            )
        except Exception as e:
            log.warning("Bad record for station %s: %s", station.name, e)
            return [], {}, None
        
        obs_time = rec.observation_time
        
        if not obs_time:
            log.warning("Missing observation_time for station %s.", station.name)
            return [], {}, None
        
        if not isinstance(obs_time, datetime):
            log.error(
                "observation_time for station %s must be datetime, got %s: %r",
                station.name, type(obs_time), obs_time
            )
            return [], {}, None
        
        # Normalize to aware station-local time
        obs_time = make_record_timezone_aware(obs_time, tz)
        
        for mapping in variable_mappings:
            adl_param = getattr(mapping, "adl_parameter", None)
            src_name = getattr(mapping, "source_parameter_name", None)
            src_unit = getattr(mapping, "source_parameter_unit", None)
            
            if not (adl_param and src_name and src_unit):
                continue
            
            src_name = str(src_name)
            
            if src_name not in rec.values:
                continue
            
            value = rec.values.get(src_name)
            
            if value is None or not isinstance(value, (int, float)):
                continue
            
            # Unit conversion
            try:
                if adl_param.unit != src_unit:
                    value = adl_param.convert_value_from_units(value, src_unit)
            except Exception as e:
                log.warning(
                    "Unit conversion failed for %s (%s→%s) on station %s: %s",
                    adl_param.name, src_unit, adl_param.unit, station.name, e
                )
                continue
            
            time_key = dj_timezone.localtime(obs_time, timezone=py_tz.utc).isoformat()
            utc_obs_key_with_param = f"{time_key}_{adl_param.id}"
            
            # QC checks
            qc_bits, qc_status, qc_messages = self.perform_qc_checks_with_pipeline(
                value=value,
                variable_mapping=mapping,
                adl_param=adl_param,
                station_link=station_link,
                obs_time=obs_time
            )
            
            if qc_messages:
                if utc_obs_key_with_param not in qc_results:
                    qc_results[utc_obs_key_with_param] = []
                qc_results[utc_obs_key_with_param].extend(qc_messages)
            
            observation_records.append(ObservationRecord(
                station=station,
                parameter=adl_param,
                time=obs_time,
                value=value,
                connection=station_link.network_connection,
                is_daily=station_link.network_connection.is_daily_data,
                qc_status=qc_status,
                qc_bits=int(qc_bits),
                qc_version=1,
            ))
        
        return observation_records, qc_results, obs_time
    
    def _save_chunk(
            self,
            station_link,
            chunk_records: List[Dict[str, Any]],
            variable_mappings: List,
            log: TaskLogger
    ) -> Tuple[int, Optional[datetime], Optional[datetime]]:
        """
        Process and save a chunk of records.
        
        Returns:
            - Number of saved records
            - Earliest observation time in chunk
            - Latest observation time in chunk
        """
        from adl.core.models import ObservationRecord
        
        station = station_link.station
        tz = station_link.timezone
        
        all_observation_records = {}  # Dedupe by time+param
        all_qc_results = {}
        chunk_earliest = None
        chunk_latest = None
        
        for record in chunk_records:
            obs_records, qc_results, obs_time = self._process_single_record(
                record, station_link, station, variable_mappings, tz, log
            )
            
            if obs_time:
                if chunk_earliest is None or obs_time < chunk_earliest:
                    chunk_earliest = obs_time
                if chunk_latest is None or obs_time > chunk_latest:
                    chunk_latest = obs_time
            
            # Merge into chunk collections (dedupe)
            for obs_record in obs_records:
                time_key = dj_timezone.localtime(obs_record.time, timezone=py_tz.utc).isoformat()
                key = f"{time_key}_{obs_record.parameter_id}"
                all_observation_records[key] = obs_record
            
            all_qc_results.update(qc_results)
        
        if not all_observation_records:
            return 0, chunk_earliest, chunk_latest
        
        observation_records_list = list(all_observation_records.values())
        
        saved_records = ObservationRecord.objects.bulk_create(
            observation_records_list,
            update_conflicts=True,
            update_fields=["value", "is_daily", "qc_status", "qc_bits", "qc_version"],
            unique_fields=["time", "station", "connection", "parameter"],
            batch_size=500  # Smaller batch for bulk_create itself
        )
        
        if saved_records and all_qc_results:
            self._create_qc_messages(saved_records, all_qc_results)
        
        return len(saved_records), chunk_earliest, chunk_latest
    
    def save_records(
            self,
            station_link,
            station_records: Iterable[Dict[str, Any]],
            chunk_size: Optional[int] = None
    ) -> Tuple[int, Optional[datetime], Optional[datetime]]:
        """
        Normalize and upsert observations into ObservationRecord using chunked processing.
        
        This method processes records in chunks to minimize memory usage.
        
        Args:
            station_link: The station link configuration
            station_records: Iterable (can be generator) of raw records
            chunk_size: Override default chunk size (self.SAVE_CHUNK_SIZE)
        
        Returns:
            Tuple of (total_saved_count, earliest_time, latest_time)
        """
        log = self.get_logger()
        
        station = station_link.station
        variable_mappings = list(station_link.get_variable_mappings() or [])
        
        if not variable_mappings:
            log.warning("No variable mappings for station %s.", station.name)
            return 0, None, None
        
        chunk_size = chunk_size or self.SAVE_CHUNK_SIZE
        
        total_saved = 0
        overall_earliest = None
        overall_latest = None
        chunk_count = 0
        
        # Process in chunks - works with both generators and lists
        for chunk in self._chunk_iterator(station_records, chunk_size):
            chunk_count += 1
            
            saved_count, chunk_earliest, chunk_latest = self._save_chunk(
                station_link, chunk, variable_mappings, log
            )
            
            total_saved += saved_count
            
            # Track overall time range
            if chunk_earliest:
                if overall_earliest is None or chunk_earliest < overall_earliest:
                    overall_earliest = chunk_earliest
            if chunk_latest:
                if overall_latest is None or chunk_latest > overall_latest:
                    overall_latest = chunk_latest
            
            log.debug(
                "Processed chunk %d for station %s: %d records saved",
                chunk_count, station.name, saved_count
            )
        
        if total_saved == 0:
            log.warning("No valid observation records for station %s.", station.name)
        else:
            log.info(
                "Saved %d total records for station %s in %d chunks",
                total_saved, station.name, chunk_count
            )
        
        return total_saved, overall_earliest, overall_latest
    
    # ---------- Orchestration ----------
    def process_station(self, station_link, initial_start_date=None, initial_end_date=None) -> int:
        """
        Process a single station - optimized for memory efficiency.
        
        Key optimization: Uses generator-based data fetching and chunked saving
        to avoid loading all records into memory at once.
        """
        from adl.monitoring.models import StationLinkActivityLog
        log = self.get_logger()
        
        start = time.monotonic()
        activity_log = StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=station_link,
            direction='pull',
        )
        
        saved_obs_records_count = 0
        earliest_time = None
        latest_time = None
        
        try:
            start_date, end_date = self.get_dates_for_station(station_link)
            
            if initial_start_date:
                start_date = initial_start_date
            if initial_end_date:
                end_date = initial_end_date
            
            log.info("Fetching %s from %s to %s.", station_link, start_date, end_date)
            
            # Get station data - should be a generator for memory efficiency
            station_records = self.get_station_data(
                station_link,
                start_date=start_date,
                end_date=end_date
            )
            
            if station_records is None:
                log.info("No new data for %s.", station_link)
                return 0
            
            # Use chunked save - handles generators efficiently
            saved_obs_records_count, earliest_time, latest_time = self.save_records(
                station_link,
                station_records
            )
            
            if saved_obs_records_count == 0:
                log.info("No records saved for %s.", station_link)
                activity_log.status = StationLinkActivityLog.ActivityStatus.COMPLETED
                activity_log.success = True
                activity_log.message = "No new records to save."
            else:
                log.info(
                    "Saved %d records for %s from %s to %s.",
                    saved_obs_records_count, station_link, earliest_time, latest_time
                )
                activity_log.status = StationLinkActivityLog.ActivityStatus.COMPLETED
                activity_log.success = True
                activity_log.obs_start_time = earliest_time
                activity_log.obs_end_time = latest_time
                activity_log.message = f"Processed {saved_obs_records_count} records."
        
        except Exception as e:
            error_msg = str(e)
            activity_log.success = False
            activity_log.message = error_msg
            activity_log.status = StationLinkActivityLog.ActivityStatus.FAILED
            log.error("Error processing station %s: %s", station_link, error_msg)
        finally:
            activity_log.duration_ms = (time.monotonic() - start) * 1000
            activity_log.records_count = saved_obs_records_count
            activity_log.save()
        
        return saved_obs_records_count
    
    def run_process(self, network_connection, initial_start_date=None) -> Dict[int, int]:
        log = self.get_logger()
        
        station_links = network_connection.station_links.all()
        results: Dict[int, int] = {}
        
        log.info("Processing %d station links for %s.", len(station_links), network_connection.name)
        
        for station_link in station_links:
            if not station_link.enabled:
                log.info("Skipping disabled station link: %s", station_link)
                continue
            
            results[station_link.station.id] = self.process_station(
                station_link,
                initial_start_date=initial_start_date
            )
        
        return results
    
    # ---------- QC Methods (unchanged) ----------
    def perform_qc_checks_with_pipeline(self, value: float, variable_mapping, adl_param, station_link,
                                        obs_time: datetime):
        """Perform QC checks using the QCPipeline system with optimized history fetching"""
        from adl.core.models import QCBits, QCStatus
        from adl.core.qc.config import QCConfigConverter, build_qc_context
        from adl.core.qc.validators import QCFlag
        
        log = self.get_logger()
        
        if hasattr(variable_mapping, "qc_checks"):
            qc_checks = variable_mapping.qc_checks
        else:
            qc_checks = adl_param.qc_checks
        
        if not qc_checks:
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
                log.debug(f"Created QC pipeline for parameter {adl_param.name}")
            except Exception as e:
                log.error(f"Error creating QC pipeline for parameter {adl_param.name}: {e}")
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
                log.debug(f"Insufficient history for {adl_param.name}: "
                          f"got {len(recent_history)}, need {history_requirements['min_required']}")
        
        # Build QC context
        mock_observation_record = {'observation_time': obs_time}
        context = build_qc_context(mock_observation_record, adl_param, station_link, recent_history)
        
        # Run the QC pipeline
        try:
            pipeline_result = pipeline.run_single(value, context)
        except Exception as e:
            log.error(f"Error running QC pipeline for {adl_param.name}: {e}")
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
        
        log.debug(f"QC result for {adl_param.name}: passed={pipeline_result.passed}, "
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
        
        log = self.get_logger()
        
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
            log.warning(f"Error getting recent history for QC: {e}")
            return []


class PluginRegistry(Registry):
    """
    Plugin registry for ADL data-source plugins.
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
        return [(k, v.label) for k, v in self.registry.items()]


custom_unit_context_registry = CustomUnitContextRegistry()


class ViewSetRegistry(Registry):
    def __init__(self, name, allow_instance_override=True):
        self.name = name
        super().__init__(allow_instance_override=allow_instance_override)


dispatch_channel_viewset_registry = ViewSetRegistry(name="dispatch_channel_viewset_registry")
connection_viewset_registry = ViewSetRegistry(name="connection_viewset_registry")
station_link_viewset_registry = ViewSetRegistry(name="station_link_viewset_registry")
