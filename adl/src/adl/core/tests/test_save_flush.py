"""
Persistence must not depend on the source finishing.

Records are buffered up to ``SAVE_CHUNK_SIZE`` before a bulk upsert. For a
source that yields one record per slow network fetch, that used to mean
minutes of downloaded data lived only in memory — and a soft time limit or a
dropped connection on the next fetch threw all of it away, while the plugin
had already marked its files as processed. These tests pin the two guarantees
that close that gap: buffered records are persisted when the source raises,
and a source can yield ``FLUSH`` to persist at its own boundaries.
"""

from datetime import datetime, timedelta, timezone as py_tz
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TestCase

from adl.core.models import ObservationRecord
from adl.core.registries import FLUSH
from adl.monitoring.models import StationLinkActivityLog
from .factories import (
    StationLinkFactory,
    DataParameterFactory,
    KelvinUnitFactory,
    CelsiusUnitFactory,
)
from .helpers import make_test_plugin, make_mapping


class SaveFlushTestCase(TestCase):
    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()
        unit_c = CelsiusUnitFactory()
        self.unit_k = KelvinUnitFactory()
        self.param_temp = DataParameterFactory(name="air_temperature", unit=unit_c)
        mapping = make_mapping(self.param_temp, self.unit_k)
        self.link.get_variable_mappings = lambda: [mapping]

        self.window_start = datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc)
        self.window_end = datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc)

    def record(self, minutes):
        return {
            "observation_time": self.window_start + timedelta(minutes=minutes),
            "temp_K": 293.15 + minutes,
        }

    def save(self, source, **kwargs):
        return self.plugin.save_records(
            self.link, source, self.window_start, self.window_end, **kwargs
        )


class InterruptionFlushTests(SaveFlushTestCase):
    def test_records_yielded_before_the_source_raises_are_persisted(self):
        def source():
            yield self.record(1)
            yield self.record(2)
            yield self.record(3)
            raise ConnectionError("server went away on file 4")

        with self.assertRaises(ConnectionError):
            self.save(source())

        self.assertEqual(ObservationRecord.objects.count(), 3)

    def test_soft_time_limit_is_treated_as_an_interruption(self):
        # Celery's soft limit is an Exception subclass and fires wherever the
        # worker happens to be — usually inside the plugin's next fetch
        def source():
            yield self.record(1)
            raise SoftTimeLimitExceeded()

        with self.assertRaises(SoftTimeLimitExceeded):
            self.save(source())

        self.assertEqual(ObservationRecord.objects.count(), 1)

    def test_a_full_chunk_boundary_and_a_partial_tail_both_survive(self):
        def source():
            for i in range(1, 6):
                yield self.record(i)
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.save(source(), chunk_size=2)

        # 2 + 2 flushed on size, the trailing 1 flushed on interruption
        self.assertEqual(ObservationRecord.objects.count(), 5)

    def test_the_original_exception_is_the_one_re_raised(self):
        marker = ValueError("this exact instance")

        def source():
            yield self.record(1)
            raise marker

        with self.assertRaises(ValueError) as ctx:
            self.save(source())
        self.assertIs(ctx.exception, marker)

    def test_a_source_that_raises_before_yielding_persists_nothing_and_re_raises(self):
        def source():
            raise ConnectionError("cannot connect")
            yield  # noqa: unreachable — makes this a generator

        with self.assertRaises(ConnectionError):
            self.save(source())
        self.assertEqual(ObservationRecord.objects.count(), 0)

    def test_persistence_failure_during_a_chunk_is_not_masked(self):
        # An exception raised by the *consumer* (the upsert itself) must
        # propagate as-is; only the source's exceptions get the flush-first
        # treatment
        def source():
            yield self.record(1)

        with patch.object(type(self.plugin), "_save_chunk", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.save(source())


class FlushMarkerTests(SaveFlushTestCase):
    def test_flush_persists_buffered_records_before_the_generator_resumes(self):
        seen_after_flush = []

        def source():
            yield self.record(1)
            yield FLUSH
            # Runs only after core has consumed FLUSH — i.e. after the upsert
            seen_after_flush.append(ObservationRecord.objects.count())
            yield self.record(2)

        total, _, _ = self.save(source())

        self.assertEqual(total, 2)
        self.assertEqual(seen_after_flush, [1])

    def test_flush_with_nothing_buffered_is_a_no_op(self):
        def source():
            yield FLUSH
            yield FLUSH
            yield self.record(1)
            yield FLUSH
            yield FLUSH

        total, _, _ = self.save(source())
        self.assertEqual(total, 1)
        self.assertEqual(ObservationRecord.objects.count(), 1)

    def test_flush_is_not_counted_as_a_record(self):
        def source():
            yield self.record(1)
            yield FLUSH
            yield self.record(2)
            yield FLUSH

        total, earliest, latest = self.save(source())
        self.assertEqual(total, 2)
        self.assertEqual(earliest, self.window_start + timedelta(minutes=1))
        self.assertEqual(latest, self.window_start + timedelta(minutes=2))

    def test_flush_works_from_a_plain_list_too(self):
        total, _, _ = self.save([self.record(1), FLUSH, self.record(2)])
        self.assertEqual(total, 2)


class ProcessStationPartialSaveTests(SaveFlushTestCase):
    """The activity log for a run that failed part-way must carry what *was*
    saved, not zero — otherwise the operator sees FAILED / 0 records next to
    source files marked as processed and cannot tell whether data landed."""

    def setUp(self):
        super().setUp()
        patcher = patch.object(
            type(self.plugin), "get_dates_for_station",
            return_value=(self.window_start, self.window_end),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failed_run_records_partial_count_and_range(self):
        def fetch(station_link, start_date=None, end_date=None):
            yield self.record(1)
            yield self.record(2)
            raise ConnectionError("lost the server")

        with patch.object(self.plugin, "get_station_data", side_effect=fetch):
            returned = self.plugin.process_station(self.link, bypass_lock=True)

        self.assertEqual(returned, 2)
        self.assertEqual(ObservationRecord.objects.count(), 2)
        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(log.records_count, 2)
        self.assertEqual(log.obs_start_time, self.window_start + timedelta(minutes=1))
        self.assertEqual(log.obs_end_time, self.window_start + timedelta(minutes=2))
        self.assertIn("lost the server", log.message)

    def test_soft_time_limit_run_records_partial_count_and_re_raises(self):
        def fetch(station_link, start_date=None, end_date=None):
            yield self.record(1)
            raise SoftTimeLimitExceeded()

        with patch.object(self.plugin, "get_station_data", side_effect=fetch):
            with self.assertRaises(SoftTimeLimitExceeded):
                self.plugin.process_station(self.link, bypass_lock=True)

        self.assertEqual(ObservationRecord.objects.count(), 1)
        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(log.records_count, 1)
        self.assertIn("timed out", log.message)
        self.assertIn("1 records saved before the cut-off", log.message)

    def test_clean_run_is_unchanged(self):
        def fetch(station_link, start_date=None, end_date=None):
            yield self.record(1)
            yield FLUSH
            yield self.record(2)

        with patch.object(self.plugin, "get_station_data", side_effect=fetch):
            returned = self.plugin.process_station(self.link, bypass_lock=True)

        self.assertEqual(returned, 2)
        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.COMPLETED)
        self.assertTrue(log.success)
        self.assertEqual(log.records_count, 2)
        self.assertEqual(log.message, "Processed 2 records.")
