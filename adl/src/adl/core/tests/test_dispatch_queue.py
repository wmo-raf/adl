from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django_celery_beat.models import PeriodicTask

from adl.core.tasks import (
    create_or_update_dispatch_channel_periodic_tasks,
    perform_channel_dispatch,
)
from .factories import StationLinkFactory, Wis2BoxUploadFactory


class DispatchQueueRoutingTests(TestCase):
    def test_dispatch_tasks_route_to_dispatch_queue(self):
        routes = settings.CELERY_TASK_ROUTES
        for task_name in (
                "adl.core.tasks.perform_channel_dispatch",
                "adl.core.tasks.dispatch_station",
                "adl.core.tasks.sweep_stale_dispatch_logs",
        ):
            self.assertEqual(routes[task_name]["queue"], "dispatch", task_name)

    def test_coordinator_enqueues_station_tasks_on_dispatch_queue(self):
        link = StationLinkFactory()
        channel = Wis2BoxUploadFactory()
        channel.network_connections.add(link.network_connection)

        with patch("adl.core.tasks.dispatch_station.apply_async") as mock_apply:
            perform_channel_dispatch(channel.id)

        self.assertEqual(mock_apply.call_args.kwargs["queue"], "dispatch")


class DispatchPeriodicTaskQueueTests(TestCase):
    def test_periodic_task_created_on_dispatch_queue(self):
        channel = Wis2BoxUploadFactory()

        create_or_update_dispatch_channel_periodic_tasks(channel)

        task = PeriodicTask.objects.get(args=f"[{channel.id}]")
        self.assertEqual(task.queue, "dispatch")

    def test_existing_periodic_task_migrates_from_old_queue_on_update(self):
        channel = Wis2BoxUploadFactory()
        create_or_update_dispatch_channel_periodic_tasks(channel)
        # simulate a pre-upgrade row stranded on the old queue
        PeriodicTask.objects.filter(args=f"[{channel.id}]").update(queue="adl")

        create_or_update_dispatch_channel_periodic_tasks(channel)

        task = PeriodicTask.objects.get(args=f"[{channel.id}]")
        self.assertEqual(task.queue, "dispatch")
