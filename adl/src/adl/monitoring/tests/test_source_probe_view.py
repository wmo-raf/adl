"""
Seam-3 tests for the on-demand source probe: permission, cooldown,
in-flight and TTL behaviour are HTTP-level by construction — a 403 versus a
200 versus a stored result is not visible below the view.

The probe itself is substituted at its one seam
(``adl.monitoring.views.health.run_source_probe``); no test dials a host.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_tz

from adl.core.models import NetworkConnection
from adl.core.source_checks import ProbeStep, SourceCheckResult, SourceCheckStatus
from adl.core.tests.factories import NetworkConnectionFactory, StationLinkFactory
from adl.monitoring.models import SourceProbeResult
from adl.monitoring.views.health import source_probe_cooldown_key

OK_STEPS = (
    ProbeStep("dns_resolution", 4, SourceCheckResult(
        status=SourceCheckStatus.OK, message="host resolved", latency_ms=12)),
    ProbeStep("tcp_connect", 4, SourceCheckResult(
        status=SourceCheckStatus.OK, message="tcp opened", latency_ms=30)),
    ProbeStep("source_check", 5, SourceCheckResult(
        status=SourceCheckStatus.OK, message="listed 3 files", latency_ms=200)),
)


class ProbeViewTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(self.user)
        self.url = reverse("connection_probe_source", args=[self.connection.id])
        self.page_url = reverse("connection_health", args=[self.connection.id])

        # The base connection implements no contract; the view must see it
        # as supported for the probe paths under test
        supported = patch.object(NetworkConnection, "source_probe_supported", True)
        supported.start()
        self.addCleanup(supported.stop)

    def probe(self, **kwargs):
        return self.client.post(self.url, follow=True, **kwargs)


class ProbePermissionTests(ProbeViewTestCase):
    def make_plain_user(self, *perms):
        user = get_user_model().objects.create_user(
            username="operator", email="op@example.com", password="test-pass"
        )
        user.user_permissions.add(
            Permission.objects.get(codename="access_admin"),
            *[Permission.objects.get(codename=p) for p in perms],
        )
        return user

    def test_post_without_change_permission_never_fires_the_probe(self):
        # Wagtail's admin wrapper turns the view's PermissionDenied into a
        # redirect home with an error message; the raw 403 surfaces on XHR
        self.client.force_login(self.make_plain_user())

        with patch("adl.monitoring.views.health.run_source_probe") as probe:
            response = self.client.post(self.url, follow=True)
            xhr_response = self.client.post(
                self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )

        probe.assert_not_called()
        self.assertContains(response, "do not have permission")
        self.assertEqual(xhr_response.status_code, 403)

    def test_button_is_hidden_not_disabled_for_unpermitted_users(self):
        self.client.force_login(self.make_plain_user())

        response = self.client.get(self.page_url)

        self.assertEqual(response.status_code, 200)
        # Hidden means absent: no probe form, no disabled variant of it
        self.assertNotContains(response, "Probe source now")
        self.assertNotContains(response, self.url)

    def test_button_is_hidden_when_the_plugin_has_no_contract(self):
        # Undo the class-level patch for this one test
        connection = StationLinkFactory().network_connection
        with patch.object(NetworkConnection, "source_probe_supported", False):
            response = self.client.get(
                reverse("connection_health", args=[connection.id])
            )

        self.assertNotContains(response, "Probe source now")

    def test_button_is_shown_to_permitted_users_on_a_supported_connection(self):
        response = self.client.get(self.page_url)

        self.assertContains(response, "Probe source now")


class ProbeRunTests(ProbeViewTestCase):
    def test_a_probe_persists_one_row_per_step_with_the_producer_stamped_layer(self):
        with patch("adl.monitoring.views.health.run_source_probe",
                   return_value=OK_STEPS):
            response = self.probe()

        self.assertEqual(response.status_code, 200)
        rows = SourceProbeResult.objects.filter(connection=self.connection)
        self.assertEqual(rows.count(), 3)
        self.assertEqual(rows.get(check_id="dns_resolution").layer, "network")
        self.assertEqual(rows.get(check_id="source_check").layer, "source")
        for row in rows:
            self.assertIsNone(row.station_link)

    def test_a_failed_probe_reports_the_failing_step_message(self):
        failed = (ProbeStep("dns_resolution", 4, SourceCheckResult(
            status=SourceCheckStatus.FAILED, category="DNS_FAILURE",
            message="ftp.example.org did not resolve")),)

        with patch("adl.monitoring.views.health.run_source_probe",
                   return_value=failed):
            response = self.probe()

        self.assertContains(response, "did not resolve")


class ProbeCooldownTests(ProbeViewTestCase):
    def test_a_press_inside_the_cooldown_returns_the_stored_result_not_an_error(self):
        with patch("adl.monitoring.views.health.run_source_probe",
                   return_value=OK_STEPS) as probe:
            self.probe()
            response = self.probe()

        # The probe fired exactly once; the second press got the shared
        # result with its age and origin, as a 200
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "on-demand probe")
        self.assertContains(response, "minute(s) ago")

    def test_a_press_while_in_flight_reports_the_in_flight_state(self):
        # Another user's probe claimed the cooldown but has produced no
        # result rows yet
        key = source_probe_cooldown_key(self.connection)
        cache.add(key, dj_tz.now().isoformat(), timeout=60)

        with patch("adl.monitoring.views.health.run_source_probe") as probe:
            response = self.probe()

        probe.assert_not_called()
        self.assertContains(response, "has not recorded a result yet")

    def test_a_raising_probe_does_not_release_the_cooldown(self):
        with patch("adl.monitoring.views.health.run_source_probe",
                   side_effect=RuntimeError("boom")) as probe:
            first = self.probe()
            second = self.probe()

        # The budget was spent by the crashed dial; the second press is
        # answered from the claim, not by a fresh probe
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(first.status_code, 200)
        self.assertContains(second, "has not recorded a result yet")

    def test_completion_does_not_extend_the_cooldown_ttl(self):
        # The claim is written once, with `add`, before the probe fires and
        # is never touched again: no set/touch/delete may follow, which is
        # what would extend (or release) the TTL
        key = source_probe_cooldown_key(self.connection)

        with patch("adl.monitoring.views.health.run_source_probe",
                   return_value=OK_STEPS), \
                patch.object(cache, "set") as cache_set, \
                patch.object(cache, "touch", create=True) as cache_touch, \
                patch.object(cache, "delete") as cache_delete:
            self.probe()
            claim_after_first = cache.get(key)
            self.probe()

        self.assertIsNotNone(claim_after_first)
        self.assertEqual(cache.get(key), claim_after_first)
        cache_set.assert_not_called()
        cache_touch.assert_not_called()
        cache_delete.assert_not_called()


class CooldownKeyTests(ProbeViewTestCase):
    def test_key_is_the_source_host_without_the_port(self):
        self.connection.get_source_endpoint = lambda: ("ftp.example.org", 21)

        key = source_probe_cooldown_key(self.connection)

        self.assertIn("ftp.example.org", key)
        self.assertNotIn("21", key)

    def test_two_connections_to_the_same_host_share_one_budget(self):
        other = NetworkConnectionFactory()
        self.connection.get_source_endpoint = lambda: ("ftp.example.org", 21)
        other.get_source_endpoint = lambda: ("ftp.example.org", 2121)

        self.assertEqual(source_probe_cooldown_key(self.connection),
                         source_probe_cooldown_key(other))

    def test_a_raising_endpoint_falls_back_instead_of_erroring(self):
        def boom():
            raise RuntimeError("bad endpoint config")

        self.connection.get_source_endpoint = boom

        key = source_probe_cooldown_key(self.connection)

        self.assertIn(str(self.connection.id), key)

    def test_unimplemented_endpoint_falls_back_to_the_connection_id(self):
        other = NetworkConnectionFactory()

        self.assertNotEqual(source_probe_cooldown_key(self.connection),
                            source_probe_cooldown_key(other))
        self.assertIn(str(self.connection.id),
                      source_probe_cooldown_key(self.connection))
