"""
Seam tests for the gate on the five manual-action admin views.

Permission is an HTTP-level property here — whether the task was enqueued,
the locks cleared or the destination dialled is only observable at the
view — so these drive the views through the test client and assert on the
side effect, never on the helper alone.

Each action is exercised three ways: refused for an admin-access user with
no change rights, allowed for one granted the *concrete* subclass's change
permission (what a deployment actually assigns), and allowed for one
granted only the polymorphic base's.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from adl.core.tasks import dispatch_station_lock_key
from .factories import StationLinkFactory, Wis2BoxUploadFactory


def make_user(username, *codenames):
    """An admin-access user holding exactly ``codenames`` and nothing else."""
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", password="test-pass"
    )
    user.user_permissions.add(
        Permission.objects.get(codename="access_admin"),
        *[Permission.objects.get(codename=c) for c in codenames],
    )
    return user


class ManualActionTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.connection)

    def login(self, *codenames):
        self.client.force_login(make_user("operator", *codenames))

    def assertRefused(self, url, **post_kwargs):
        """The view refused: Wagtail's admin wrapper turns the raised
        PermissionDenied into a redirect home, and the raw 403 surfaces on
        XHR."""
        response = self.client.post(url, follow=True, **post_kwargs)
        self.assertContains(response, "do not have permission")

        xhr = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                               **post_kwargs)
        self.assertEqual(xhr.status_code, 403)


class TriggerStationCollectionPermissionTests(ManualActionTestCase):
    """The one ingestion-side action: gated on its *connection*, which is
    what holds the credentials the run will use."""

    def setUp(self):
        super().setUp()
        self.url = reverse("trigger_station_collection", args=[self.link.id])

    def test_admin_access_alone_never_enqueues_a_run(self):
        self.login()

        with patch("adl.core.views.process_station_link_batch") as task:
            self.assertRefused(self.url)

        task.delay.assert_not_called()

    def test_connection_change_permission_enqueues_the_run(self):
        self.login("change_networkconnection")

        with patch("adl.core.views.process_station_link_batch") as task:
            response = self.client.post(self.url)

        task.delay.assert_called_once_with(self.connection.id, [self.link.id])
        self.assertEqual(response.status_code, 302)

    def test_dispatch_permission_does_not_unlock_the_ingestion_action(self):
        self.login("change_dispatchchannel")

        with patch("adl.core.views.process_station_link_batch") as task:
            self.assertRefused(self.url)

        task.delay.assert_not_called()

    def panel_context(self, user):
        from adl.core.components import StationLinkCollectionStatusPanel

        request = RequestFactory().get("/admin/")
        request.user = user
        return StationLinkCollectionStatusPanel().get_context_data(
            {"station_link": self.link, "request": request}
        )

    def test_button_is_hidden_for_unpermitted_users(self):
        context = self.panel_context(make_user("operator"))

        self.assertFalse(context["can_trigger_collection"])

    def test_button_is_shown_with_the_connection_change_permission(self):
        context = self.panel_context(
            make_user("permitted", "change_networkconnection"))

        self.assertTrue(context["can_trigger_collection"])

    def test_per_channel_dispatch_button_follows_that_channel(self):
        # Answered per channel, not once for the panel: a user may hold the
        # change permission on one channel type and not another
        context = self.panel_context(make_user("permitted", "change_wis2boxupload"))
        channels = {c.id: c for c in context["station_link"].dispatch_channels}

        self.assertTrue(channels[self.channel.id].can_trigger_dispatch)

    def test_per_channel_dispatch_button_is_hidden_without_the_permission(self):
        context = self.panel_context(
            make_user("permitted", "change_networkconnection"))
        channels = {c.id: c for c in context["station_link"].dispatch_channels}

        self.assertFalse(channels[self.channel.id].can_trigger_dispatch)


class ChannelActionPermissionTests(ManualActionTestCase):
    """The four dispatch-side actions. Each accepts the concrete channel
    type's change permission as well as the polymorphic base's."""

    def channel_url(self, name):
        return reverse(name, args=[self.channel.id])

    def test_dispatch_now_refuses_without_change_rights(self):
        self.login()

        with patch("adl.core.views.perform_channel_dispatch") as task:
            self.assertRefused(self.channel_url("dispatch_channel_dispatch_now"))

        task.delay.assert_not_called()

    def test_dispatch_now_accepts_the_concrete_channel_permission(self):
        self.login("change_wis2boxupload")

        with patch("adl.core.views.perform_channel_dispatch") as task:
            response = self.client.post(
                self.channel_url("dispatch_channel_dispatch_now"))

        task.delay.assert_called_once_with(self.channel.id)
        self.assertEqual(response.status_code, 302)

    def test_dispatch_now_accepts_the_base_channel_permission(self):
        self.login("change_dispatchchannel")

        with patch("adl.core.views.perform_channel_dispatch") as task:
            self.client.post(self.channel_url("dispatch_channel_dispatch_now"))

        task.delay.assert_called_once_with(self.channel.id)

    def test_reset_refuses_without_change_rights_and_leaves_locks_held(self):
        lock = dispatch_station_lock_key(self.channel.id, self.link.id)
        cache.set(lock, "locked", timeout=300)
        self.login()

        with patch("adl.core.views.perform_channel_dispatch") as task:
            self.assertRefused(self.channel_url("dispatch_channel_reset"))

        self.assertEqual(cache.get(lock), "locked")
        task.delay.assert_not_called()

    def test_reset_clears_locks_with_the_concrete_channel_permission(self):
        lock = dispatch_station_lock_key(self.channel.id, self.link.id)
        cache.set(lock, "locked", timeout=300)
        self.login("change_wis2boxupload")

        with patch("adl.core.views.perform_channel_dispatch"):
            self.client.post(self.channel_url("dispatch_channel_reset"))

        self.assertIsNone(cache.get(lock))

    def test_reset_clears_locks_with_the_base_channel_permission(self):
        lock = dispatch_station_lock_key(self.channel.id, self.link.id)
        cache.set(lock, "locked", timeout=300)
        self.login("change_dispatchchannel")

        with patch("adl.core.views.perform_channel_dispatch"):
            self.client.post(self.channel_url("dispatch_channel_reset"))

        self.assertIsNone(cache.get(lock))

    def test_station_dispatch_refuses_without_change_rights(self):
        url = reverse("trigger_station_dispatch",
                      args=[self.link.id, self.channel.id])
        self.login()

        with patch("adl.core.views.perform_channel_dispatch") as task:
            self.assertRefused(url)

        task.delay.assert_not_called()

    def test_station_dispatch_accepts_the_concrete_channel_permission(self):
        url = reverse("trigger_station_dispatch",
                      args=[self.link.id, self.channel.id])
        self.login("change_wis2boxupload")

        with patch("adl.core.views.perform_channel_dispatch") as task:
            self.client.post(url)

        task.delay.assert_called_once_with(self.channel.id, [self.link.id])

    def test_station_dispatch_accepts_the_base_channel_permission(self):
        url = reverse("trigger_station_dispatch",
                      args=[self.link.id, self.channel.id])
        self.login("change_dispatchchannel")

        with patch("adl.core.views.perform_channel_dispatch") as task:
            self.client.post(url)

        task.delay.assert_called_once_with(self.channel.id, [self.link.id])

    def test_test_connection_refuses_before_dialling_or_spending_a_press(self):
        self.login()
        url = self.channel_url("dispatch_channel_test_connection")

        with patch("adl.core.views.run_dispatch_connection_test") as probe:
            self.assertRefused(url)

        probe.assert_not_called()
        # The cooldown is claimed after the gate, so a refused press must
        # not spend the budget a permitted operator is about to need
        from adl.core.views import dispatch_test_cooldown_key
        self.assertIsNone(cache.get(dispatch_test_cooldown_key(self.channel)))

    def test_test_connection_dials_with_the_concrete_channel_permission(self):
        self.login("change_wis2boxupload")
        url = self.channel_url("dispatch_channel_test_connection")

        with patch("adl.core.views.run_dispatch_connection_test") as probe:
            probe.return_value = {"supported": True, "ok": True,
                                  "message": "connected", "latency_ms": 12}
            response = self.client.post(url)

        probe.assert_called_once()
        self.assertEqual(response.status_code, 302)

    def test_test_connection_dials_with_the_base_channel_permission(self):
        self.login("change_dispatchchannel")
        url = self.channel_url("dispatch_channel_test_connection")

        with patch("adl.core.views.run_dispatch_connection_test") as probe:
            probe.return_value = {"supported": True, "ok": True,
                                  "message": "connected", "latency_ms": 12}
            self.client.post(url)

        probe.assert_called_once()


class ChannelButtonVisibilityTests(ManualActionTestCase):
    """Hidden, not disabled — the source probe's precedent."""

    def test_station_links_page_hides_the_action_forms(self):
        self.login()

        response = self.client.get(
            reverse("dispatch_channel_station_links", args=[self.channel.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response, reverse("dispatch_channel_dispatch_now", args=[self.channel.id]))
        self.assertNotContains(
            response,
            reverse("dispatch_channel_test_connection", args=[self.channel.id]))

    def test_station_links_page_shows_the_action_forms_when_permitted(self):
        self.login("change_wis2boxupload")

        response = self.client.get(
            reverse("dispatch_channel_station_links", args=[self.channel.id]))

        self.assertContains(
            response, reverse("dispatch_channel_dispatch_now", args=[self.channel.id]))

    def test_locks_page_hides_the_reset_forms(self):
        self.login()

        with patch("adl.core.views.get_active_dispatch_tasks", return_value={}):
            response = self.client.get(
                reverse("dispatch_channel_locks", args=[self.channel.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response, reverse("dispatch_channel_reset", args=[self.channel.id]))

    def test_locks_page_shows_the_reset_forms_when_permitted(self):
        self.login("change_dispatchchannel")

        with patch("adl.core.views.get_active_dispatch_tasks", return_value={}):
            response = self.client.get(
                reverse("dispatch_channel_locks", args=[self.channel.id]))

        self.assertContains(
            response, reverse("dispatch_channel_reset", args=[self.channel.id]))
