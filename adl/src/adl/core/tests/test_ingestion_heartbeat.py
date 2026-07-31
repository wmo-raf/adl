import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as dj_tz
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from adl.core.models import NetworkConnectionHeartbeat
from adl.core.tasks import (
    INGESTION_TASK_NAME,
    find_connection_schedule_entries,
    run_network_plugin,
)
from .factories import NetworkConnectionFactory, StationLinkFactory


class IngestionHeartbeatStampTests(TestCase):
    """
    The coordinator is the single write point for ``last_run_at``, so these
    tests call it directly rather than going through beat.
    """

    def setUp(self):
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection

    def run_coordinator(self):
        with patch("adl.core.tasks.process_station_link_batch.apply_async"):
            return run_network_plugin(self.connection.id)

    def test_coordinator_stamps_heartbeat_every_run(self):
        self.run_coordinator()

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertEqual(heartbeat.station_links_enabled, 1)
        self.assertEqual(heartbeat.batches_spawned, 1)
        self.assertAlmostEqual(
            heartbeat.last_run_at, dj_tz.now(), delta=timedelta(seconds=10)
        )

        first_run_at = heartbeat.last_run_at
        self.run_coordinator()

        self.assertEqual(NetworkConnectionHeartbeat.objects.count(), 1)  # updated, not duplicated
        heartbeat.refresh_from_db()
        self.assertGreaterEqual(heartbeat.last_run_at, first_run_at)

    def test_coordinator_caches_the_workers_broker_stack(self):
        # The running-task-age guard judges the worker's own stack; the
        # coordinator runs in the worker process, so its stamp is that stack
        self.run_coordinator()

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertEqual(set(heartbeat.worker_versions), {"celery", "kombu", "redis"})

    def test_manual_run_caches_the_workers_broker_stack_too(self):
        # A manual run executes in the worker as well — the version cache is
        # about which container ran, not about scheduling
        with patch("adl.core.tasks.process_station_link_batch.apply_async"):
            run_network_plugin(self.connection.id, manual=True)

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertIsNone(heartbeat.last_run_at)
        self.assertEqual(set(heartbeat.worker_versions), {"celery", "kombu", "redis"})

    def test_heartbeat_is_stamped_when_no_station_links_are_enabled(self):
        self.link.enabled = False
        self.link.save()

        self.run_coordinator()

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertEqual(heartbeat.station_links_enabled, 0)
        self.assertEqual(heartbeat.batches_spawned, 0)
        self.assertIsNotNone(heartbeat.last_run_at)

    def test_batches_spawned_counts_batches_not_station_links(self):
        StationLinkFactory(network_connection=self.connection)
        StationLinkFactory(network_connection=self.connection)
        self.connection.batch_size = 2
        self.connection.save()

        self.run_coordinator()

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertEqual(heartbeat.station_links_enabled, 3)
        self.assertEqual(heartbeat.batches_spawned, 2)

    def test_missing_connection_stamps_nothing(self):
        with patch("adl.core.tasks.process_station_link_batch.apply_async"):
            run_network_plugin(self.connection.id + 1000)

        self.assertEqual(NetworkConnectionHeartbeat.objects.count(), 0)

    def test_manual_run_stamps_last_manual_run_at_not_last_run_at(self):
        with patch("adl.core.tasks.process_station_link_batch.apply_async"):
            run_network_plugin(self.connection.id, manual=True)

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertIsNone(heartbeat.last_run_at)
        self.assertAlmostEqual(
            heartbeat.last_manual_run_at, dj_tz.now(), delta=timedelta(seconds=10)
        )

    def test_manual_run_preserves_the_scheduled_heartbeat(self):
        scheduled_at = dj_tz.now() - timedelta(hours=1)
        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=scheduled_at,
            station_links_enabled=1,
            batches_spawned=1,
            task_id="scheduled-task",
        )

        with patch("adl.core.tasks.process_station_link_batch.apply_async"):
            run_network_plugin(self.connection.id, manual=True)

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertEqual(heartbeat.last_run_at, scheduled_at)
        self.assertEqual(heartbeat.station_links_enabled, 1)
        self.assertEqual(heartbeat.batches_spawned, 1)
        self.assertEqual(heartbeat.task_id, "scheduled-task")
        self.assertIsNotNone(heartbeat.last_manual_run_at)

    def test_manual_run_with_no_enabled_links_still_stamps_only_the_manual_slot(self):
        self.link.enabled = False
        self.link.save()

        with patch("adl.core.tasks.process_station_link_batch.apply_async"):
            run_network_plugin(self.connection.id, manual=True)

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertIsNone(heartbeat.last_run_at)
        self.assertIsNotNone(heartbeat.last_manual_run_at)

    def test_manual_run_spawns_batches_identically_to_a_scheduled_run(self):
        with patch("adl.core.tasks.process_station_link_batch.apply_async") as scheduled:
            run_network_plugin(self.connection.id)
        with patch("adl.core.tasks.process_station_link_batch.apply_async") as manual:
            run_network_plugin(self.connection.id, manual=True)

        self.assertEqual(scheduled.call_args_list, manual.call_args_list)

    def test_coordinator_write_preserves_last_manual_run_at(self):
        manual_run_at = dj_tz.now() - timedelta(hours=2)
        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=manual_run_at,
            last_manual_run_at=manual_run_at,
        )

        self.run_coordinator()

        heartbeat = NetworkConnectionHeartbeat.objects.get(connection=self.connection)
        self.assertEqual(heartbeat.last_manual_run_at, manual_run_at)
        self.assertGreater(heartbeat.last_run_at, manual_run_at)


