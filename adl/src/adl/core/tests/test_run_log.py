"""
Per-run logs (adl.core.run_log): what a worker was doing during one run,
readable from the run's activity row without server access.

A Campbell station's runs were being recorded as "worker died mid-run" with
nothing to say where; the activity row only ever held a one-line verdict.
These tests pin the contract: every record logged while a run's scope is
open — whatever logger it comes from — lands on that run's row, bounded to
its first and last lines, flushed while the run is still going so a run that
is killed outright keeps what it logged, and without ever swallowing the
batch's soft time limit.
"""

import logging
from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from adl.core import run_log
from adl.core.models import Wis2BoxUpload
from adl.core.run_log import (
    RunLogBuffer,
    RunLogSink,
    capture,
)
from adl.core.tasks import dispatch_station, ingest_station_lock_key, process_station_link_batch
from adl.monitoring.models import IngestionBatchLog, StationLinkActivityLog
from .factories import StationLinkFactory, Wis2BoxUploadFactory
from .helpers import make_test_plugin

plugin_logger = logging.getLogger("adl_some_vendor_plugin.client")


def messages(lines):
    return [line["msg"] for line in lines or [] if "msg" in line]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RunLogBufferTests(SimpleTestCase):
    def test_under_the_cap_every_line_is_kept_in_order(self):
        buffer = RunLogBuffer(head=3, tail=3)
        for i in range(5):
            buffer.add(i)
        self.assertEqual(buffer.snapshot(), [0, 1, 2, 3, 4])

    def test_over_the_cap_keeps_the_first_and_last_lines_and_counts_the_rest(self):
        buffer = RunLogBuffer(head=2, tail=2)
        for i in range(10):
            buffer.add(i)
        self.assertEqual(buffer.snapshot(), [0, 1, {"omitted": 6}, 8, 9])


