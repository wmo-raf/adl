from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from adl.core.tasks import dispatch_station_lock_key
from .factories import StationLinkFactory, Wis2BoxUploadFactory


class DispatchAdminActionTestCase(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(self.user)


class DispatchNowActionTests(DispatchAdminActionTestCase):
    def test_post_enqueues_channel_dispatch_and_redirects(self):
        url = reverse("dispatch_channel_dispatch_now", args=[self.channel.id])

        with patch("adl.core.views.perform_channel_dispatch") as mock_task:
            response = self.client.post(url, HTTP_REFERER="/admin/dispatch-channels/")

        mock_task.delay.assert_called_once_with(self.channel.id)
        self.assertEqual(response.status_code, 302)

    def test_get_does_not_enqueue(self):
        url = reverse("dispatch_channel_dispatch_now", args=[self.channel.id])

        with patch("adl.core.views.perform_channel_dispatch") as mock_task:
            response = self.client.get(url)

        mock_task.delay.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_anonymous_cannot_trigger(self):
        self.client.logout()
        url = reverse("dispatch_channel_dispatch_now", args=[self.channel.id])

        with patch("adl.core.views.perform_channel_dispatch") as mock_task:
            response = self.client.post(url)

        mock_task.delay.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])


class ResetChannelDispatchTests(DispatchAdminActionTestCase):
    def test_post_clears_only_this_channels_locks_and_enqueues(self):
        other_link = StationLinkFactory()
        other_channel = Wis2BoxUploadFactory()
        other_channel.network_connections.add(other_link.network_connection)

        own_lock = dispatch_station_lock_key(self.channel.id, self.link.id)
        other_lock = dispatch_station_lock_key(other_channel.id, other_link.id)
        cache.set(own_lock, "locked", timeout=300)
        cache.set(other_lock, "locked", timeout=300)
        self.addCleanup(cache.delete_many, [own_lock, other_lock])

        url = reverse("dispatch_channel_reset", args=[self.channel.id])
        with patch("adl.core.views.perform_channel_dispatch") as mock_task:
            response = self.client.post(url, HTTP_REFERER="/admin/dispatch-channels/")

        self.assertIsNone(cache.get(own_lock))  # cleared
        self.assertEqual(cache.get(other_lock), "locked")  # untouched
        mock_task.delay.assert_called_once_with(self.channel.id)
        self.assertEqual(response.status_code, 302)

    def test_anonymous_cannot_reset(self):
        self.client.logout()
        own_lock = dispatch_station_lock_key(self.channel.id, self.link.id)
        cache.set(own_lock, "locked", timeout=300)
        self.addCleanup(cache.delete, own_lock)

        url = reverse("dispatch_channel_reset", args=[self.channel.id])
        with patch("adl.core.views.perform_channel_dispatch") as mock_task:
            response = self.client.post(url)

        self.assertEqual(cache.get(own_lock), "locked")  # untouched
        mock_task.delay.assert_not_called()
        self.assertIn("login", response["Location"])


class ChannelPageButtonsTests(DispatchAdminActionTestCase):
    def test_station_links_page_renders_action_buttons(self):
        url = reverse("dispatch_channel_station_links", args=[self.channel.id])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dispatch now")
        self.assertContains(response, "Show active locks")
        self.assertContains(response, "Test connection")
        self.assertContains(response, reverse("dispatch_channel_dispatch_now", args=[self.channel.id]))
        self.assertContains(response, reverse("dispatch_channel_locks", args=[self.channel.id]))
        # Reset is no longer directly on this page — it lives on the locks page
        self.assertNotContains(response, reverse("dispatch_channel_reset", args=[self.channel.id]))
