"""
ADL Plugin Registry

This module defines the :class:`Plugin` base class that all ADL data-source
plugins must subclass, along with the :class:`PluginRegistry` singleton used
to register and look up plugins at runtime.

Plugins are Django apps that act as adapters between an upstream data source
(HTTP API, FTP feed, database, serial port, etc.) and ADL's internal
observation store. Each plugin is responsible for fetching raw records for a
station over a time window; ADL handles scheduling, date windowing, timezone
normalization, unit conversion, upserts, and logging.

Processing is optimised for memory efficiency: :meth:`Plugin.get_station_data`
should yield records as a generator, and :meth:`Plugin.save_records` processes
them in configurable chunks rather than loading the full response into memory.
Buffered records are never lost to an interruption: a source that raises
mid-stream has whatever it already yielded persisted before the exception is
re-raised, and a plugin can yield :data:`FLUSH` to persist at its own natural
unit of work (a file, a page) instead of waiting for a chunk to fill.
"""

import time
from datetime import timedelta, datetime
from datetime import timezone as py_tz
from typing import Iterable, List, Dict, Any, Optional, Tuple, Generator

from celery.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as dj_timezone

from .classification import mark_failed, stamp_failure
from .date_utils import make_record_timezone_aware
from .logging import TaskLogger
from .registry import Registry, Instance
from .validators import StationRecordModel


class _FlushMarker:
    """Type of the :data:`FLUSH` sentinel. Never instantiate it yourself."""
    __slots__ = ()

    def __repr__(self):
        return "FLUSH"


#: Sentinel a plugin may ``yield`` from :meth:`Plugin.get_station_data`, in
#: between record dicts, to ask ADL to persist everything buffered so far.
#:
#: Without it, records are written only when :attr:`Plugin.SAVE_CHUNK_SIZE` of
#: them have accumulated or the source is exhausted. For a source whose natural
#: unit is much smaller than that — one file holding one record, one API page
#: holding a handful — that means data downloaded minutes ago is still only in
#: memory, and a plugin has no honest point at which to mark its own source
#: item as done. Yielding ``FLUSH`` after each item persists that item's
#: records before the generator is resumed, so code after the ``yield`` runs
#: knowing the rows are in the database::
#:
#:     for path in files:
#:         yield from self._decode(path)
#:         yield FLUSH
#:         mark_done(path)   # runs after the file's records were upserted
#:
#: A ``FLUSH`` with nothing buffered is a no-op; a plugin that never yields it
#: behaves exactly as before.
FLUSH = _FlushMarker()


class _SaveTally:
    """Running totals over the chunks persisted for one station run.

    Kept as an object rather than three locals so :meth:`Plugin.process_station`
    can read what *was* saved when the save loop is cut short by an exception —
    the counts survive the ``raise`` where a return value would not.
    """
    __slots__ = ("saved", "earliest", "latest", "chunks")

    def __init__(self):
        self.saved = 0
        self.earliest = None
        self.latest = None
        self.chunks = 0

    def add(self, saved_count, chunk_earliest, chunk_latest):
        self.chunks += 1
        self.saved += saved_count
        if chunk_earliest and (self.earliest is None or chunk_earliest < self.earliest):
            self.earliest = chunk_earliest
        if chunk_latest and (self.latest is None or chunk_latest > self.latest):
            self.latest = chunk_latest

    def as_tuple(self):
        return self.saved, self.earliest, self.latest


def _sanitize_sources_count(value):
    """
    Coerce a plugin-reported ``adl_sources_count`` into its stored tri-state.

    Only a non-negative ``int`` is accepted. Anything else — missing, negative,
    float, string, bool — degrades to ``None`` (*did not look*), never to
    ``0``, because ``0`` (*looked, found nothing*) is the fault value and must
    never be manufactured from a malformed report.
    """
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


