"""
The active-tasks endpoint behind the Task Monitor dashboard.

Its whole purpose is to be usable when ingestion is broken, so the tests here
are about the two ways it used to fail that promise (#166): unbounded inspect
calls that hang the request thread, and silence from the workers rendered as
"nothing is running".
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from adl.core.tests.factories import StationLinkFactory

BATCH_TASK = "adl.core.tasks.process_station_link_batch"


class ActiveTasksViewTestCase(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(user)
        self.url = reverse("active_tasks")

    def get(self, url=None, active=None, reserved=None, side_effect=None):
        """GET the endpoint with the worker replies scripted."""
        inspect = MagicMock()
        if side_effect is not None:
            inspect.active.side_effect = side_effect
            inspect.reserved.side_effect = side_effect
        else:
            inspect.active.return_value = active
            inspect.reserved.return_value = reserved

        with patch("adl.monitoring.views.bounded_broker_connection") as connection, \
                patch("adl.monitoring.views.bounded_inspect",
                      return_value=inspect) as bounded_inspect:
            response = self.client.get(url or self.url)

        self.connection_factory = connection
        self.bounded_inspect = bounded_inspect
        return response

    def batch_task(self, task_id="abc123", network_id=None, station_ids=None,
                   time_start=1750000000.0):
        return {
            "id": task_id,
            "name": BATCH_TASK,
            "args": [network_id if network_id is not None else self.connection.id,
                     station_ids if station_ids is not None else [self.link.id]],
            "hostname": "adl-worker@host",
            "time_start": time_start,
        }


class BoundedInspectTests(ActiveTasksViewTestCase):
    def test_inspects_over_one_short_lived_bounded_connection(self):
        # Unbounded, on the app's default connection, these two calls cost
        # ~12 s against a refused broker and ~150 s against a blackholed one
        self.get(active={}, reserved={})

        self.connection_factory.assert_called_once_with()
        connection = self.connection_factory.return_value.__enter__.return_value
        self.assertEqual(self.bounded_inspect.call_count, 1)
        self.assertEqual(self.bounded_inspect.call_args.args, (connection,))

    def test_does_not_limit_the_replies(self):
        # limit truncates silently: with several ingestion workers it would
        # drop whole workers' tasks off the dashboard. Worth the second the
        # unlimited call costs — see _inspect_ingestion_tasks
        self.get(active={}, reserved={})

        self.assertNotIn("limit", self.bounded_inspect.call_args.kwargs)

    def test_a_broker_failure_answers_instead_of_erroring(self):
        response = self.get(side_effect=OSError("broker refused"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["workers_replied"])


class WorkerSilenceTests(ActiveTasksViewTestCase):
    def test_no_reply_is_reported_as_unknown_not_idle(self):
        # inspect has no empty-dict reply, so falsy means nobody answered
        response = self.get(active=None, reserved=None)

        body = response.json()
        self.assertFalse(body["workers_replied"])
        self.assertEqual(body["tasks"], [])

    def test_an_idle_worker_that_replies_is_reported_as_idle(self):
        response = self.get(active={"adl-worker@host": []},
                            reserved={"adl-worker@host": []})

        body = response.json()
        self.assertTrue(body["workers_replied"])
        self.assertEqual(body["count"], 0)

    def test_one_call_replying_is_enough_to_count_as_a_reply(self):
        response = self.get(active={"adl-worker@host": []}, reserved=None)

        self.assertTrue(response.json()["workers_replied"])


class TaskReportingTests(ActiveTasksViewTestCase):
    def test_reports_active_tasks_as_started_and_reserved_as_pending(self):
        response = self.get(
            active={"adl-worker@host": [self.batch_task(task_id="running")]},
            reserved={"adl-worker@host": [self.batch_task(task_id="queued")]},
        )

        statuses = {t["task_id"]: t["status"] for t in response.json()["tasks"]}
        self.assertEqual(statuses, {"running": "STARTED", "queued": "PENDING"})

    def test_status_is_per_worker_not_taken_from_the_first_worker_only(self):
        # A second worker's active tasks used to be compared against the
        # first worker's list and mislabelled PENDING
        response = self.get(
            active={
                "adl-worker-a@host": [self.batch_task(task_id="on-a")],
                "adl-worker-b@host": [self.batch_task(task_id="on-b")],
            },
            reserved={},
        )

        statuses = {t["task_id"]: t["status"] for t in response.json()["tasks"]}
        self.assertEqual(statuses, {"on-a": "STARTED", "on-b": "STARTED"})

    def test_resolves_station_names_for_the_batch(self):
        response = self.get(
            active={"adl-worker@host": [self.batch_task()]}, reserved={})

        task = response.json()["tasks"][0]
        self.assertEqual(task["stations"],
                         [{"id": self.link.id, "name": self.link.station.name}])

    def test_ignores_tasks_that_are_not_ingestion_batches(self):
        response = self.get(
            active={"adl-worker@host": [
                {"id": "other", "name": "adl.core.tasks.dispatch_station",
                 "args": [1, 2]},
            ]},
            reserved={},
        )

        self.assertEqual(response.json()["count"], 0)

    def test_a_task_with_unusable_args_is_skipped_rather_than_500ing(self):
        response = self.get(
            active={"adl-worker@host": [
                {"id": "odd", "name": BATCH_TASK, "args": []},
                {"id": "odder", "name": BATCH_TASK, "args": ["not-an-id", []]},
                self.batch_task(task_id="fine"),
            ]},
            reserved={},
        )

        self.assertEqual([t["task_id"] for t in response.json()["tasks"]], ["fine"])

    def test_network_filter_keeps_only_that_connections_tasks(self):
        other = StationLinkFactory().network_connection
        url = reverse("active_tasks_by_network", args=[self.connection.id])

        response = self.get(
            url=url,
            active={"adl-worker@host": [
                self.batch_task(task_id="mine"),
                self.batch_task(task_id="theirs", network_id=other.id),
            ]},
            reserved={},
        )

        self.assertEqual([t["task_id"] for t in response.json()["tasks"]], ["mine"])
