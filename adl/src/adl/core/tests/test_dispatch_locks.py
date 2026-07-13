import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from adl.core.tasks import dispatch_station_lock_key, get_active_dispatch_tasks
from .factories import StationLinkFactory, Wis2BoxUploadFactory


class GetActiveDispatchTasksTests(SimpleTestCase):
    def _run_with_active(self, active_reply):
        with patch("adl.core.tasks.app.control.inspect") as mock_inspect:
            mock_inspect.return_value.active.return_value = active_reply
            return get_active_dispatch_tasks()

    def test_maps_running_dispatch_tasks_by_channel_and_station(self):
        reply = {
            "dispatch-worker@host": [
                {
                    "name": "adl.core.tasks.dispatch_station",
                    "args": [7, 42],
                    "time_start": 1750000000.0,
                },
                {  # non-dispatch task on the same worker is ignored
                    "name": "adl.core.tasks.process_station_link_batch",
                    "args": [1, [2, 3]],
                    "time_start": 1750000001.0,
                },
            ]
        }

        result = self._run_with_active(reply)

        self.assertEqual(result, {(7, 42): 1750000000.0})

    def test_returns_none_when_no_worker_replies(self):
        self.assertIsNone(self._run_with_active(None))
        self.assertIsNone(self._run_with_active({}))

    def test_returns_none_instead_of_raising_on_broker_error(self):
        with patch("adl.core.tasks.app.control.inspect", side_effect=Exception("broker down")):
            self.assertIsNone(get_active_dispatch_tasks())


class LocksPageTestCase(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(user)
        self.url = reverse("dispatch_channel_locks", args=[self.channel.id])

    def hold_lock(self, station_link, ttl=300):
        key = dispatch_station_lock_key(self.channel.id, station_link.id)
        cache.set(key, "locked", timeout=ttl)
        self.addCleanup(cache.delete, key)
        return key

    def get_page(self, active_tasks):
        with patch("adl.core.views.get_active_dispatch_tasks", return_value=active_tasks):
            return self.client.get(self.url)


class LocksPageRowStatusTests(LocksPageTestCase):
    RUNNING_BADGE = ">RUNNING</span>"
    STALE_BADGE = ">STALE</span>"

    def test_lock_with_matching_active_task_shows_running(self):
        self.hold_lock(self.link)
        active = {(self.channel.id, self.link.id): time.time() - 65}

        response = self.get_page(active)

        self.assertContains(response, self.link.station.name)
        self.assertContains(response, self.RUNNING_BADGE)
        self.assertNotContains(response, self.STALE_BADGE)

    def test_lock_without_active_task_shows_stale(self):
        self.hold_lock(self.link)

        response = self.get_page(active_tasks={})

        self.assertContains(response, self.link.station.name)
        self.assertContains(response, self.STALE_BADGE)
        self.assertNotContains(response, self.RUNNING_BADGE)

    def test_no_worker_reply_shows_unknown_banner_and_disables_stale_clear(self):
        self.hold_lock(self.link)

        response = self.get_page(active_tasks=None)

        self.assertContains(response, ">UNKNOWN</span>")
        self.assertContains(response, "did not respond")
        # the safe clear button is disabled without worker evidence
        self.assertRegex(
            response.content.decode(),
            r'name="scope" value="stale">\s*<button[^>]*disabled',
        )

    def test_no_locks_shows_empty_state(self):
        response = self.get_page(active_tasks={})

        self.assertContains(response, "No dispatch locks currently held")
        self.assertNotContains(response, self.STALE_BADGE)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertIn("login", response["Location"])


class ResetScopeTests(LocksPageTestCase):
    def setUp(self):
        super().setUp()
        self.other_link = StationLinkFactory(
            network_connection=self.link.network_connection
        )
        self.reset_url = reverse("dispatch_channel_reset", args=[self.channel.id])

    def post_reset(self, scope, active_tasks):
        with patch("adl.core.views.get_active_dispatch_tasks", return_value=active_tasks), \
                patch("adl.core.views.perform_channel_dispatch") as mock_task:
            response = self.client.post(
                self.reset_url, {"scope": scope}, HTTP_REFERER="/admin/", follow=True
            )
        return response, mock_task

    def test_stale_scope_clears_only_stale_locks(self):
        running_key = self.hold_lock(self.link)
        stale_key = self.hold_lock(self.other_link)
        active = {(self.channel.id, self.link.id): time.time() - 10}

        response, mock_task = self.post_reset("stale", active_tasks=active)

        self.assertIsNone(cache.get(stale_key))  # cleared
        self.assertEqual(cache.get(running_key), "locked")  # kept
        mock_task.delay.assert_called_once_with(self.channel.id)

    def test_stale_scope_with_no_worker_reply_clears_nothing(self):
        key = self.hold_lock(self.link)

        response, mock_task = self.post_reset("stale", active_tasks=None)

        self.assertEqual(cache.get(key), "locked")  # untouched
        mock_task.delay.assert_not_called()
        rendered_messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("did not respond" in m for m in rendered_messages))

    def test_all_scope_clears_running_locks_too(self):
        running_key = self.hold_lock(self.link)
        active = {(self.channel.id, self.link.id): time.time() - 10}

        response, mock_task = self.post_reset("all", active_tasks=active)

        self.assertIsNone(cache.get(running_key))
        mock_task.delay.assert_called_once_with(self.channel.id)