class RunLogSinkTests(SimpleTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.persisted = []
        self.sink = RunLogSink(self.persisted.append, interval=2.0, clock=self.clock)

    def test_lines_are_persisted_at_most_once_per_interval(self):
        self.sink.add({"msg": "a"})
        self.sink.add({"msg": "b"})
        self.assertEqual(self.persisted, [])

        self.clock.now = 2.5
        self.sink.add({"msg": "c"})
        self.assertEqual(messages(self.persisted[-1]), ["a", "b", "c"])
        self.assertEqual(len(self.persisted), 1)

    def test_close_persists_what_the_last_interval_held(self):
        self.sink.add({"msg": "a"})
        self.sink.close()
        self.assertEqual(messages(self.persisted[-1]), ["a"])

    def test_a_failing_store_does_not_fail_the_run(self):
        def broken(lines):
            raise RuntimeError("database gone")

        sink = RunLogSink(broken, interval=0, clock=self.clock)
        sink.add({"msg": "a"})  # does not raise

    def test_the_soft_time_limit_arriving_during_a_store_is_not_swallowed(self):
        def interrupted(lines):
            raise SoftTimeLimitExceeded()

        sink = RunLogSink(interrupted, interval=0, clock=self.clock)
        with capture(sink), self.assertRaises(SoftTimeLimitExceeded):
            plugin_logger.warning("downloading file 3 of 9")


class HandlerRoutingTests(SimpleTestCase):
    def sink(self):
        persisted = []
        return RunLogSink(persisted.append, interval=0), persisted

    def test_records_outside_a_scope_go_nowhere(self):
        sink, persisted = self.sink()
        plugin_logger.warning("before")
        with capture(sink):
            pass
        plugin_logger.warning("after")
        self.assertEqual(persisted, [])

    def test_any_logger_is_captured_not_only_the_task_logger(self):
        sink, persisted = self.sink()
        with capture(sink):
            plugin_logger.info("listing /data/CR1000")
        line = persisted[-1][0]
        self.assertEqual(line["msg"], "listing /data/CR1000")
        self.assertEqual(line["level"], "INFO")
        self.assertEqual(line["logger"], "adl_some_vendor_plugin.client")

    def test_debug_and_database_chatter_are_left_out(self):
        sink, persisted = self.sink()
        with capture(sink):
            plugin_logger.debug("raw bytes …")
            logging.getLogger("django.db.backends").error("SELECT 1")
            plugin_logger.warning("kept")
        self.assertEqual(messages(persisted[-1]), ["kept"])

    def test_nested_scopes_route_to_the_innermost(self):
        outer, outer_lines = self.sink()
        inner, inner_lines = self.sink()
        with capture(outer):
            plugin_logger.warning("batch: spawning")
            with capture(inner):
                plugin_logger.warning("station: fetching")
            plugin_logger.warning("batch: done")
        self.assertEqual(messages(outer_lines[-1]), ["batch: spawning", "batch: done"])
        self.assertEqual(messages(inner_lines[-1]), ["station: fetching"])

    def test_lines_are_redacted_and_carry_their_traceback(self):
        sink, persisted = self.sink()
        with capture(sink):
            try:
                raise ValueError("boom")
            except ValueError:
                plugin_logger.exception("GET https://e.org/data?api_key=abc123 failed")
        msg = persisted[-1][0]["msg"]
        self.assertNotIn("abc123", msg)
        self.assertIn("ValueError: boom", msg)


class ProcessStationRunLogTests(TestCase):
    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()
        self.addCleanup(cache.delete, ingest_station_lock_key(self.link.id))
        window = (
            datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc),
            datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc),
        )
        patcher = patch.object(type(self.plugin), "get_dates_for_station", return_value=window)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_run_log_survives_the_runs_own_save_of_the_row(self):
        def source(*args, **kwargs):
            plugin_logger.warning("decoding CR1000_Hourly.dat")
            return []

        with patch.object(self.plugin, "get_station_data", side_effect=source):
            self.plugin.process_station(self.link)

        row = StationLinkActivityLog.objects.get()
        self.assertEqual(row.status, StationLinkActivityLog.ActivityStatus.COMPLETED)
        self.assertIn("decoding CR1000_Hourly.dat", messages(row.log_lines))

    def test_lines_reach_the_row_while_the_run_is_still_going(self):
        # The case the feature exists for: a run killed outright never reaches
        # its finally, so what is on the row is what was flushed before
        seen_mid_run = []

        def source(*args, **kwargs):
            plugin_logger.warning("downloading file 3 of 9")
            seen_mid_run.extend(messages(StationLinkActivityLog.objects.get().log_lines))
            return []

        with patch.object(run_log, "FLUSH_INTERVAL_SECONDS", 0), \
                patch.object(self.plugin, "get_station_data", side_effect=source):
            self.plugin.process_station(self.link)

        self.assertIn("downloading file 3 of 9", seen_mid_run)

    def test_a_timed_out_run_keeps_its_log_and_still_re_raises(self):
        def source(*args, **kwargs):
            plugin_logger.warning("decoding a large file")
            raise SoftTimeLimitExceeded()

        with patch.object(self.plugin, "get_station_data", side_effect=source), \
                self.assertRaises(SoftTimeLimitExceeded):
            self.plugin.process_station(self.link)

        row = StationLinkActivityLog.objects.get()
        self.assertEqual(row.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertIn("decoding a large file", messages(row.log_lines))


class BatchRunLogTests(TestCase):
    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection
        self.addCleanup(cache.delete, ingest_station_lock_key(self.link.id))
        window = (
            datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc),
            datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc),
        )
        patcher = patch.object(type(self.plugin), "get_dates_for_station", return_value=window)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_batch_lines_and_station_lines_are_kept_apart_and_linked_by_task_id(self):
        def source(*args, **kwargs):
            plugin_logger.warning("station-only line")
            return []

        with patch("adl.core.registries.plugin_registry.get", return_value=self.plugin), \
                patch.object(self.plugin, "get_station_data", side_effect=source):
            process_station_link_batch.apply(
                args=[self.connection.id, [self.link.id]], task_id="batch-task-1",
            )

        row = StationLinkActivityLog.objects.get()
        self.assertEqual(row.task_id, "batch-task-1")
        self.assertIn("station-only line", messages(row.log_lines))

        batch = IngestionBatchLog.objects.get(task_id="batch-task-1")
        self.assertEqual(batch.network_connection_id, self.connection.id)
        batch_messages = " ".join(messages(batch.log_lines))
        self.assertIn("Starting batch processing", batch_messages)
        self.assertIn("Batch complete", batch_messages)
        self.assertNotIn("station-only line", batch_messages)


class DispatchRunLogTests(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        self.addCleanup(cache.delete, f"lock:dispatch:{self.channel.id}:{self.link.id}")

    def test_a_dispatch_run_keeps_its_log_on_the_push_row(self):
        records = [{"station_id": self.link.station_id, "values": {}}]

        def send(*args, **kwargs):
            plugin_logger.warning("uploading to minio")
            return 0, None

        with patch("adl.core.tasks.get_station_dispatch_records", return_value=records), \
                patch.object(Wis2BoxUpload, "send_station_data", side_effect=send):
            dispatch_station.apply(args=[self.channel.id, self.link.id], task_id="dispatch-task-1")

        row = StationLinkActivityLog.objects.get(direction="push")
        self.assertEqual(row.task_id, "dispatch-task-1")
        self.assertIn("uploading to minio", messages(row.log_lines))


class LoggingConfigTests(SimpleTestCase):
    def test_run_logs_get_info_lines_whatever_the_console_level(self):
        # ADL_LOG_LEVEL=WARNING is common in deployments. Applied to the root
        # logger it dropped INFO records before any handler saw them, so run
        # logs lost "Fetching …" and "Saved …" — the lines that say where a
        # run was. It belongs on the console handler.
        from django.conf import settings

        self.assertLessEqual(logging.getLogger().getEffectiveLevel(), logging.INFO)
        self.assertEqual(settings.LOGGING["handlers"]["console"]["level"], settings.ADL_LOG_LEVEL)
