from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.test import TestCase

from adl.core import tasks as core_tasks
from adl.core.registries import plugin_registry
from adl.core.tasks import (
    INGEST_LOCK_TTL_MARGIN_SECONDS,
    INGEST_TIME_LIMIT_GRACE_SECONDS,
    ingest_station_lock_key,
    process_station_link_batch,
    run_network_plugin,
)
from adl.monitoring.models import StationLinkActivityLog
from .factories import NetworkConnectionFactory, StationLinkFactory
from .helpers import make_test_plugin


class ProcessStationLockTestCase(TestCase):
    """Shared fixture: one stub plugin and one station link, with the plugin's
    date-window resolution stubbed so tests exercise only the lock seam."""

    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()
        self.lock_key = ingest_station_lock_key(self.link.id)
        self.addCleanup(cache.delete, self.lock_key)

        window = (
            datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc),
            datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc),
        )
        patcher = patch.object(
            type(self.plugin), "get_dates_for_station", return_value=window
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class ProcessStationLockTests(ProcessStationLockTestCase):
    def test_held_lock_skips_with_visible_log_and_no_fetch(self):
        cache.set(self.lock_key, "locked", timeout=60)

        with patch.object(self.plugin, "get_station_data") as mock_get:
            result = self.plugin.process_station(self.link)

        self.assertEqual(result, 0)
        mock_get.assert_not_called()

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.direction, "pull")
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.SKIPPED)
        self.assertTrue(log.success)  # a skip is not a failure
        self.assertIn("previous ingestion still running", log.message)

    def test_lock_released_after_successful_run(self):
        self.plugin.records = []

        self.plugin.process_station(self.link)

        self.assertIsNone(cache.get(self.lock_key))
        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.COMPLETED)

    def test_lock_released_after_failed_run(self):
        with patch.object(
            self.plugin, "get_station_data", side_effect=RuntimeError("host unreachable")
        ):
            self.plugin.process_station(self.link)  # generic errors do not propagate

        self.assertIsNone(cache.get(self.lock_key))
        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertIn("host unreachable", log.message)

    def test_lock_ttl_derives_from_connection_timeout(self):
        # default timeout 300s + 30s hard-limit grace + 60s margin
        with patch.object(cache, "add", return_value=True) as mock_add, \
                patch.object(cache, "delete"):
            self.plugin.records = []
            self.plugin.process_station(self.link)

        mock_add.assert_called_once_with(self.lock_key, "locked", timeout=390)

    def test_soft_time_limit_reraised_after_log_finalised(self):
        with patch.object(
            self.plugin, "get_station_data", side_effect=SoftTimeLimitExceeded()
        ):
            with self.assertRaises(SoftTimeLimitExceeded):
                self.plugin.process_station(self.link)

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("timed out", log.message)
        self.assertIsNotNone(log.duration_ms)
        self.assertIsNone(cache.get(self.lock_key))

    def test_bypass_lock_runs_despite_held_lock(self):
        cache.set(self.lock_key, "locked", timeout=60)

        with patch.object(self.plugin, "get_station_data", return_value=[]) as mock_get:
            self.plugin.process_station(self.link, bypass_lock=True)

        mock_get.assert_called_once()
        # the held lock belongs to someone else and must survive the bypass run
        self.assertEqual(cache.get(self.lock_key), "locked")


class BatchTimeLimitTests(TestCase):
    def test_batch_soft_limit_is_per_station_budget_with_grace_hard_limit(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=30, ingest_timeout_seconds=300
        )
        StationLinkFactory(network_connection=connection)
        StationLinkFactory(network_connection=connection)

        with patch("adl.core.tasks.process_station_link_batch.apply_async") as mock_apply:
            run_network_plugin(connection.id)

        mock_apply.assert_called_once()
        kwargs = mock_apply.call_args.kwargs
        # 2 stations × 300s = 600s, under the 30-minute interval clamp
        self.assertEqual(kwargs["soft_time_limit"], 600)
        self.assertEqual(kwargs["time_limit"], 600 + INGEST_TIME_LIMIT_GRACE_SECONDS)

    def test_batch_soft_limit_clamped_to_connection_interval(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=5, ingest_timeout_seconds=300
        )
        StationLinkFactory(network_connection=connection)
        StationLinkFactory(network_connection=connection)

        with patch("adl.core.tasks.process_station_link_batch.apply_async") as mock_apply:
            run_network_plugin(connection.id)

        kwargs = mock_apply.call_args.kwargs
        # 2 × 300s = 600s would outlive the 5-minute beat tick: clamp to 300s
        self.assertEqual(kwargs["soft_time_limit"], 300)
        self.assertEqual(kwargs["time_limit"], 300 + INGEST_TIME_LIMIT_GRACE_SECONDS)

    def test_batch_reraises_soft_time_limit_from_process_station(self):
        plugin = make_test_plugin()
        link = StationLinkFactory()

        with patch.object(plugin_registry, "get", return_value=plugin), \
                patch.object(plugin, "process_station", side_effect=SoftTimeLimitExceeded()):
            with self.assertRaises(SoftTimeLimitExceeded):
                process_station_link_batch(link.network_connection.id, [link.id])


class LegacyLockTeardownTests(TestCase):
    def test_unlock_all_and_its_worker_ready_hook_are_gone(self):
        self.assertFalse(hasattr(core_tasks, "unlock_all"))

    def test_lock_key_namespace_orphans_legacy_eternal_locks(self):
        self.assertEqual(ingest_station_lock_key(7), "lock:ingest:station:7")

    def test_ttl_constants_mirror_dispatch_convention(self):
        self.assertEqual(INGEST_TIME_LIMIT_GRACE_SECONDS, 30)
        self.assertEqual(INGEST_LOCK_TTL_MARGIN_SECONDS, 60)
