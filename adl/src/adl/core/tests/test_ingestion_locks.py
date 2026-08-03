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
    effective_ingest_station_seconds,
    ingest_batch_budget_seconds,
    ingest_batch_soft_limit_seconds,
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

    def test_lock_ttl_derives_from_the_batch_bound(self):
        # stock defaults: batch soft limit 900s (10 × 300s clamped to the
        # 15-minute interval) + 30s hard-limit grace + 60s margin
        with patch.object(cache, "add", return_value=True) as mock_add, \
                patch.object(cache, "delete"):
            self.plugin.records = []
            self.plugin.process_station(self.link)

        mock_add.assert_called_once_with(self.lock_key, "locked", timeout=990)

    def test_lock_outlives_a_station_running_past_the_per_station_budget(self):
        # Regression for #209: a station may legitimately occupy the whole
        # batch budget — with batching there is no per-station soft limit — so
        # the lock must still be held once the per-station number has elapsed,
        # or the concurrent run it exists to prevent is re-admitted.
        connection = self.link.network_connection
        per_station_budget = (connection.ingest_timeout_seconds
                              + INGEST_TIME_LIMIT_GRACE_SECONDS
                              + INGEST_LOCK_TTL_MARGIN_SECONDS)

        # Let the run acquire the lock for real, but hold onto it afterwards so
        # its remaining life can be read back out of the cache
        with patch.object(cache, "delete"):
            self.plugin.records = []
            self.plugin.process_station(self.link)

        self.assertGreater(cache.ttl(self.lock_key), per_station_budget)

        # and a second entrant, arriving inside that window, is still refused
        with patch.object(self.plugin, "get_station_data") as mock_get:
            self.assertEqual(self.plugin.process_station(self.link), 0)
        mock_get.assert_not_called()

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


class IngestBatchBudgetTests(TestCase):
    """The single bound shared by the station lock TTL and the pull-side
    stale-log sweep, per decision #153 §5."""

    def test_budget_is_batch_soft_limit_plus_grace_and_margin(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=15, ingest_timeout_seconds=300, batch_size=10
        )

        # 10 × 300s clamped to the 900s interval, + 30s grace + 60s margin
        self.assertEqual(ingest_batch_budget_seconds(connection), 990)

    def test_budget_uses_the_configured_batch_size_as_an_upper_bound(self):
        # the sweeper cannot see the actual batch, so the configured size wins
        connection = NetworkConnectionFactory(
            plugin_processing_interval=60, ingest_timeout_seconds=300, batch_size=4
        )

        # 4 × 300s = 1200s, well under the 3600s interval
        self.assertEqual(ingest_batch_budget_seconds(connection), 1290)

    def test_unbatched_connection_collapses_to_the_per_station_budget(self):
        # batch_size=1 is the degenerate case the old per-station helper always
        # assumed: one station is the whole batch, so both numbers coincide
        connection = NetworkConnectionFactory(
            plugin_processing_interval=15, ingest_timeout_seconds=300, batch_size=1
        )

        per_station_budget = (connection.ingest_timeout_seconds
                              + INGEST_TIME_LIMIT_GRACE_SECONDS
                              + INGEST_LOCK_TTL_MARGIN_SECONDS)
        self.assertEqual(ingest_batch_budget_seconds(connection), per_station_budget)

    def test_short_interval_clamps_the_budget_below_the_per_station_number(self):
        # the clamp binds in both directions: a connection ticking every minute
        # cannot grant any station more than that minute, batching or not
        connection = NetworkConnectionFactory(
            plugin_processing_interval=1, ingest_timeout_seconds=300, batch_size=10
        )

        self.assertEqual(ingest_batch_budget_seconds(connection), 60 + 30 + 60)

    def test_zero_batch_size_uses_the_batch_the_coordinator_would_form(self):
        # 0 is admin-reachable and means "unset": the coordinator still chunks
        # by 10, so the budget must size for 10 and not for a single station
        connection = NetworkConnectionFactory(
            plugin_processing_interval=60, ingest_timeout_seconds=300, batch_size=0
        )

        # 10 × 300s = 3000s, under the 3600s interval, + 30s grace + 60s margin
        self.assertEqual(ingest_batch_budget_seconds(connection), 3090)


class EffectiveStationTimeoutTests(TestCase):
    """The figure the admin displays, per decision #153 §2 — the per-station
    share a full batch actually gets once the interval clamp is applied."""

    def test_unclamped_batch_gives_each_station_the_configured_timeout(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=30, ingest_timeout_seconds=300, batch_size=2
        )

        # 2 × 300s = 600s fits inside the 30-minute interval: no cap
        self.assertEqual(ingest_batch_soft_limit_seconds(connection, 2), 600)
        self.assertEqual(effective_ingest_station_seconds(connection), 300)

    def test_clamped_batch_shortens_each_station_share(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=15, ingest_timeout_seconds=300, batch_size=10
        )

        # stock defaults: 10 × 300s = 3000s, clamped to the 900s interval,
        # so the configured 300s is really 90s a station
        self.assertEqual(ingest_batch_soft_limit_seconds(connection, 10), 900)
        self.assertEqual(effective_ingest_station_seconds(connection), 90)

    def test_batch_size_of_one_is_never_clamped_below_the_interval(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=1, ingest_timeout_seconds=300, batch_size=1
        )

        # one station cannot outrun its own tick by more than the interval
        self.assertEqual(effective_ingest_station_seconds(connection), 60)

    def test_zero_batch_size_falls_back_to_the_coordinators_own_default(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=15, ingest_timeout_seconds=300, batch_size=0
        )

        # 0 means "unset", and the coordinator reads it as 10 — so the admin
        # must show the share of a batch of 10, not a station running alone
        self.assertEqual(effective_ingest_station_seconds(connection), 90)

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