class IngestionOverdueTests(TestCase):
    def setUp(self):
        # plugin_processing_interval default = 15 minutes -> overdue threshold 30 minutes
        self.connection = NetworkConnectionFactory()
        self.now = dj_tz.now()

    def stamp(self, minutes_ago):
        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=self.now - timedelta(minutes=minutes_ago),
        )

    def test_fresh_run_is_not_overdue(self):
        self.stamp(minutes_ago=1)
        self.assertFalse(self.connection.is_ingestion_overdue(now=self.now))

    def test_just_under_twice_interval_is_not_overdue(self):
        self.stamp(minutes_ago=29)
        self.assertFalse(self.connection.is_ingestion_overdue(now=self.now))

    def test_exactly_twice_interval_is_not_yet_overdue(self):
        self.stamp(minutes_ago=30)
        self.assertFalse(self.connection.is_ingestion_overdue(now=self.now))

    def test_beyond_twice_interval_is_overdue(self):
        self.stamp(minutes_ago=31)
        self.assertTrue(self.connection.is_ingestion_overdue(now=self.now))

    def test_disabled_connection_is_never_overdue(self):
        self.connection.plugin_processing_enabled = False
        self.stamp(minutes_ago=500)
        self.assertFalse(self.connection.is_ingestion_overdue(now=self.now))

    def test_never_ran_enabled_connection_is_overdue(self):
        self.assertTrue(self.connection.is_ingestion_overdue(now=self.now))

    def test_never_ran_disabled_connection_is_not_overdue(self):
        self.connection.plugin_processing_enabled = False
        self.assertFalse(self.connection.is_ingestion_overdue(now=self.now))

    def test_overdue_threshold_follows_the_connection_interval(self):
        self.connection.plugin_processing_interval = 5
        self.stamp(minutes_ago=11)
        self.assertTrue(self.connection.is_ingestion_overdue(now=self.now))


class ConnectionScheduleEntryLookupTests(TestCase):
    """
    Entries are resolved by what they run — ``task`` plus ``args`` — so a
    duplicated or renamed schedule row is visible instead of silently missed.
    """

    def setUp(self):
        self.connection = NetworkConnectionFactory()
        self.schedule, _ = IntervalSchedule.objects.get_or_create(
            every=15, period=IntervalSchedule.MINUTES
        )
        PeriodicTask.objects.filter(task=INGESTION_TASK_NAME).delete()

    def add_entry(self, name, connection=None, args=None):
        connection = connection or self.connection
        return PeriodicTask.objects.create(
            name=name,
            interval=self.schedule,
            task=INGESTION_TASK_NAME,
            args=args if args is not None else json.dumps([connection.id]),
            queue="adl",
        )

    def test_single_entry_is_resolved(self):
        entry = self.add_entry("run-conn")

        found = find_connection_schedule_entries(self.connection)

        self.assertFalse(found.missing)
        self.assertFalse(found.duplicated)
        self.assertEqual(found.entry, entry)

    def test_no_entry_reports_missing(self):
        found = find_connection_schedule_entries(self.connection)

        self.assertTrue(found.missing)
        self.assertFalse(found.duplicated)
        self.assertIsNone(found.entry)

    def test_two_entries_for_the_same_connection_report_duplicated(self):
        self.add_entry("run-conn")
        self.add_entry("run-conn-renamed")

        found = find_connection_schedule_entries(self.connection)

        self.assertFalse(found.missing)
        self.assertTrue(found.duplicated)
        self.assertEqual(len(found.entries), 2)

    def test_entry_for_another_connection_is_not_matched(self):
        other = NetworkConnectionFactory()
        self.add_entry("run-other", connection=other)

        self.assertTrue(find_connection_schedule_entries(self.connection).missing)
        self.assertFalse(find_connection_schedule_entries(other).missing)

    def test_lookup_is_insensitive_to_args_formatting(self):
        self.add_entry("run-conn-spaced", args=f"[ {self.connection.id} ]")

        self.assertFalse(find_connection_schedule_entries(self.connection).missing)

    def test_unparseable_args_are_ignored_rather_than_raising(self):
        self.add_entry("run-conn-broken", args="not-json")

        self.assertTrue(find_connection_schedule_entries(self.connection).missing)

    def test_entry_running_a_different_task_is_not_matched(self):
        PeriodicTask.objects.create(
            name="dispatch-entry",
            interval=self.schedule,
            task="adl.core.tasks.perform_channel_dispatch",
            args=json.dumps([self.connection.id]),
        )

        self.assertTrue(find_connection_schedule_entries(self.connection).missing)

    def test_entry_created_by_the_scheduler_writer_is_found(self):
        from adl.core.tasks import create_or_update_network_plugin_periodic_tasks

        create_or_update_network_plugin_periodic_tasks(self.connection)

        found = find_connection_schedule_entries(self.connection)
        self.assertFalse(found.missing)
        self.assertFalse(found.duplicated)
