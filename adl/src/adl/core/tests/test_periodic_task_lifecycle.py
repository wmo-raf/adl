import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from adl.core import tasks
from adl.core.tasks import (
    DISPATCH_TASK_NAME,
    INGESTION_TASK_NAME,
    create_or_update_dispatch_channel_periodic_tasks,
    create_or_update_network_plugin_periodic_tasks,
    delete_dispatch_channel_periodic_tasks,
    delete_network_plugin_periodic_tasks,
    find_periodic_tasks_for,
    prune_orphaned_periodic_tasks,
)
from .factories import NetworkConnectionFactory, Wis2BoxUploadFactory


def add_entry(task_name, object_id, name, args=None):
    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=15, period=IntervalSchedule.MINUTES
    )
    return PeriodicTask.objects.create(
        name=name,
        interval=schedule,
        task=task_name,
        args=args if args is not None else json.dumps([object_id]),
    )


class IngestionScheduleWriterTests(TestCase):
    def setUp(self):
        self.connection = NetworkConnectionFactory()
        PeriodicTask.objects.filter(task=INGESTION_TASK_NAME).delete()

    def entries(self):
        return find_periodic_tasks_for(INGESTION_TASK_NAME, self.connection.id)

    def test_first_write_creates_one_entry(self):
        create_or_update_network_plugin_periodic_tasks(self.connection)

        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(json.loads(entries[0].args), [self.connection.id])
        self.assertTrue(entries[0].enabled)

    def test_repeated_writes_do_not_accumulate_entries(self):
        create_or_update_network_plugin_periodic_tasks(self.connection)
        create_or_update_network_plugin_periodic_tasks(self.connection)

        self.assertEqual(len(self.entries()), 1)

    def test_a_drifted_name_is_updated_rather_than_duplicated(self):
        # The row was written by another Celery build, so its generated name
        # no longer matches repr(sig). It still runs this connection.
        drifted = add_entry(INGESTION_TASK_NAME, self.connection.id, "old-format-name")
        self.connection.plugin_processing_enabled = False
        self.connection.save()

        create_or_update_network_plugin_periodic_tasks(self.connection)

        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].id, drifted.id)
        self.assertFalse(entries[0].enabled)

    def test_pre_existing_duplicates_collapse_to_one(self):
        first = add_entry(INGESTION_TASK_NAME, self.connection.id, "dup-a")
        add_entry(INGESTION_TASK_NAME, self.connection.id, "dup-b")

        create_or_update_network_plugin_periodic_tasks(self.connection)

        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].id, first.id)

    def test_another_connections_entry_is_untouched(self):
        other = NetworkConnectionFactory()
        add_entry(INGESTION_TASK_NAME, other.id, "run-other")

        create_or_update_network_plugin_periodic_tasks(self.connection)

        self.assertEqual(len(find_periodic_tasks_for(INGESTION_TASK_NAME, other.id)), 1)


class IngestionScheduleDeletionTests(TestCase):
    def setUp(self):
        self.connection = NetworkConnectionFactory()
        PeriodicTask.objects.filter(task=INGESTION_TASK_NAME).delete()

    def test_deleting_a_connection_removes_its_schedule_entry(self):
        create_or_update_network_plugin_periodic_tasks(self.connection)
        connection_id = self.connection.id

        self.connection.delete()

        self.assertEqual(find_periodic_tasks_for(INGESTION_TASK_NAME, connection_id), [])

    def test_deleting_a_connection_removes_every_duplicate_entry(self):
        add_entry(INGESTION_TASK_NAME, self.connection.id, "dup-a")
        add_entry(INGESTION_TASK_NAME, self.connection.id, "dup-b")
        connection_id = self.connection.id

        self.connection.delete()

        self.assertEqual(find_periodic_tasks_for(INGESTION_TASK_NAME, connection_id), [])

    def test_deleting_a_connection_leaves_other_connections_entries(self):
        other = NetworkConnectionFactory()
        create_or_update_network_plugin_periodic_tasks(self.connection)
        create_or_update_network_plugin_periodic_tasks(other)

        self.connection.delete()

        self.assertEqual(len(find_periodic_tasks_for(INGESTION_TASK_NAME, other.id)), 1)

    def test_the_receiver_is_a_no_op_when_there_is_no_entry(self):
        delete_network_plugin_periodic_tasks(
            sender=type(self.connection), instance=self.connection
        )

        self.assertEqual(PeriodicTask.objects.filter(task=INGESTION_TASK_NAME).count(), 0)


