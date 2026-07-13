from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_tz

from adl.core.models import DispatchChannelHeartbeat
from adl.core.tasks import perform_channel_dispatch
from .factories import StationLinkFactory, Wis2BoxUploadFactory


class HeartbeatStampTests(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)

    def test_coordinator_stamps_heartbeat_every_run(self):
        with patch("adl.core.tasks.dispatch_station.apply_async"):
            perform_channel_dispatch(self.channel.id)

        heartbeat = DispatchChannelHeartbeat.objects.get(channel=self.channel)
        self.assertEqual(heartbeat.stations_spawned, 1)
        self.assertAlmostEqual(
            heartbeat.last_run_at, dj_tz.now(), delta=timedelta(seconds=10)
        )

        first_run_at = heartbeat.last_run_at
        with patch("adl.core.tasks.dispatch_station.apply_async"):
            perform_channel_dispatch(self.channel.id)

        self.assertEqual(DispatchChannelHeartbeat.objects.count(), 1)  # updated, not duplicated
        heartbeat.refresh_from_db()
        self.assertGreaterEqual(heartbeat.last_run_at, first_run_at)


class DispatchOverdueTests(TestCase):
    def setUp(self):
        # data_check_interval default = 10 minutes -> overdue threshold 20 minutes
        self.channel = Wis2BoxUploadFactory()
        self.now = dj_tz.now()

    def stamp(self, minutes_ago, channel=None):
        DispatchChannelHeartbeat.objects.create(
            channel=channel or self.channel,
            last_run_at=self.now - timedelta(minutes=minutes_ago),
        )

    def test_fresh_run_is_not_overdue(self):
        self.stamp(minutes_ago=1)
        self.assertFalse(self.channel.is_dispatch_overdue(now=self.now))

    def test_just_under_twice_interval_is_not_overdue(self):
        self.stamp(minutes_ago=19)
        self.assertFalse(self.channel.is_dispatch_overdue(now=self.now))

    def test_beyond_twice_interval_is_overdue(self):
        self.stamp(minutes_ago=21)
        self.assertTrue(self.channel.is_dispatch_overdue(now=self.now))

    def test_disabled_channel_is_never_overdue(self):
        self.channel.enabled = False
        self.stamp(minutes_ago=500)
        self.assertFalse(self.channel.is_dispatch_overdue(now=self.now))

    def test_never_ran_enabled_channel_is_overdue(self):
        self.assertTrue(self.channel.is_dispatch_overdue(now=self.now))

    def test_never_ran_disabled_channel_is_not_overdue(self):
        self.channel.enabled = False
        self.assertFalse(self.channel.is_dispatch_overdue(now=self.now))


class DispatchMonitoringApiTests(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(user)
        self.url = reverse("dispatch_activity", args=[self.channel.id])

    def test_channel_payload_flags_never_ran_channel_as_overdue(self):
        payload = self.client.get(self.url).json()["channel"]

        self.assertTrue(payload["overdue"])
        self.assertIsNone(payload["last_run_at"])
        self.assertIsNone(payload["stations_spawned"])

    def test_channel_payload_reports_fresh_heartbeat(self):
        DispatchChannelHeartbeat.objects.create(
            channel=self.channel, last_run_at=dj_tz.now(), stations_spawned=3
        )

        payload = self.client.get(self.url).json()["channel"]

        self.assertFalse(payload["overdue"])
        self.assertIsNotNone(payload["last_run_at"])
        self.assertEqual(payload["stations_spawned"], 3)


class ChannelPageHeartbeatTests(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(user)
        self.url = reverse("dispatch_channel_station_links", args=[self.channel.id])

    def test_never_ran_channel_shows_overdue_badge(self):
        response = self.client.get(self.url)

        self.assertContains(response, "OVERDUE")
        self.assertContains(response, "Never run")

    def test_fresh_channel_shows_last_run_without_badge(self):
        DispatchChannelHeartbeat.objects.create(
            channel=self.channel, last_run_at=dj_tz.now(), stations_spawned=2
        )

        response = self.client.get(self.url)

        self.assertNotContains(response, "OVERDUE")
        self.assertContains(response, "Last dispatch run")
