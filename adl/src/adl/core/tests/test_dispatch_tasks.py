from datetime import datetime, timedelta, timezone as py_tz
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone as dj_tz

from adl.core.models import StationChannelDispatchStatus, Wis2BoxUpload
from adl.core.tasks import (
    dispatch_station,
    perform_channel_dispatch,
    sweep_stale_dispatch_logs,
)
from adl.monitoring.models import StationLinkActivityLog
from .factories import StationLinkFactory, Wis2BoxUploadFactory


class DispatchTaskTestCase(TestCase):
    """Shared fixture: one channel wired to one station link, plus fake records."""

    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        self.obs_time = datetime(2025, 1, 1, 12, 0, tzinfo=py_tz.utc)
        self.records = [
            {
                "station_id": self.link.station_id,
                "timestamp": self.obs_time,
                "values": {"air_temperature": 20.0},
            }
        ]
        self.lock_key = f"lock:dispatch:{self.channel.id}:{self.link.id}"
        self.addCleanup(cache.delete, self.lock_key)


class DispatchStationTests(DispatchTaskTestCase):
    def test_successful_dispatch_logs_completed_and_advances_checkpoint(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", return_value=(1, self.obs_time)):
            result = dispatch_station(self.channel.id, self.link.id)

        self.assertEqual(result, {"records_sent": 1})

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.direction, "push")
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.COMPLETED)
        self.assertTrue(log.success)
        self.assertEqual(log.records_count, 1)
        self.assertEqual(log.dispatch_channel_id, self.channel.id)
        self.assertIsNotNone(log.duration_ms)

        checkpoint = StationChannelDispatchStatus.objects.get(
            channel=self.channel, station=self.link.station
        )
        self.assertEqual(checkpoint.last_sent_obs_time, self.obs_time)


    def test_timed_out_dispatch_logged_as_failed_without_raising(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", side_effect=SoftTimeLimitExceeded()):
            dispatch_station(self.channel.id, self.link.id)  # must not raise

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("timed out", log.message)
        self.assertIsNotNone(log.duration_ms)
        # no checkpoint advance on timeout
        self.assertFalse(StationChannelDispatchStatus.objects.exists())


    def test_send_failure_logged_as_failed_and_reraised(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", side_effect=RuntimeError("bucket unreachable")):
            with self.assertRaises(RuntimeError):
                dispatch_station(self.channel.id, self.link.id)

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("bucket unreachable", log.message)
        self.assertIsNotNone(log.duration_ms)


class DispatchStationLockTests(DispatchTaskTestCase):
    def test_held_lock_skips_with_visible_log_and_no_send(self):
        cache.set(self.lock_key, "locked", timeout=60)

        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data") as mock_send:
            dispatch_station(self.channel.id, self.link.id)

        mock_send.assert_not_called()

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.SKIPPED)
        self.assertEqual(log.direction, "push")
        self.assertTrue(log.success)  # a skip is not a failure
        self.assertIn("previous dispatch still running", log.message)
        self.assertFalse(StationChannelDispatchStatus.objects.exists())

    def test_lock_released_after_successful_dispatch(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", return_value=(1, self.obs_time)):
            dispatch_station(self.channel.id, self.link.id)

        self.assertIsNone(cache.get(self.lock_key))

    def test_lock_released_after_failed_dispatch(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                dispatch_station(self.channel.id, self.link.id)

        self.assertIsNone(cache.get(self.lock_key))

    def test_lock_ttl_derives_from_channel_timeout(self):
        # default timeout 300s + 30s hard-limit grace + 60s margin
        with patch.object(cache, "add", return_value=True) as mock_add, \
                patch.object(cache, "delete"), \
                patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", return_value=(1, self.obs_time)):
            dispatch_station(self.channel.id, self.link.id)

        mock_add.assert_called_once_with(self.lock_key, "locked", timeout=390)


class SweepStaleDispatchLogsTests(DispatchTaskTestCase):
    def _make_push_log(self, age_seconds, status=StationLinkActivityLog.ActivityStatus.STARTED,
                       channel=None):
        return StationLinkActivityLog.objects.create(
            time=dj_tz.now() - timedelta(seconds=age_seconds),
            station_link=self.link,
            direction="push",
            dispatch_channel=channel or self.channel,
            status=status,
        )

    def test_stale_started_row_swept_to_failed(self):
        # default channel timeout 300s + 30s grace + 60s margin = 390s threshold
        log = self._make_push_log(age_seconds=500)

        swept = sweep_stale_dispatch_logs()

        self.assertEqual(swept, 1)
        log.refresh_from_db()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("worker died", log.message)

    def test_fresh_started_row_untouched(self):
        # under the 390s threshold: may legitimately still be running
        log = self._make_push_log(age_seconds=100)

        swept = sweep_stale_dispatch_logs()

        self.assertEqual(swept, 0)
        log.refresh_from_db()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.STARTED)

    def test_finished_rows_untouched_regardless_of_age(self):
        completed = self._make_push_log(
            age_seconds=10_000, status=StationLinkActivityLog.ActivityStatus.COMPLETED)
        failed = self._make_push_log(
            age_seconds=10_000, status=StationLinkActivityLog.ActivityStatus.FAILED)

        swept = sweep_stale_dispatch_logs()

        self.assertEqual(swept, 0)
        completed.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual(completed.status, StationLinkActivityLog.ActivityStatus.COMPLETED)
        self.assertEqual(failed.status, StationLinkActivityLog.ActivityStatus.FAILED)

    def test_threshold_is_per_channel_timeout(self):
        # same age, different channel timeouts: stale for the 30s channel
        # (threshold 120s), still fresh for the 600s channel (threshold 690s)
        short_channel = Wis2BoxUploadFactory(dispatch_timeout_seconds=30)
        long_channel = Wis2BoxUploadFactory(dispatch_timeout_seconds=600)
        stale_for_short = self._make_push_log(age_seconds=300, channel=short_channel)
        fresh_for_long = self._make_push_log(age_seconds=300, channel=long_channel)

        swept = sweep_stale_dispatch_logs()

        self.assertEqual(swept, 1)
        stale_for_short.refresh_from_db()
        fresh_for_long.refresh_from_db()
        self.assertEqual(stale_for_short.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(fresh_for_long.status, StationLinkActivityLog.ActivityStatus.STARTED)


class CoordinatorTaskContractTests(TestCase):
    def test_coordinator_is_not_a_singleton_task(self):
        """A stale Singleton lock silently discarded beat ticks; the coordinator
        must never be deduplicated again."""
        from celery_singleton import Singleton
        self.assertNotIsInstance(perform_channel_dispatch, Singleton)


class PerformChannelDispatchTests(TestCase):
    def test_station_tasks_enqueued_with_channel_timeout_limits(self):
        link = StationLinkFactory()
        channel = Wis2BoxUploadFactory(dispatch_timeout_seconds=120)
        channel.network_connections.add(link.network_connection)

        with patch("adl.core.tasks.dispatch_station.apply_async") as mock_apply:
            perform_channel_dispatch(channel.id)

        mock_apply.assert_called_once()
        kwargs = mock_apply.call_args.kwargs
        self.assertEqual(kwargs["args"], [channel.id, link.id])
        self.assertEqual(kwargs["soft_time_limit"], 120)
        self.assertEqual(kwargs["time_limit"], 150)  # soft + 30s grace