class DispatchScheduleLifecycleTests(TestCase):
    def setUp(self):
        PeriodicTask.objects.filter(task=DISPATCH_TASK_NAME).delete()

    def test_saving_a_channel_writes_one_entry(self):
        channel = Wis2BoxUploadFactory()

        entries = find_periodic_tasks_for(DISPATCH_TASK_NAME, channel.id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].queue, "dispatch")

    def test_a_drifted_name_is_updated_rather_than_duplicated(self):
        channel = Wis2BoxUploadFactory()
        PeriodicTask.objects.filter(task=DISPATCH_TASK_NAME).delete()
        drifted = add_entry(DISPATCH_TASK_NAME, channel.id, "old-format-name")

        create_or_update_dispatch_channel_periodic_tasks(channel)

        entries = find_periodic_tasks_for(DISPATCH_TASK_NAME, channel.id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].id, drifted.id)

    def test_deleting_a_channel_removes_its_schedule_entry(self):
        channel = Wis2BoxUploadFactory()
        channel_id = channel.id

        channel.delete()

        self.assertEqual(find_periodic_tasks_for(DISPATCH_TASK_NAME, channel_id), [])

    def test_the_receiver_is_a_no_op_when_there_is_no_entry(self):
        channel = Wis2BoxUploadFactory()
        PeriodicTask.objects.filter(task=DISPATCH_TASK_NAME).delete()

        delete_dispatch_channel_periodic_tasks(sender=type(channel), instance=channel)

        self.assertEqual(PeriodicTask.objects.filter(task=DISPATCH_TASK_NAME).count(), 0)


class FindPeriodicTasksForTests(TestCase):
    def setUp(self):
        self.connection = NetworkConnectionFactory()
        PeriodicTask.objects.filter(task=INGESTION_TASK_NAME).delete()

    def test_unparseable_args_are_ignored_rather_than_raising(self):
        add_entry(INGESTION_TASK_NAME, self.connection.id, "broken", args="not-json")

        self.assertEqual(find_periodic_tasks_for(INGESTION_TASK_NAME, self.connection.id), [])

    def test_a_different_task_with_the_same_id_is_not_matched(self):
        add_entry(DISPATCH_TASK_NAME, self.connection.id, "dispatch-entry")

        self.assertEqual(find_periodic_tasks_for(INGESTION_TASK_NAME, self.connection.id), [])

    def test_a_string_id_matches_the_object_it_names(self):
        # A hand-written row can carry ["5"] rather than [5]; compared raw it
        # would read as a different object and the writer would duplicate it
        add_entry(
            INGESTION_TASK_NAME,
            self.connection.id,
            "string-id",
            args=json.dumps([str(self.connection.id)]),
        )

        self.assertEqual(
            len(find_periodic_tasks_for(INGESTION_TASK_NAME, self.connection.id)), 1
        )

    def test_an_id_that_names_no_object_is_ignored(self):
        add_entry(INGESTION_TASK_NAME, None, "not-an-id", args=json.dumps(["abc"]))

        self.assertEqual(find_periodic_tasks_for(INGESTION_TASK_NAME, self.connection.id), [])

    def test_entries_are_returned_in_creation_order(self):
        first = add_entry(INGESTION_TASK_NAME, self.connection.id, "a")
        second = add_entry(INGESTION_TASK_NAME, self.connection.id, "b")

        self.assertEqual(
            [entry.id for entry in find_periodic_tasks_for(INGESTION_TASK_NAME, self.connection.id)],
            [first.id, second.id],
        )


