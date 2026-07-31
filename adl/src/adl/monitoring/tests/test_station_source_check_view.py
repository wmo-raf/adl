"""
Seam-3 tests for the station-scope source check: permission, cooldown
keying and the zero-match ``OK`` are HTTP-level by construction — a 403
versus a stored result versus a fresh run is not visible below the view.

The check itself is substituted at its one seam
(``adl.monitoring.views.health.run_station_source_check``); no test dials
a host. Keying is the point under test: the cooldown is ``(host, station
link)``, so one station's press must never answer for another's.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone as dj_tz

from adl.core.components import StationLinkSourceCheckPanel
from adl.core.models import StationLink
from adl.core.source_checks import (
    CHECK_STATION_SOURCE,
    ProbeStep,
    SourceCheckResult,
    SourceCheckStatus,
)
from adl.core.tests.factories import StationLinkFactory
from adl.monitoring.models import SourceProbeResult
from adl.monitoring.views.health import (
    source_probe_cooldown_key,
    station_source_check_cooldown_key,
)

ZERO_MATCH_STEP = ProbeStep(CHECK_STATION_SOURCE, 5, SourceCheckResult(
    status=SourceCheckStatus.OK,
    message="Resolved /data/2026/07/31; 0 file(s) matched.",
    latency_ms=180,
))


class StationCheckViewTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(self.user)
        self.url = reverse("station_link_check_source", args=[self.link.id])

        # The base StationLink implements no contract; the view must see it
        # as supported for the check paths under test
        supported = patch.object(StationLink, "station_source_check_supported", True)
        supported.start()
        self.addCleanup(supported.stop)

    def check(self, url=None, **kwargs):
        return self.client.post(url or self.url, follow=True, **kwargs)


class StationCheckPermissionTests(StationCheckViewTestCase):
    def make_plain_user(self):
        user = get_user_model().objects.create_user(
            username="operator", email="op@example.com", password="test-pass"
        )
        user.user_permissions.add(Permission.objects.get(codename="access_admin"))
        return user

    def test_post_without_change_permission_never_fires_the_check(self):
        self.client.force_login(self.make_plain_user())

        with patch("adl.monitoring.views.health.run_station_source_check") as check:
            response = self.client.post(self.url, follow=True)
            xhr_response = self.client.post(
                self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )

        check.assert_not_called()
        self.assertContains(response, "do not have permission")
        self.assertEqual(xhr_response.status_code, 403)


class StationCheckRunTests(StationCheckViewTestCase):
    def test_zero_matches_reports_ok_with_the_resolved_path(self):
        with patch("adl.monitoring.views.health.run_station_source_check",
                   return_value=ZERO_MATCH_STEP):
            response = self.check()

        self.assertEqual(response.status_code, 200)
        # Zero matches is success: the resolved path and match count reach
        # the operator, who judges better than a rule can
        self.assertContains(response, "/data/2026/07/31")
        self.assertContains(response, "0 file(s) matched")
        row = SourceProbeResult.objects.get()
        self.assertEqual(row.status, SourceCheckStatus.OK)

    def test_the_result_persists_with_the_station_link_fk_set(self):
        with patch("adl.monitoring.views.health.run_station_source_check",
                   return_value=ZERO_MATCH_STEP):
            self.check()

        row = SourceProbeResult.objects.get()
        self.assertEqual(row.station_link_id, self.link.id)
        self.assertEqual(row.connection_id, self.connection.id)
        self.assertEqual(row.check_id, CHECK_STATION_SOURCE)
        self.assertEqual(row.layer, "source")

    def test_a_failed_check_reports_the_failing_message(self):
        failed = ProbeStep(CHECK_STATION_SOURCE, 5, SourceCheckResult(
            status=SourceCheckStatus.FAILED, category="AUTH_FAILED",
            message="530 Login incorrect"))

        with patch("adl.monitoring.views.health.run_station_source_check",
                   return_value=failed):
            response = self.check()

        self.assertContains(response, "530 Login incorrect")

    def test_unsupported_station_link_gets_a_warning_and_no_row(self):
        with patch.object(StationLink, "station_source_check_supported", False), \
                patch("adl.monitoring.views.health.run_station_source_check") as check:
            response = self.check()

        check.assert_not_called()
        self.assertContains(response, "does not implement")
        self.assertFalse(SourceProbeResult.objects.exists())

    def test_a_raising_check_does_not_release_the_cooldown(self):
        with patch("adl.monitoring.views.health.run_station_source_check",
                   side_effect=RuntimeError("boom")) as check:
            first = self.check()
            second = self.check()

        self.assertEqual(check.call_count, 1)
        self.assertEqual(first.status_code, 200)
        self.assertContains(second, "has not recorded a result yet")


class StationCheckCooldownTests(StationCheckViewTestCase):
    def test_a_press_inside_the_cooldown_returns_the_stored_result_not_an_error(self):
        with patch("adl.monitoring.views.health.run_station_source_check",
                   return_value=ZERO_MATCH_STEP) as check:
            self.check()
            response = self.check()

        self.assertEqual(check.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "minute(s) ago")
        self.assertContains(response, "0 file(s) matched")

    def test_one_stations_press_does_not_answer_for_another(self):
        # Two links on the same connection share a host; keying on the host
        # alone would hand the second station the first one's verdict
        other = StationLinkFactory(network_connection=self.connection)
        other_url = reverse("station_link_check_source", args=[other.id])

        with patch("adl.monitoring.views.health.run_station_source_check",
                   return_value=ZERO_MATCH_STEP) as check:
            self.check()
            self.check(url=other_url)

        self.assertEqual(check.call_count, 2)
        self.assertEqual(
            SourceProbeResult.objects.filter(station_link=other).count(), 1)

    def test_checks_run_one_station_at_a_time_no_fan_out(self):
        # One press, one check, one row — nothing iterates sibling links
        StationLinkFactory(network_connection=self.connection)

        with patch("adl.monitoring.views.health.run_station_source_check",
                   return_value=ZERO_MATCH_STEP) as check:
            self.check()

        self.assertEqual(check.call_count, 1)
        self.assertEqual(SourceProbeResult.objects.count(), 1)


class StationCheckCooldownKeyTests(StationCheckViewTestCase):
    def test_key_is_host_and_station_link(self):
        self.connection.get_source_endpoint = lambda: ("ftp.example.org", 21)

        key = station_source_check_cooldown_key(self.link)

        self.assertIn("ftp.example.org", key)
        self.assertIn(str(self.link.id), key)

    def test_two_links_on_one_host_get_distinct_keys(self):
        other = StationLinkFactory(network_connection=self.connection)
        self.connection.get_source_endpoint = lambda: ("ftp.example.org", 21)
        other.network_connection = self.connection

        self.assertNotEqual(station_source_check_cooldown_key(self.link),
                            station_source_check_cooldown_key(other))

    def test_key_is_independent_of_the_connection_probe_key(self):
        self.connection.get_source_endpoint = lambda: ("ftp.example.org", 21)
        self.link.network_connection = self.connection

        self.assertNotEqual(station_source_check_cooldown_key(self.link),
                            source_probe_cooldown_key(self.connection))

    def test_unimplemented_endpoint_falls_back_to_connection_and_link(self):
        other = StationLinkFactory()

        self.assertNotEqual(station_source_check_cooldown_key(self.link),
                            station_source_check_cooldown_key(other))
        self.assertIn(str(self.link.id),
                      station_source_check_cooldown_key(self.link))


class InspectPanelTests(StationCheckViewTestCase):
    """The button and its result render on the station-link inspect page via
    the panel component; hidden, not disabled, when unpermitted or
    unsupported. Station-scope drift renders there as advisory."""

    def render_panel(self, user=None):
        request = RequestFactory().get("/")
        request.user = user or self.user
        return StationLinkSourceCheckPanel().render_html({
            "station_link": self.link,
            "request": request,
        })

    def test_button_renders_for_a_permitted_user_on_a_supported_link(self):
        html = self.render_panel()

        self.assertIn("Check station source now", html)
        self.assertIn(self.url, html)

    def test_button_is_hidden_when_unsupported(self):
        with patch.object(StationLink, "station_source_check_supported", False):
            html = self.render_panel()

        self.assertNotIn("Check station source now", html)
        self.assertNotIn(self.url, html)

    def test_button_is_hidden_for_an_unpermitted_user(self):
        plain = get_user_model().objects.create_user(
            username="viewer", email="viewer@example.com", password="test-pass"
        )

        html = self.render_panel(user=plain)

        self.assertNotIn("Check station source now", html)

    def test_latest_station_scope_result_renders_with_its_message(self):
        SourceProbeResult.objects.create(
            connection=self.connection, station_link=self.link,
            check_id=CHECK_STATION_SOURCE, layer="source",
            status=SourceCheckStatus.OK,
            message="Resolved /data/2026/07/31; 0 file(s) matched.",
            latency_ms=180, at=dj_tz.now(),
        )

        html = self.render_panel()

        self.assertIn("0 file(s) matched", html)

    def test_a_connection_scope_result_is_not_shown_as_the_stations(self):
        SourceProbeResult.objects.create(
            connection=self.connection, station_link=None,
            check_id="source_check", layer="source",
            status=SourceCheckStatus.OK, message="listed 3 files",
            at=dj_tz.now(),
        )

        html = self.render_panel()

        self.assertNotIn("listed 3 files", html)

    def test_station_scope_drift_renders_as_advisory(self):
        from adl.monitoring.health import ConfigurationDrift

        drifted = ConfigurationDrift(
            drifted=True, evaluated=True, fields=("file_pattern",),
            messages=("file pattern: this field is required",))
        with patch("adl.core.components.configuration_drift",
                   return_value=drifted):
            html = self.render_panel()

        self.assertIn("Configuration drift", html)
        self.assertIn("file pattern: this field is required", html)
