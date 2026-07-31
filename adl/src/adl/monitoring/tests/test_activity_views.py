"""The two activity views must render the shared status computation.

These are wiring tests, not a second copy of the status rules — those live in
``test_status``. What is asserted here is that each view feeds the right
domain rows into the helper and renders what comes back.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_timezone

from adl.core.models import StationChannelDispatchStatus
from adl.core.registries import plugin_registry
from adl.core.tests.factories import (
    NetworkConnectionFactory,
    StationLinkFactory,
    Wis2BoxUploadFactory,
)
from adl.core.tests.helpers import make_test_plugin
from adl.monitoring.models import StationLinkActivityLog


class ActivityViewStatusTestCase(TestCase):
    def setUp(self):
        self.now = dj_timezone.now()
        # The views live under the Wagtail admin URLs, so they need admin access.
        user = get_user_model().objects.create_superuser(
            username="monitor", email="monitor@example.com", password="pw"
        )
        self.client.force_login(user)

    def ago(self, **kwargs):
        return self.now - timedelta(**kwargs)


class NetworkConnectionActivityViewTests(ActivityViewStatusTestCase):
    def setUp(self):
        super().setUp()
        # 15 min interval -> 45 min pipeline tolerance, 60 min / 180 min freshness
        # The view reports the connection's plugin label, so the stub must be registered.
        plugin = make_test_plugin()
        plugin_registry.register(plugin)
        self.addCleanup(plugin_registry.unregister, plugin)

        self.connection = NetworkConnectionFactory(plugin_processing_interval=15, is_daily_data=False)
        self.station_link = StationLinkFactory(network_connection=self.connection)

    def log(self, time, success=True):
        StationLinkActivityLog.objects.create(
            station_link=self.station_link, direction="pull", time=time, success=success
        )

    def get(self):
        response = self.client.get(
            reverse("network_connection_activity", args=(self.connection.id,))
        )
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_never_checked_station_warns(self):
        data = self.get()

        station = data["stations"][0]
        self.assertEqual(station["pipeline_status"], "warning")
        self.assertEqual(station["data_status"], "warning")
        self.assertEqual(data["summary"], {"active": 0, "warning": 1, "error": 0})

    def test_failed_last_run_is_an_error(self):
        self.log(self.ago(minutes=5), success=False)

        data = self.get()

        self.assertEqual(data["stations"][0]["pipeline_status"], "error")
        self.assertEqual(data["summary"], {"active": 0, "warning": 0, "error": 1})

    def test_successful_run_beyond_tolerance_warns(self):
        self.log(self.ago(minutes=50))

        data = self.get()

        self.assertEqual(data["stations"][0]["pipeline_status"], "warning")

    def test_recent_successful_run_is_active(self):
        self.log(self.ago(minutes=5))

        data = self.get()

        self.assertEqual(data["stations"][0]["pipeline_status"], "active")

    def test_connection_payload_carries_a_health_verdict_before_the_first_sweep(self):
        # No health row yet — the day-one state. The panel still renders a
        # verdict slot, with the diagnostic link always present.
        data = self.get()

        health = data["connection"]["health"]
        self.assertIsNone(health["status"])
        self.assertEqual(
            health["diagnostic_url"],
            reverse("connection_health", args=(self.connection.id,)),
        )

    def test_connection_payload_reports_the_stored_verdict(self):
        from adl.monitoring.models import NetworkConnectionHealth

        NetworkConnectionHealth.objects.create(
            connection=self.connection,
            status="FAILED",
            first_failing_layer="scheduler",
            headline_message="No schedule entry runs this connection.",
            since=self.ago(hours=3),
            evaluated_at=self.now,
        )

        data = self.get()

        health = data["connection"]["health"]
        self.assertEqual(health["status"], "FAILED")
        self.assertEqual(health["first_failing_layer"], "scheduler")
        self.assertIsNotNone(health["since"])

    def test_the_panel_read_never_triggers_an_evaluation(self):
        # The panel reads the stored verdict; evaluating belongs to the sweep
        from unittest.mock import patch

        with patch("adl.monitoring.health.evaluate_connection_health") as evaluate:
            self.get()

        evaluate.assert_not_called()


class DispatchChannelMonitoringViewTests(ActivityViewStatusTestCase):
    def setUp(self):
        super().setUp()
        # 10 min check interval -> 30 min pipeline tolerance, 40 min / 120 min freshness
        self.channel = Wis2BoxUploadFactory(data_check_interval=10, send_aggregated_data=False)
        self.station_link = StationLinkFactory()
        self.channel.network_connections.add(self.station_link.network_connection)

    def log(self, time, success=True):
        StationLinkActivityLog.objects.create(
            station_link=self.station_link,
            dispatch_channel=self.channel,
            direction="push",
            time=time,
            success=success,
        )

    def sent(self, time):
        StationChannelDispatchStatus.objects.create(
            channel=self.channel, station=self.station_link.station, last_sent_obs_time=time
        )

    def get(self):
        response = self.client.get(reverse("dispatch_activity", args=(self.channel.id,)))
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_never_attempted_station_warns(self):
        data = self.get()

        station = data["stations"][0]
        self.assertEqual(station["pipeline_status"], "warning")
        self.assertEqual(station["data_status"], "warning")
        self.assertEqual(data["summary"], {"active": 0, "warning": 1, "error": 0})

    def test_failed_attempt_is_an_error(self):
        self.log(self.ago(minutes=5), success=False)
        self.sent(self.ago(minutes=5))

        data = self.get()

        self.assertEqual(data["stations"][0]["pipeline_status"], "error")
        self.assertEqual(data["stations"][0]["data_status"], "active")
        self.assertEqual(data["summary"], {"active": 0, "warning": 0, "error": 1})

    def test_recent_attempt_and_fresh_send_is_active(self):
        self.log(self.ago(minutes=5))
        self.sent(self.ago(minutes=5))

        data = self.get()

        station = data["stations"][0]
        self.assertEqual(station["pipeline_status"], "active")
        self.assertEqual(station["data_status"], "active")
        self.assertEqual(data["summary"], {"active": 1, "warning": 0, "error": 0})

    def test_stale_send_is_a_data_error(self):
        self.log(self.ago(minutes=5))
        self.sent(self.ago(minutes=200))

        data = self.get()

        self.assertEqual(data["stations"][0]["data_status"], "error")
        self.assertEqual(data["summary"], {"active": 0, "warning": 0, "error": 1})
