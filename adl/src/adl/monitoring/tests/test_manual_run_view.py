"""
Seam-3 tests for the manual re-run button: permission, in-flight, cooldown
and enqueue behaviour are HTTP-level by construction.

The enqueue is substituted at its one seam
(``run_network_plugin.apply_async``); the broker observation at its
(``adl.monitoring.views.health.get_ingestion_queue_health``). No test dials
a broker or runs a worker.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_tz

from adl.core.broker import IngestionQueueHealth, RunningIngestionTask
from adl.core.models import NetworkConnectionHeartbeat
from adl.core.tests.factories import StationLinkFactory
from adl.monitoring.views.health import (
    MANUAL_RUN_COOLDOWN_CAP_SECONDS,
    manual_run_cooldown_key,
)

UNOBSERVED = IngestionQueueHealth(queue_depth=None, worker_consuming=None,
                                  running_tasks=None)
IDLE = IngestionQueueHealth(queue_depth=0, worker_consuming=True,
                            running_tasks=())


def observed_running(connection_id, age_seconds=30.0):
    return IngestionQueueHealth(
        queue_depth=0,
        worker_consuming=True,
        running_tasks=(RunningIngestionTask(
            task_id="task-1",
            name="adl.core.tasks.run_network_plugin",
            args=(connection_id,),
            age_seconds=age_seconds,
        ),),
    )


class ManualRunViewTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(self.user)
        self.url = reverse("connection_run_now", args=[self.connection.id])
        self.page_url = reverse("connection_health", args=[self.connection.id])

        # No test dials the broker: the observation is substituted at the
        # view module's name for it
        broker = patch("adl.monitoring.views.health.get_ingestion_queue_health",
                       return_value=IDLE)
        self.broker = broker.start()
        self.addCleanup(broker.stop)

    def press(self, **kwargs):
        return self.client.post(self.url, follow=True, **kwargs)

    def enqueue_patch(self):
        return patch("adl.core.tasks.run_network_plugin.apply_async")


class ManualRunPermissionTests(ManualRunViewTestCase):
    def make_plain_user(self):
        user = get_user_model().objects.create_user(
            username="operator", email="op@example.com", password="test-pass"
        )
        user.user_permissions.add(Permission.objects.get(codename="access_admin"))
        return user

    def test_post_without_change_permission_never_enqueues(self):
        self.client.force_login(self.make_plain_user())

        with self.enqueue_patch() as enqueue:
            response = self.client.post(self.url, follow=True)
            xhr_response = self.client.post(
                self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )

        enqueue.assert_not_called()
        self.assertContains(response, "do not have permission")
        self.assertEqual(xhr_response.status_code, 403)

    def test_button_is_hidden_not_disabled_for_unpermitted_users(self):
        self.client.force_login(self.make_plain_user())

        response = self.client.get(self.page_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Run ingestion now")
        self.assertNotContains(response, self.url)

    def test_button_is_shown_to_permitted_users(self):
        response = self.client.get(self.page_url)

        self.assertContains(response, "Run ingestion now")

    def test_get_does_not_enqueue(self):
        with self.enqueue_patch() as enqueue:
            response = self.client.get(self.url)

        enqueue.assert_not_called()
        self.assertEqual(response.status_code, 302)


class ManualRunEnqueueTests(ManualRunViewTestCase):
    def test_press_enqueues_the_coordinator_on_the_ingestion_queue_with_manual_true(self):
        with self.enqueue_patch() as enqueue:
            response = self.press()

        self.assertEqual(response.status_code, 200)
        enqueue.assert_called_once()
        call = enqueue.call_args
        self.assertEqual(call.kwargs["args"], [self.connection.id])
        self.assertEqual(call.kwargs["kwargs"], {"manual": True})
        self.assertEqual(call.kwargs["queue"], "adl")

    def test_press_on_a_disabled_connection_does_not_enqueue(self):
        self.connection.plugin_processing_enabled = False
        self.connection.save()

        with self.enqueue_patch() as enqueue:
            response = self.press()

        enqueue.assert_not_called()
        self.assertContains(response, "disabled")

    def test_an_unanswering_broker_does_not_block_the_press(self):
        # Unknown is not "running": the cooldown still protects the source
        self.broker.return_value = UNOBSERVED

        with self.enqueue_patch() as enqueue:
            self.press()

        enqueue.assert_called_once()


class ManualRunInFlightTests(ManualRunViewTestCase):
    def test_press_while_a_run_is_in_flight_shows_the_running_one(self):
        self.broker.return_value = observed_running(self.connection.id,
                                                    age_seconds=120.0)

        with self.enqueue_patch() as enqueue:
            response = self.press()

        enqueue.assert_not_called()
        self.assertContains(response, "already running")

    def test_a_run_for_another_connection_does_not_block_the_press(self):
        self.broker.return_value = observed_running(self.connection.id + 1000)

        with self.enqueue_patch() as enqueue:
            self.press()

        enqueue.assert_called_once()

    def test_an_in_flight_press_does_not_claim_the_cooldown(self):
        self.broker.return_value = observed_running(self.connection.id)

        with self.enqueue_patch():
            self.press()

        self.assertIsNone(cache.get(manual_run_cooldown_key(self.connection)))


class ManualRunCooldownTests(ManualRunViewTestCase):
    def test_a_press_inside_the_cooldown_does_not_enqueue_again(self):
        with self.enqueue_patch() as enqueue:
            self.press()
            response = self.press()

        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "minute(s) ago")

    def test_cooldown_is_the_connection_interval(self):
        # interval 5 minutes -> 300 seconds, under the cap
        self.connection.plugin_processing_interval = 5
        self.connection.save()

        with self.enqueue_patch(), patch.object(cache, "add",
                                                wraps=cache.add) as add:
            self.press()

        claims = [c for c in add.call_args_list
                  if c.args[0] == manual_run_cooldown_key(self.connection)]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].kwargs.get("timeout"), 300)

    def test_cooldown_is_capped_at_fifteen_minutes(self):
        self.connection.plugin_processing_interval = 60 * 24
        self.connection.save()

        with self.enqueue_patch(), patch.object(cache, "add",
                                                wraps=cache.add) as add:
            self.press()

        claims = [c for c in add.call_args_list
                  if c.args[0] == manual_run_cooldown_key(self.connection)]
        self.assertEqual(claims[0].kwargs.get("timeout"),
                         MANUAL_RUN_COOLDOWN_CAP_SECONDS)

    def test_cooldown_key_is_connection_keyed(self):
        other = StationLinkFactory().network_connection

        self.assertNotEqual(manual_run_cooldown_key(self.connection),
                            manual_run_cooldown_key(other))
        self.assertIn(str(self.connection.id),
                      manual_run_cooldown_key(self.connection))


class ManualRunCaptionTests(ManualRunViewTestCase):
    def test_green_from_a_manual_run_is_captioned_on_the_page(self):
        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=dj_tz.now() - timedelta(hours=1),
            last_manual_run_at=dj_tz.now(),
        )

        response = self.client.get(self.page_url)

        self.assertContains(response, "triggered manually")

    def test_no_caption_when_the_latest_run_was_scheduled(self):
        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=dj_tz.now(),
            last_manual_run_at=dj_tz.now() - timedelta(hours=1),
        )

        response = self.client.get(self.page_url)

        self.assertNotContains(response, "triggered manually")

    def test_manual_run_before_any_scheduled_run_is_captioned(self):
        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=None,
            last_manual_run_at=dj_tz.now(),
        )

        response = self.client.get(self.page_url)

        self.assertContains(response, "triggered manually")

    def test_no_caption_with_no_heartbeat_row(self):
        response = self.client.get(self.page_url)

        self.assertNotContains(response, "triggered manually")
