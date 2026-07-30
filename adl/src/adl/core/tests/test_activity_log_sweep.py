from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone as dj_tz

from adl.core.tasks import sweep_stale_activity_logs
from adl.monitoring.models import StationLinkActivityLog
from .factories import NetworkConnectionFactory, StationLinkFactory, Wis2BoxUploadFactory


class ActivityLogSweepTestCase(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)

    def _make_log(self, direction, age_seconds,
                  status=StationLinkActivityLog.ActivityStatus.STARTED,
                  link=None, channel=None):
        return StationLinkActivityLog.objects.create(
            time=dj_tz.now() - timedelta(seconds=age_seconds),
            station_link=link or self.link,
            direction=direction,
            dispatch_channel=(channel or self.channel) if direction == "push" else None,
            status=status,
        )


class SweepBothDirectionsTests(ActivityLogSweepTestCase):
    def test_stale_push_row_swept_to_failed(self):
        # default channel timeout 300s + 30s grace + 60s margin = 390s threshold
        log = self._make_log("push", age_seconds=500)

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 1)
        log.refresh_from_db()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("worker died", log.message)

    def test_stale_pull_row_swept_to_failed(self):
        # default connection ingest timeout 300s + 30s grace + 60s margin = 390s
        log = self._make_log("pull", age_seconds=500)

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 1)
        log.refresh_from_db()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("worker died", log.message)

    def test_one_pass_sweeps_stale_rows_in_both_directions(self):
        push_log = self._make_log("push", age_seconds=500)
        pull_log = self._make_log("pull", age_seconds=500)

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 2)
        push_log.refresh_from_db()
        pull_log.refresh_from_db()
        self.assertEqual(push_log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(pull_log.status, StationLinkActivityLog.ActivityStatus.FAILED)


class SweepLeavesLiveRowsAloneTests(ActivityLogSweepTestCase):
    def test_fresh_rows_untouched_in_both_directions(self):
        # under the 390s threshold: may legitimately still be running
        push_log = self._make_log("push", age_seconds=100)
        pull_log = self._make_log("pull", age_seconds=100)

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 0)
        push_log.refresh_from_db()
        pull_log.refresh_from_db()
        self.assertEqual(push_log.status, StationLinkActivityLog.ActivityStatus.STARTED)
        self.assertEqual(pull_log.status, StationLinkActivityLog.ActivityStatus.STARTED)

    def test_finished_rows_untouched_regardless_of_age(self):
        finished = [
            self._make_log(direction, age_seconds=10_000, status=status)
            for direction in ("push", "pull")
            for status in (StationLinkActivityLog.ActivityStatus.COMPLETED,
                           StationLinkActivityLog.ActivityStatus.FAILED,
                           StationLinkActivityLog.ActivityStatus.SKIPPED)
        ]

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 0)
        for log in finished:
            original_status = log.status
            log.refresh_from_db()
            self.assertEqual(log.status, original_status)


class SweepThresholdTests(ActivityLogSweepTestCase):
    def test_push_threshold_is_per_channel_timeout(self):
        # same age, different channel timeouts: stale for the 30s channel
        # (threshold 120s), still fresh for the 600s channel (threshold 690s)
        short_channel = Wis2BoxUploadFactory(dispatch_timeout_seconds=30)
        long_channel = Wis2BoxUploadFactory(dispatch_timeout_seconds=600)
        stale_for_short = self._make_log("push", age_seconds=300, channel=short_channel)
        fresh_for_long = self._make_log("push", age_seconds=300, channel=long_channel)

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 1)
        stale_for_short.refresh_from_db()
        fresh_for_long.refresh_from_db()
        self.assertEqual(stale_for_short.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(fresh_for_long.status, StationLinkActivityLog.ActivityStatus.STARTED)

    def test_pull_threshold_is_per_connection_ingest_timeout(self):
        # same age, different ingest timeouts: stale for the 30s connection
        # (threshold 120s), still fresh for the 600s connection (threshold 690s)
        short_link = StationLinkFactory(
            network_connection=NetworkConnectionFactory(ingest_timeout_seconds=30))
        long_link = StationLinkFactory(
            network_connection=NetworkConnectionFactory(ingest_timeout_seconds=600))
        stale_for_short = self._make_log("pull", age_seconds=300, link=short_link)
        fresh_for_long = self._make_log("pull", age_seconds=300, link=long_link)

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 1)
        stale_for_short.refresh_from_db()
        fresh_for_long.refresh_from_db()
        self.assertEqual(stale_for_short.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(fresh_for_long.status, StationLinkActivityLog.ActivityStatus.STARTED)


class SweepQueueRoutingTests(TestCase):
    def test_sweep_is_not_routed_to_the_ingestion_queue(self):
        route = settings.CELERY_TASK_ROUTES["adl.core.tasks.sweep_stale_activity_logs"]
        self.assertNotEqual(route["queue"], "adl")
        self.assertEqual(route["queue"], "dispatch")

    def test_push_only_sweep_is_gone(self):
        self.assertNotIn("adl.core.tasks.sweep_stale_dispatch_logs",
                         settings.CELERY_TASK_ROUTES)
        from adl.core import tasks
        self.assertFalse(hasattr(tasks, "sweep_stale_dispatch_logs"))


class SweepRunsHealthEvaluatorTests(ActivityLogSweepTestCase):
    def test_sweep_evaluates_and_stores_every_connections_verdict(self):
        from adl.monitoring.models import NetworkConnectionHealth

        other_link = StationLinkFactory()

        sweep_stale_activity_logs()

        self.assertTrue(NetworkConnectionHealth.objects.filter(
            connection=self.link.network_connection).exists())
        self.assertTrue(NetworkConnectionHealth.objects.filter(
            connection=other_link.network_connection).exists())

    def test_evaluation_happens_after_sweeping(self):
        # The sweep still reports its own count with the evaluator riding along
        log = self._make_log("pull", age_seconds=500)

        swept = sweep_stale_activity_logs()

        self.assertEqual(swept, 1)
        log.refresh_from_db()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)

    def test_one_bad_connection_does_not_blind_the_rest(self):
        from unittest.mock import patch

        from adl.monitoring.models import NetworkConnectionHealth

        other_link = StationLinkFactory()

        from adl.monitoring.health import store_connection_health as real_store

        def flaky_store(connection, checklist, now=None):
            if connection.id == self.link.network_connection.id:
                raise RuntimeError("boom")
            return real_store(connection, checklist, now=now)

        with patch("adl.monitoring.health.store_connection_health", side_effect=flaky_store):
            sweep_stale_activity_logs()

        self.assertTrue(NetworkConnectionHealth.objects.filter(
            connection=other_link.network_connection).exists())