class Plugin(Instance):
    """
    Base class for all ADL data-source plugins.

    Subclasses must:

    - Set :attr:`type` — a unique string registry key (e.g. ``"adl_tahmo_plugin"``).
    - Set :attr:`label` — a human-readable name shown in the admin UI and logs.
      A blank ``label`` raises :exc:`~django.core.exceptions.ImproperlyConfigured`
      on startup.
    - Implement :meth:`get_station_data`.

    All other methods have working defaults and can be overridden selectively.

    **Minimal subclass example:**

    .. code-block:: python

        from adl.core.registries import Plugin

        class MyPlugin(Plugin):
            type = "my_plugin"
            label = "My Data Source Plugin"

            def get_station_data(self, station_link, start_date=None, end_date=None):
                client = station_link.network_connection.get_api_client()
                yield from client.get_measurements(
                    station_link.station_code,
                    start=start_date,
                    end=end_date,
                )
    """
    label = ""
    
    #: How many raw records :meth:`save_records` buffers before one bulk
    #: upsert. Override on a subclass for a source with a very different
    #: record size; for a source that wants to persist at its own boundaries
    #: (per file, per page) yield :data:`FLUSH` instead of lowering this.
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
        """
        Return the :class:`~adl.core.logging.TaskLogger` for this plugin instance.
    
        Creates a new logger on first call, keyed to :attr:`label`. Subsequent
        calls return the same instance unless :meth:`set_task_context` has been
        called to replace it with a task-scoped logger.
    
        :return: The active task logger.
        :rtype: TaskLogger
        """
        if self._task_logger is None:
            self._task_logger = TaskLogger(plugin_label=self.label)
        return self._task_logger
    
    def set_task_context(self, task_id: str):
        """
        Replace the current logger with one scoped to a specific Celery task ID.
    
        Called automatically by the ADL task runner before :meth:`run_process`
        executes, so that all log entries for a given ingestion run are associated
        with the same task. You do not normally need to call this directly.
    
        :param task_id: The Celery task ID string for the current ingestion run.
        :type task_id: str
        """
        self._task_logger = TaskLogger(task_id=task_id, plugin_label=self.label)
    
    # ---------- URL exposure ----------
    def get_urls(self) -> list:
        """
        Return a list of Django URL patterns to include in the ADL URL configuration.
    
        The default implementation returns an empty list. Override this method if
        your plugin needs to serve views outside the Wagtail admin namespace. For
        views that belong inside the Wagtail admin, use the ``register_admin_urls``
        hook in ``wagtail_hooks.py`` instead.
    
        :return: A list of Django URL patterns.
        :rtype: list
    
        Example:
    
        .. code-block:: python
    
            def get_urls(self):
                from django.urls import path, include
                from . import plugin_urls
                return [
                    path("my-plugin/", include(plugin_urls, namespace=self.type)),
                ]
            """
        
        return []
    
    def after_save_records(self, station_link, station_records, saved_records, qc_fail_results=None) -> None:
        """
        Hook called after each batch of :class:`~adl.core.models.ObservationRecord`
        instances has been upserted for a station.
    
        The default implementation does nothing. Override this method if your plugin
        needs to trigger side effects after data lands in the database — for example,
        sending a notification, updating an external cache, or writing a
        plugin-specific summary log.
    
        :param station_link: The ``StationLink`` instance that was just processed.
        :param station_records: The raw record dicts as returned by
            :meth:`get_station_data` for this station.
        :param saved_records: The ``ObservationRecord`` instances that were upserted.
        :param qc_fail_results: Dict of QC failure messages keyed by UTC ISO
            timestamp string, or ``None`` if no QC checks are configured for this
            parameter.
        """
    
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
        Fetch raw observations for one station over a time window.
    
        This is the only method subclasses **must** implement. ADL calls it with a
        pre-resolved ``[start_date, end_date)`` window and expects back an iterable
        of record dicts that it will normalize, convert, and upsert.
    
        :param station_link: The configured ``StationLink`` subclass instance for
            this station. Provides upstream credentials via
            ``station_link.network_connection``, the upstream station identifier,
            variable mappings, and the station timezone.
        :param start_date: Start of the fetch window, expressed in the station's
            local timezone (aware datetime). Fetch records where
            ``observation_time >= start_date``.
        :type start_date: datetime, optional
        :param end_date: End of the fetch window, expressed in the station's local
            timezone (aware datetime). Fetch records where
            ``observation_time < end_date``.
        :type end_date: datetime, optional
        :return: An iterable (preferably a generator) of record dicts. Each dict
            **must** contain:
    
            - ``"observation_time"`` (:class:`datetime`) — aware datetimes are used
              as-is; naive datetimes are interpreted as station-local time.
    
            And **may** contain any number of source-parameter fields whose keys
            match ``mapping.source_parameter_name`` on the station link's variable
            mappings, for example::
    
                {
                    "observation_time": datetime(2025, 1, 1, 10, 0, tzinfo=utc),
                    "te": 22.4,
                    "rh": 78.0,
                }
    
        :rtype: Iterable[Dict[str, Any]]
        :raises NotImplementedError: If not overridden by the subclass.
    
        .. note::
            Prefer ``yield``-ing records one at a time rather than returning a
            complete list. :meth:`save_records` processes in chunks of
            :attr:`SAVE_CHUNK_SIZE`, so a generator avoids loading the entire
            upstream response into memory — important for large historical backfills.

        .. note::
            **Optional flush marker.** Records are written to the database when
            :attr:`SAVE_CHUNK_SIZE` of them have accumulated, when the iterable
            is exhausted, or when it raises (whatever was buffered is persisted
            before the exception propagates). A generator may also ``yield``
            :data:`FLUSH` between records to persist immediately — after each
            file, page or other source unit — so that code following the
            ``yield`` (marking the unit as done, for instance) runs only once
            its records are in the database::

                for path in matched_files:
                    yield from decode(path)
                    yield FLUSH
                    mark_processed(path)

        .. note::
            **Optional sources-count handover.** A plugin that can count the
            candidate source items it resolved (files matched, API result
            entries, …) may report the number by setting a duck-typed
            attribute on the station link as it lists::

                station_link.adl_sources_count = len(matched_files)

            :meth:`process_station` initialises the attribute to ``None``
            before calling this method and stores it on the run's activity
            log afterwards (``StationLinkActivityLog.sources_count``). The
            value is deliberately tri-state: ``None`` = did not look, ``0`` =
            looked and found nothing, ``n`` = found ``n``. Only a
            non-negative ``int`` is stored; anything else degrades to
            ``None``. This is an attribute convention rather than an API so
            plugins can ship the change before the deployment upgrades core.
    
        .. warning::
            Records with a missing or non-:class:`datetime` ``observation_time``,
            timestamps outside ``[start_date, end_date]``, or future timestamps are
            silently dropped by :meth:`save_records`. No exception is raised.
            """
        raise NotImplementedError
    
    # ---------- Date helpers ----------
    def get_default_end_date(self, station_link) -> datetime:
        """
        Return the default end date for a station's ingestion window.
    
        Computes the station-local "top of the next hour" as a timezone-aware
        datetime. This is used as ``end_date`` for every ingestion run unless
        overridden.
    
        :param station_link: The ``StationLink`` instance whose timezone is used
            to localise the result.
        :return: The top of the next hour in the station's local timezone, as an
            aware datetime.
        :rtype: datetime
    
        Override this method if your data source reports at a different resolution
        — for example, to return the end of the current day for a daily-data source.
        """
        timezone = station_link.timezone
        end_date = dj_timezone.localtime(timezone=timezone)
        end_date = end_date.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return end_date
    
    def get_default_start_date(self, station_link) -> datetime:
        """
        Return the default start date for a station's ingestion window.
    
        Used as the ``start_date`` fallback when no prior observations exist in the
        database and no custom start date is set on the station link. The base
        implementation returns one hour before :meth:`get_default_end_date`.
    
        :param station_link: The ``StationLink`` instance whose timezone is used
            to localise the result.
        :return: One hour before the default end date, in the station's local
            timezone, as an aware datetime.
        :rtype: datetime
    
        Override this method when your source's natural polling window differs from
        one hour. For example, to fall back to the previous 24 hours:
    
        .. code-block:: python
    
            def get_default_start_date(self, station_link):
                return self.get_default_end_date(station_link) - timedelta(days=1)
        """
        end_date = self.get_default_end_date(station_link)
        start_date = end_date - timedelta(hours=1)
        return start_date
    
    def get_start_date_from_db(self, station_link) -> Optional[datetime]:
        """
        Return the latest saved observation timestamp for this station and connection.
    
        Queries :class:`~adl.core.models.ObservationRecord` for the most recent
        ``time`` value matching ``(station, network_connection)``. This is the
        primary mechanism by which ingestion resumes from where it left off after
        a restart or gap.
    
        :param station_link: The ``StationLink`` instance identifying the station
            and connection to query.
        :return: The latest saved observation time as a UTC-aware datetime, or
            ``None`` if no records exist yet for this station and connection.
        :rtype: datetime or None
    
        Override this method when your API uses an inclusive end bound — i.e. it
        returns the record at exactly the timestamp you request — to avoid
        re-fetching the boundary record. For example, to add a one-minute offset:
    
        .. code-block:: python
    
            def get_start_date_from_db(self, station_link):
                start_date = super().get_start_date_from_db(station_link)
                if start_date:
                    start_date += timedelta(minutes=1)
                return start_date
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
        Resolve the ``(start_date, end_date)`` window to pass to
        :meth:`get_station_data`.
    
        You should not normally need to override this method. Override the
        individual helpers (:meth:`get_default_start_date`,
        :meth:`get_default_end_date`, :meth:`get_start_date_from_db`) instead.
    
        ``start_date`` is resolved as follows:
    
        1. The **later** of :meth:`get_start_date_from_db` (the latest saved
           observation — normal incremental ingestion) and
           ``station_link.get_first_collection_date()`` (the collection start
           date configured on the station link). Either may be ``None``, in
           which case the other is used on its own.
        2. :meth:`get_default_start_date` — final fallback when no prior data
           exists and no start date is configured.
    
        The configured start date is therefore a *floor*: ingestion never starts
        before it. On the first run it is the start of the backfill; afterwards,
        moving it forward past the latest saved record makes the next run resume
        from the new date, deliberately skipping the gap (which is not backfilled).
        When that happens an ``INFO`` line is written to the task log. It cannot
        move the window backwards; use ``process_station(initial_start_date=...)``
        for that.
    
        When ``latest=True``, step 1 is skipped and the default start date is
        always used. This mode is used when fetching the most recent data on
        demand rather than resuming normal ingestion.
    
        Both dates are always localised to the station's timezone before being
        returned. If ``start_date`` equals ``end_date`` after resolution, one
        hour is added to ``end_date`` to ensure a non-zero window.
    
        :param station_link: The ``StationLink`` instance to resolve dates for.
        :param latest: If ``True``, skip DB and first-collection-date lookups and
            always use the default start date. Defaults to ``False``.
        :type latest: bool
        :return: A ``(start_date, end_date)`` tuple, both timezone-aware and
            expressed in the station's local timezone.
        :rtype: Tuple[datetime, datetime]
        """
        
        if latest:
            start_date = self.get_default_start_date(station_link)
        else:
            db_start = self.get_start_date_from_db(station_link)
            floor = self._get_station_first_collection_date(station_link)
            
            if db_start and floor and floor > db_start:
                self.get_logger().info(
                    "Collection start date %s for %s is after the latest saved record %s; "
                    "resuming from the start date and skipping the gap.",
                    floor, station_link, db_start,
                )
                start_date = floor
            else:
                start_date = db_start or floor or self.get_default_start_date(station_link)
        
        end_date = self.get_default_end_date(station_link)
        
        if end_date == start_date:
            end_date += timedelta(hours=1)
        
        tz = station_link.timezone
        start_date = dj_timezone.localtime(start_date, timezone=tz)
        end_date = dj_timezone.localtime(end_date, timezone=tz)
        
        return start_date, end_date
    
    # ---------- Iterator utilities ----------
    def _chunk_iterator(self, iterable: Iterable, chunk_size: int) -> Generator[List, None, None]:
        """
        Yield lists of at most ``chunk_size`` records from ``iterable``.

        A chunk is yielded when it is full, when :data:`FLUSH` is encountered
        (the marker itself is consumed, never yielded), and when the source is
        exhausted. If the source raises, whatever is buffered is yielded first
        and the exception is re-raised afterwards — so a soft time limit or a
        connection dropping on item *n+1* does not throw away items *1..n*
        that were already fetched. Only the source's own exceptions are handled
        this way; an exception raised by the consumer while persisting a chunk
        propagates untouched.
        """
        log = self.get_logger()
        chunk = []
        total = 0
        source = iter(iterable)
        interruption = None

        while True:
            try:
                item = next(source)
            except StopIteration:
                break
            except Exception as e:
                # SoftTimeLimitExceeded is an Exception subclass, so the batch
                # soft limit lands here too — with the grace window Celery
                # allows after it, long enough to persist one partial chunk
                interruption = e
                break

            if item is FLUSH:
                if chunk:
                    log.info(f"Flush requested by source: yielding chunk of {len(chunk)} records "
                             f"(total so far: {total})")
                    yield chunk
                    chunk = []
                continue

            chunk.append(item)
            total += 1

            if len(chunk) >= chunk_size:
                log.info(f"Yielding chunk of {len(chunk)} records (total so far: {total})")
                yield chunk
                chunk = []

        if interruption is not None:
            if chunk:
                log.warning(
                    "Source raised %s after %d records; persisting the %d buffered "
                    "records before re-raising",
                    type(interruption).__name__, total, len(chunk),
                )
                yield chunk
            raise interruption

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
            start_date,
            end_date,
            log: TaskLogger
    ) -> Tuple[List[Any], Dict[str, List], Optional[datetime]]:
        """
        Validate one raw record dict and produce unsaved ``ObservationRecord``
        objects for each variable mapping that resolves successfully.
    
        Returns ``([], {}, None)`` for any record that fails validation
        (missing or invalid ``observation_time``, out-of-window timestamp,
        future timestamp). Unit conversion failures on individual mappings are
        also silently skipped.
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
        
        if obs_time < start_date:
            log.warning(
                "Rejected timestamp %s before start_date %s for station %s",
                obs_time, start_date, station.name
            )
            return [], {}, None
        
        if obs_time > end_date:
            log.warning(
                "Rejected timestamp %s after end_date %s for station %s",
                obs_time, end_date, station.name
            )
            return [], {}, None
        
        now = dj_timezone.now()
        if obs_time > now:
            log.warning(
                "Rejected futuristic timestamp %s for station %s (now=%s)",
                obs_time, station.name, now
            )
            
            return [], {}, None
        
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
            start_date,
            end_date,
            log: TaskLogger
    ) -> Tuple[int, Optional[datetime], Optional[datetime]]:
        """
        Process and bulk-upsert one chunk of raw records.
    
        Deduplicates by ``(utc_time, parameter_id)`` before calling
        ``bulk_create(update_conflicts=True)``, so re-fetching an overlapping
        window is safe. Returns ``(saved_count, earliest_time, latest_time)``
        for the chunk.
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
                record, station_link, station, variable_mappings, tz, start_date, end_date, log
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

        try:
            self.after_save_records(station_link, chunk_records, list(saved_records))
        except Exception:
            log.exception("after_save_records raised for station %s", station_link.station)

        return len(saved_records), chunk_earliest, chunk_latest
    
    def save_records(
            self,
            station_link,
            station_records: Iterable[Dict[str, Any]],
            start_date,
            end_date,
            chunk_size: Optional[int] = None
    ) -> Tuple[int, Optional[datetime], Optional[datetime]]:
        """
        Normalize and upsert raw observation records into
        :class:`~adl.core.models.ObservationRecord`.
    
        Processes ``station_records`` in chunks of :attr:`SAVE_CHUNK_SIZE` (or
        ``chunk_size`` if provided) to keep memory usage bounded — works correctly
        with both lists and generators.
    
        For each record the method:
    
        1. Validates and normalizes ``observation_time`` to a timezone-aware
           station-local datetime. Records with a missing, non-:class:`datetime`,
           out-of-window, or future timestamp are silently dropped.
        2. Iterates the station link's variable mappings and looks up
           ``record[mapping.source_parameter_name]`` for each one.
        3. Converts the value from ``mapping.source_parameter_unit`` to the ADL
           parameter's canonical unit if they differ.
        4. Runs any configured QC checks against the value.
        5. Upserts an ``ObservationRecord`` row keyed on
           ``(time, station, connection, parameter)``, updating ``value``,
           ``is_daily``, ``qc_status``, ``qc_bits``, and ``qc_version`` on
           conflict.
    
        You do not normally need to override or call this method directly. It is
        called automatically by :meth:`process_station`.
    
        :param station_link: The ``StationLink`` instance whose variable mappings
            and timezone are used for normalization.
        :param station_records: An iterable (list or generator) of raw record dicts
            as returned by :meth:`get_station_data`.
        :param start_date: The inclusive start of the accepted time window. Records
            before this are silently dropped.
        :type start_date: datetime
        :param end_date: The inclusive end of the accepted time window. Records
            after this are silently dropped.
        :type end_date: datetime
        :param chunk_size: Number of records to process per database batch.
            Defaults to :attr:`SAVE_CHUNK_SIZE`.
        :type chunk_size: int, optional
        :return: A three-tuple of ``(total_saved, earliest_time, latest_time)``
            where ``total_saved`` is the number of rows upserted, and
            ``earliest_time`` / ``latest_time`` are the observation timestamps of
            the first and last saved records, or ``None`` if no records were saved.
        :rtype: Tuple[int, Optional[datetime], Optional[datetime]]
        """
        
        tally = _SaveTally()
        for chunk_result in self._iter_save_records(
                station_link, station_records, start_date, end_date, chunk_size
        ):
            tally.add(*chunk_result)
        return tally.as_tuple()

    def _iter_save_records(
            self,
            station_link,
            station_records: Iterable[Dict[str, Any]],
            start_date,
            end_date,
            chunk_size: Optional[int] = None,
    ) -> Generator[Tuple[int, Optional[datetime], Optional[datetime]], None, None]:
        """
        The chunk-by-chunk engine behind :meth:`save_records`.

        Yields ``(saved_count, earliest_time, latest_time)`` for each chunk
        *after* it has been upserted, so a caller accumulating the results
        holds an accurate total at every point — including the moment the
        source raises and the exception comes out of this generator. That is
        what lets :meth:`process_station` record how much *was* saved on a
        run that then failed, instead of reporting zero.

        Chunk boundaries are :attr:`SAVE_CHUNK_SIZE` records, a :data:`FLUSH`
        yielded by the source, exhaustion, or an interruption — see
        :meth:`_chunk_iterator`.
        """
        log = self.get_logger()

        station = station_link.station
        variable_mappings = list(station_link.get_variable_mappings() or [])

        if not variable_mappings:
            log.warning("No variable mappings for station %s.", station.name)
            return

        chunk_size = chunk_size or self.SAVE_CHUNK_SIZE
        tally = _SaveTally()
        exhausted = False

        try:
            # Process in chunks - works with both generators and lists
            for chunk in self._chunk_iterator(station_records, chunk_size):
                chunk_result = self._save_chunk(
                    station_link, chunk, variable_mappings, start_date, end_date, log
                )
                tally.add(*chunk_result)
                log.debug(
                    "Processed chunk %d for station %s: %d records saved",
                    tally.chunks, station.name, chunk_result[0]
                )
                yield chunk_result
            exhausted = True
        finally:
            # Runs on clean exhaustion and on the re-raise out of
            # _chunk_iterator alike, so a run that saved something always
            # gets its summary line. "No valid records" is only claimed
            # when the source was actually read to the end — a source that
            # failed before yielding anything is reported by the caller.
            if tally.saved:
                log.info(
                    "Saved %d total records for station %s in %d chunks",
                    tally.saved, station.name, tally.chunks
                )
            elif exhausted:
                log.warning("No valid observation records for station %s.", station.name)
    
    # ---------- Orchestration ----------
    def process_station(self, station_link, initial_start_date=None, initial_end_date=None,
                        bypass_lock=False) -> int:
        """
        Run the full ingestion pipeline for a single station link.

        Acquires the per-station ingestion lock, resolves the date window,
        calls :meth:`get_station_data`, passes the results to
        :meth:`save_records`, and writes a
        :class:`~adl.monitoring.models.StationLinkActivityLog` entry regardless
        of outcome. Any exception raised during fetching or saving is caught,
        logged, and recorded on the activity log without re-raising, so that a
        failure on one station does not abort the rest of the connection's run.
        The one exception is :exc:`~celery.exceptions.SoftTimeLimitExceeded`,
        which is re-raised after the activity log is finalised so the batch
        task's time limit actually stops the batch.

        The lock lives here — rather than in the batch task — so every entry
        path (scheduled batch, manual ``collect_data``, shell invocation) is
        covered, and so a collision can write a visible ``SKIPPED`` activity
        row instead of vanishing into a worker log line. The lock carries a
        TTL derived from the connection's batch soft limit — see
        :func:`~adl.core.tasks.ingest_batch_budget_seconds` — so a killed worker
        can never leave a station locked permanently, while a station that
        legitimately runs for the whole batch budget keeps its lock throughout.

        Called by :meth:`run_process` for each enabled station link. You do not
        normally need to call or override this method directly.

        :param station_link: The ``StationLink`` instance to process.
        :param initial_start_date: Override the resolved ``start_date`` with this
            value if provided. Useful for manual or backfill invocations.
        :type initial_start_date: datetime, optional
        :param initial_end_date: Override the resolved ``end_date`` with this
            value if provided.
        :type initial_end_date: datetime, optional
        :param bypass_lock: Skip lock acquisition entirely. Only for deliberate
            backfills, where running alongside a scheduled pull is intended.
        :type bypass_lock: bool, optional
        :return: The number of ``ObservationRecord`` rows upserted, or ``0`` if
            no data was available, the station was locked, or an error occurred.
        :rtype: int
        """
        from django.core.cache import cache
        from adl.monitoring.models import StationLinkActivityLog
        from adl.core.tasks import (
            ingest_batch_budget_seconds,
            ingest_station_lock_key,
        )
        log = self.get_logger()

        lock_key = ingest_station_lock_key(station_link.id)
        if not bypass_lock:
            lock_ttl = ingest_batch_budget_seconds(station_link.network_connection)
            if not cache.add(lock_key, "locked", timeout=lock_ttl):
                log.warning("Station link %s is still processing. Skipping...", station_link)
                StationLinkActivityLog.objects.create(
                    time=dj_timezone.now(),
                    station_link=station_link,
                    direction='pull',
                    success=True,
                    status=StationLinkActivityLog.ActivityStatus.SKIPPED,
                    message="Skipped — previous ingestion still running",
                )
                return 0

        start = time.monotonic()
        activity_log = StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=station_link,
            direction='pull',
        )

        # Accumulated chunk by chunk, so the numbers survive an exception out
        # of the save loop and the terminal activity log can carry them
        tally = _SaveTally()

        # Duck-typed handover: the plugin may set this while listing its
        # source, and the terminal log records it. Re-initialised every run
        # so a value left by a previous run on a reused instance cannot be
        # recorded as if this run had reported it.
        station_link.adl_sources_count = None

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
                # Converged with the empty-iterable case: both fall through to
                # the normal terminal path below, so the activity log always
                # reaches COMPLETED instead of resting at STARTED.
                station_records = []

            # Chunked save - handles generators efficiently. Consumed chunk
            # by chunk (rather than through save_records) so that if the
            # source raises part-way, the tally still holds what was
            # persisted before the exception reaches the handlers below.
            for chunk_result in self._iter_save_records(
                    station_link, station_records, start_date, end_date
            ):
                tally.add(*chunk_result)
            
            if tally.saved == 0:
                log.info("No records saved for %s.", station_link)
                activity_log.status = StationLinkActivityLog.ActivityStatus.COMPLETED
                activity_log.success = True
                activity_log.message = "No new records to save."
            else:
                log.info(
                    "Saved %d records for %s from %s to %s.",
                    tally.saved, station_link, tally.earliest, tally.latest
                )
                activity_log.status = StationLinkActivityLog.ActivityStatus.COMPLETED
                activity_log.success = True
                activity_log.message = f"Processed {tally.saved} records."
        
        except SoftTimeLimitExceeded as e:
            # Re-raised so the batch task's soft limit actually stops the
            # batch — swallowed with the generic errors below, the limit
            # would be inert and the worker would run on to the hard kill
            activity_log.success = False
            activity_log.message = "Ingestion timed out (batch soft time limit exceeded)"
            if tally.saved:
                activity_log.message += f"; {tally.saved} records saved before the cut-off"
            activity_log.status = StationLinkActivityLog.ActivityStatus.FAILED
            stamp_failure(activity_log, e)
            log.error("Ingestion for station %s timed out (%d records saved before the cut-off)",
                      station_link, tally.saved)
            raise
        except Exception as e:
            error_msg = mark_failed(activity_log, e)
            log.error("Error processing station %s: %s (%d records saved before the failure)",
                      station_link, error_msg, tally.saved)
        finally:
            activity_log.duration_ms = (time.monotonic() - start) * 1000
            activity_log.records_count = tally.saved
            if tally.saved:
                # Set on every terminal path, not only the clean one: a run
                # cut short still saved a real range, and the log should say so
                activity_log.obs_start_time = tally.earliest
                activity_log.obs_end_time = tally.latest
            activity_log.sources_count = _sanitize_sources_count(
                getattr(station_link, "adl_sources_count", None)
            )
            activity_log.save()
            if not bypass_lock:
                cache.delete(lock_key)

        return tally.saved
    
    def run_process(self, network_connection, initial_start_date=None) -> Dict[int, int]:
        """
        Run the ingestion pipeline for all enabled station links on a connection.
    
        Iterates ``network_connection.station_links.all()``, skips any link where
        ``enabled`` is ``False``, and calls :meth:`process_station` for each
        remaining link. This is the entry point called by the Celery beat task on
        the configured schedule.
    
        :param network_connection: The ``NetworkConnection`` instance whose station
            links should be processed.
        :param initial_start_date: If provided, passed through to every
            :meth:`process_station` call as ``initial_start_date``, overriding the
            normal DB-resume logic for all stations. Useful for bulk backfills.
        :type initial_start_date: datetime, optional
        :return: A dict mapping each processed ``station.id`` to the number of
            ``ObservationRecord`` rows upserted for that station.
        :rtype: Dict[int, int]
        """
        
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
        """
        Run the configured QC pipeline against a single observation value.
    
        Looks up the QC checks from ``variable_mapping.qc_checks`` if present,
        falling back to ``adl_param.qc_checks``. If no checks are configured,
        returns immediately with a ``NOT_EVALUATED`` status.
    
        QC pipelines are cached per ``(parameter_id, modified_at)`` to avoid
        rebuilding them on every record. The cache is invalidated automatically
        when a parameter's ``modified_at`` timestamp changes.
    
        Called internally by :meth:`save_records` for each mapping row. You do
        not normally need to call this method directly.
    
        :param value: The converted observation value to check (in the ADL
            canonical unit for ``adl_param``).
        :type value: float
        :param variable_mapping: The variable mapping instance for this
            parameter, used to look up per-mapping QC overrides.
        :param adl_param: The :class:`~adl.core.models.DataParameter` instance,
            used as the fallback QC check source and for logging.
        :param station_link: The ``StationLink`` instance, passed to the QC
            context builder for station-level metadata.
        :param obs_time: The timezone-aware observation timestamp, used to fetch
            recent history for checks that require it (e.g. step, persistence).
        :type obs_time: datetime
        :return: A three-tuple of ``(qc_bits, qc_status, qc_messages)`` where
            ``qc_bits`` is a :class:`~adl.core.models.QCBits` flag value,
            ``qc_status`` is a :class:`~adl.core.models.QCStatus` choice, and
            ``qc_messages`` is a list of failure message dicts (empty on pass).
        :rtype: Tuple[QCBits, QCStatus, list]
        """
        
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
        """
        Inspect all enabled validators in ``pipeline`` and return the aggregate
        history requirements as ``{'needed': bool, 'limit': int, 'min_required': int}``.
    
        Used to avoid fetching recent observation history when no validator
        in the pipeline actually needs it.
        """
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
        """
        Return up to ``limit`` recent ``ObservationRecord`` values for
        ``(station, connection, parameter)`` strictly before ``current_time``,
        ordered newest-first.
    
        Returns an empty list on any query error so that a history-fetch failure
        never aborts the QC check for the current record.
        """
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
