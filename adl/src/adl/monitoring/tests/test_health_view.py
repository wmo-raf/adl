"""
Seam-3 tests for the per-connection diagnostic page, following the pattern
of ``core/tests/test_dispatch_admin_actions.py``.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_timezone

from adl.core.tests.factories import StationLinkFactory
from adl.monitoring.models import (
    NetworkConnectionHealth,
    NetworkConnectionHealthTransition,
)


class HealthPageTestCase(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(self.user)
        self.url = reverse("connection_health", args=[self.connection.id])


class HealthPageRenderTests(HealthPageTestCase):
    def test_page_renders_on_day_one_with_no_heartbeat_and_no_activity(self):
        # No heartbeat, no schedule tick, no activity logs, no stored verdict —
        # the state of every connection on a fresh deployment
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.connection.name)
        self.assertContains(response, "Ingestion Diagnostic")
        self.assertContains(response, "status-badge")

    def test_get_has_no_write_side_effects(self):
        # Persisting the verdict belongs to the sweep task alone — refreshing
        # the page must not move `since` or append transitions
        self.client.get(self.url)

        self.assertFalse(NetworkConnectionHealth.objects.exists())

    def test_page_shows_the_sweep_recorded_verdict_when_one_exists(self):
        from adl.monitoring.health import evaluate_and_store_connection_health

        evaluate_and_store_connection_health(self.connection)

        response = self.client.get(self.url)

        self.assertContains(response, "In this state since")

    def test_disabled_connection_page_says_disabled(self):
        self.connection.plugin_processing_enabled = False
        self.connection.save()

        response = self.client.get(self.url)

        self.assertContains(response, "DISABLED")

    def test_unknown_connection_404s(self):
        response = self.client.get(reverse("connection_health", args=[self.connection.id + 1000]))

        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_page_uses_the_shared_badge_stylesheet(self):
        response = self.client.get(self.url)

        # Manifest storage may hash the filename, so match the basename only
        self.assertContains(response, "status_badges")

    def test_broker_library_versions_render_always_even_on_day_one(self):
        # Nothing else reports which broker stack an installation runs, so
        # the table renders whatever the ladder concluded — here with no
        # heartbeat at all, the worker column simply says so
        from adl.core.broker import local_library_versions

        response = self.client.get(self.url)

        self.assertContains(response, "Broker libraries")
        for name, version in local_library_versions().items():
            self.assertContains(response, name)
            if version:
                self.assertContains(response, version)
        self.assertContains(response, "not yet reported")

    def test_broker_library_versions_render_on_a_disabled_connection(self):
        # "Always" includes a short-circuited ladder — the stack question is
        # answerable regardless of what the checks concluded
        self.connection.plugin_processing_enabled = False
        self.connection.save()

        response = self.client.get(self.url)

        self.assertContains(response, "Broker libraries")

    def test_worker_column_shows_the_heartbeat_cached_stack(self):
        from adl.core.models import NetworkConnectionHeartbeat

        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=dj_timezone.now(),
            worker_versions={"celery": "5.6.99-worker", "kombu": "5.6.2",
                             "redis": "8.0.1"},
        )

        response = self.client.get(self.url)

        self.assertContains(response, "5.6.99-worker")


class ConnectionsListingLinkTests(HealthPageTestCase):
    def test_listing_dots_menu_links_to_the_diagnostic_page(self):
        # Both connections-listing views build their dots-menu through this
        # one helper; the polymorphic listing itself cannot render a
        # base-class NetworkConnection, so the helper is the testable seam
        from adl.core.utils import get_connection_list_more_buttons

        buttons = get_connection_list_more_buttons(self.connection)

        self.assertIn(self.url, [button.url for button in buttons])


class ListingHealthColumnTests(HealthPageTestCase):
    """The Connections listing surfaces the stored headline verdict. Both
    listing views render a base-class-safe cell through this one column; the
    polymorphic listing itself cannot render a base-class NetworkConnection
    (no viewset registers the base model), so the column is the testable
    seam — the same seam ``ConnectionsListingLinkTests`` uses."""

    def render_cell(self):
        from adl.core.table import ConnectionHealthColumn

        column = ConnectionHealthColumn("health", label="Health")
        return column.render_cell_html(
            self.connection, {"request": None, "table": None, "row": None}
        )

    def test_a_connection_with_no_health_row_yet_renders_a_verdict_cell(self):
        html = self.render_cell()

        self.assertIn("status-badge--muted", html)
        self.assertIn("No verdict yet", html)
        self.assertIn(self.url, html)

    def test_a_stored_verdict_renders_as_the_shared_badge(self):
        NetworkConnectionHealth.objects.create(
            connection=self.connection,
            status="FAILED",
            first_failing_layer="scheduler",
            headline_message="No schedule entry runs this connection.",
            since=dj_timezone.now(),
            evaluated_at=dj_timezone.now(),
        )
        self.connection.refresh_from_db()

        html = self.render_cell()

        self.assertIn("status-badge--failed", html)
        self.assertIn("FAILED", html)
        self.assertIn(self.url, html)

    def test_the_listing_cell_reads_the_stored_verdict_and_never_evaluates(self):
        with patch("adl.monitoring.health.evaluate_connection_health") as evaluate:
            self.render_cell()

        evaluate.assert_not_called()


class TransitionHistoryTests(HealthPageTestCase):
    """Transitions render at the bottom of the diagnostic page, paginated in
    place, read from the append-only log — never recomputed on read."""

    def transition(self, at, from_status="OK", to_status="FAILED",
                   from_layer=None, to_layer="scheduler"):
        return NetworkConnectionHealthTransition.objects.create(
            connection=self.connection,
            at=at,
            from_status=from_status,
            from_first_failing_layer=from_layer,
            to_status=to_status,
            to_first_failing_layer=to_layer,
        )

    def test_page_renders_with_no_transitions_at_all(self):
        # Day one: the sweep has never moved the verdict
        response = self.client.get(self.url)

        self.assertContains(response, "Verdict history")
        self.assertContains(response, "No verdict changes recorded yet")

    def test_transitions_render_with_both_verdicts_and_the_layer(self):
        self.transition(dj_timezone.now())

        response = self.client.get(self.url)

        self.assertContains(response, "health-transition")
        self.assertContains(response, "status-badge--failed")
        self.assertContains(response, "Scheduler")

    def test_the_first_recorded_verdict_row_says_so(self):
        # The row the sweep writes on creation has no prior verdict — it is
        # a starting point, not a change
        NetworkConnectionHealthTransition.objects.create(
            connection=self.connection,
            at=dj_timezone.now(),
            from_status=None,
            to_status="OK",
        )

        response = self.client.get(self.url)

        self.assertContains(response, "First recorded verdict")

    def test_transitions_paginate_in_place(self):
        now = dj_timezone.now()
        for i in range(25):
            self.transition(now - timedelta(minutes=i))

        page_one = self.client.get(self.url)
        page_two = self.client.get(self.url + "?p=2")

        self.assertEqual(page_one.content.decode().count('class="health-transition"'), 20)
        self.assertEqual(page_two.content.decode().count('class="health-transition"'), 5)
        self.assertContains(page_one, "Page 1 of 2")

    def test_flapping_is_a_count_of_changes_over_the_retained_window(self):
        now = dj_timezone.now()
        # The creation row is a starting point, not a flap
        NetworkConnectionHealthTransition.objects.create(
            connection=self.connection, at=now - timedelta(days=5),
            from_status=None, to_status="OK",
        )
        for i in range(3):
            self.transition(now - timedelta(days=i + 1))
        # Older than the 90-day retention window: not counted even if the
        # daily cleanup has not pruned it yet
        self.transition(now - timedelta(days=120))

        response = self.client.get(self.url)

        self.assertContains(response, "3 verdict changes")
        self.assertContains(response, "90 days")


class StationLinkDriftBannerTests(HealthPageTestCase):
    """Station-scope drift is advisory: it renders on the station link's own
    monitoring page and nowhere near the connection's headline."""

    def setUp(self):
        super().setUp()
        self.station_page_url = reverse("station_link_monitoring", args=[self.link.id])

    def test_a_valid_link_shows_no_drift_banner(self):
        response = self.client.get(self.station_page_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Configuration drift")

    def test_a_drifted_link_names_the_field_on_its_own_page(self):
        from unittest.mock import patch

        from adl.monitoring.health import ConfigurationDrift

        drift = ConfigurationDrift(
            drifted=True, evaluated=True,
            fields=("timezone_info",),
            messages=("timezone_info: This field cannot be blank.",),
        )
        with patch("adl.monitoring.views.configuration_drift", return_value=drift):
            response = self.client.get(self.station_page_url)

        self.assertContains(response, "Configuration drift")
        self.assertContains(response, "timezone_info")

    def test_the_misconfigured_precondition_row_renders_on_the_diagnostic_page(self):
        self.connection.plugin_processing_interval = 0
        self.connection.save()

        response = self.client.get(self.url)

        self.assertContains(response, "MISCONFIGURED")
        self.assertContains(response, "plugin_processing_interval")