class PruneOrphanedPeriodicTasksTests(TestCase):
    """
    The retrospective cleanup for deployments that already accumulated
    orphans before the post_delete receivers existed.
    """

    def setUp(self):
        PeriodicTask.objects.filter(
            task__in=[INGESTION_TASK_NAME, DISPATCH_TASK_NAME]
        ).delete()

    def test_an_entry_for_a_deleted_connection_is_pruned(self):
        connection = NetworkConnectionFactory()
        create_or_update_network_plugin_periodic_tasks(connection)
        orphan_id = connection.id
        PeriodicTask.objects.filter(task=INGESTION_TASK_NAME).update(name="orphan")
        NetworkConnectionFactory._meta.model.objects.filter(id=orphan_id).delete()
        # re-create the row the delete receiver just removed, as a pre-fix
        # deployment would have left it behind
        add_entry(INGESTION_TASK_NAME, orphan_id, "left-behind")

        pruned = prune_orphaned_periodic_tasks()

        self.assertEqual(find_periodic_tasks_for(INGESTION_TASK_NAME, orphan_id), [])
        self.assertEqual(len(pruned), 1)

    def test_an_entry_for_a_live_connection_is_kept(self):
        connection = NetworkConnectionFactory()
        create_or_update_network_plugin_periodic_tasks(connection)

        prune_orphaned_periodic_tasks()

        self.assertEqual(len(find_periodic_tasks_for(INGESTION_TASK_NAME, connection.id)), 1)

    def test_an_entry_for_a_live_dispatch_channel_is_kept(self):
        channel = Wis2BoxUploadFactory()

        prune_orphaned_periodic_tasks()

        self.assertEqual(len(find_periodic_tasks_for(DISPATCH_TASK_NAME, channel.id)), 1)

    def test_a_dry_run_reports_without_deleting(self):
        add_entry(INGESTION_TASK_NAME, 999999, "left-behind")

        pruned = prune_orphaned_periodic_tasks(dry_run=True)

        self.assertEqual(len(pruned), 1)
        self.assertEqual(len(find_periodic_tasks_for(INGESTION_TASK_NAME, 999999)), 1)

    def test_an_unrelated_task_is_never_pruned(self):
        add_entry("some.other.task", 999999, "unrelated")

        prune_orphaned_periodic_tasks()

        self.assertTrue(PeriodicTask.objects.filter(name="unrelated").exists())

    def test_an_entry_whose_owner_appears_mid_scan_is_kept(self):
        # A connection created after the live-id snapshot has its entry
        # written by post_save; judged against that stale snapshot it would
        # look like an orphan, and a live connection would lose its schedule
        racing_id = 999999
        add_entry(INGESTION_TASK_NAME, racing_id, "born-mid-scan")
        real_iter = tasks.iter_owned_schedule_entries

        def iter_then_create_the_connection(task_name):
            entries = list(real_iter(task_name))
            if task_name == INGESTION_TASK_NAME:
                NetworkConnectionFactory(id=racing_id)
            return iter(entries)

        with patch.object(
            tasks, "iter_owned_schedule_entries", iter_then_create_the_connection
        ):
            pruned = prune_orphaned_periodic_tasks()

        self.assertEqual(pruned, [])
        self.assertEqual(len(find_periodic_tasks_for(INGESTION_TASK_NAME, racing_id)), 1)

    def test_a_string_id_naming_a_live_connection_is_not_pruned(self):
        connection = NetworkConnectionFactory()
        add_entry(
            INGESTION_TASK_NAME,
            connection.id,
            "string-id",
            args=json.dumps([str(connection.id)]),
        )

        pruned = prune_orphaned_periodic_tasks()

        self.assertEqual(pruned, [])

    def test_the_management_command_removes_orphans(self):
        add_entry(INGESTION_TASK_NAME, 999999, "left-behind")
        out = StringIO()

        call_command("prune_orphaned_periodic_tasks", stdout=out)

        self.assertEqual(len(find_periodic_tasks_for(INGESTION_TASK_NAME, 999999)), 0)
        self.assertIn("Removed 1", out.getvalue())

    def test_the_management_command_honours_dry_run(self):
        add_entry(INGESTION_TASK_NAME, 999999, "left-behind")
        out = StringIO()

        call_command("prune_orphaned_periodic_tasks", "--dry-run", stdout=out)

        self.assertEqual(len(find_periodic_tasks_for(INGESTION_TASK_NAME, 999999)), 1)
        self.assertIn("DRY RUN", out.getvalue())

    def test_an_entry_with_unreadable_args_is_left_alone(self):
        add_entry(INGESTION_TASK_NAME, None, "unreadable", args="not-json")

        pruned = prune_orphaned_periodic_tasks()

        self.assertTrue(PeriodicTask.objects.filter(name="unreadable").exists())
        self.assertEqual(pruned, [])
