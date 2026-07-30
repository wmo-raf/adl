"""
Seam-3 tests for the per-connection diagnostic page, following the pattern
of ``core/tests/test_dispatch_admin_actions.py``.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from adl.core.tests.factories import StationLinkFactory
from adl.monitoring.models import NetworkConnectionHealth


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


class ConnectionsListingLinkTests(HealthPageTestCase):
    def test_listing_dots_menu_links_to_the_diagnostic_page(self):
        # Both connections-listing views build their dots-menu through this
        # one helper; the polymorphic listing itself cannot render a
        # base-class NetworkConnection, so the helper is the testable seam
        from adl.core.utils import get_connection_list_more_buttons

        buttons = get_connection_list_more_buttons(self.connection)

        self.assertIn(self.url, [button.url for button in buttons])
