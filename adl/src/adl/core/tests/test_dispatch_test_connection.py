import threading
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from adl.core.dispatch_checks import (
    normalise_dispatch_test_result,
    run_dispatch_connection_test,
)
from adl.core.models import DispatchChannel, Wis2BoxUpload
from adl.core.probes import PROBE_COOLDOWN_SECONDS, PROBE_WALL_CLOCK_SECONDS
from adl.core.views import dispatch_test_cooldown_key
from .factories import Wis2BoxUploadFactory


class BaseTestConnectionContractTests(TestCase):
    def test_base_channel_reports_not_supported_without_raising(self):
        channel = DispatchChannel.objects.create(name="Bare Channel")

        result = channel.test_connection()

        self.assertFalse(result["supported"])
        self.assertFalse(result["ok"])
        self.assertIn("not supported", result["message"])


class NormaliseDispatchTestResultTests(TestCase):
    """A channel type lives in its own repo and upgrades on its own schedule,
    so core never trusts what `test_connection()` hands back."""

    def test_conforming_result_passes_through_unchanged(self):
        result = normalise_dispatch_test_result(
            {"ok": True, "supported": True, "message": "reachable", "latency_ms": 12}
        )

        self.assertEqual(
            result,
            {"ok": True, "supported": True, "message": "reachable", "latency_ms": 12},
        )

    def test_missing_latency_falls_back_to_the_callers_measurement(self):
        """The admin renders the latency unconditionally on success, so an
        omitted one must not reach the operator as "(None ms)"."""
        result = normalise_dispatch_test_result(
            {"ok": False, "supported": True, "message": "bucket missing"}, measured_ms=7
        )

        self.assertEqual(result["latency_ms"], 7)
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "bucket missing")

    def test_unreadable_latency_falls_back_without_losing_the_verdict(self):
        result = normalise_dispatch_test_result(
            {"ok": True, "supported": True, "message": "reachable", "latency_ms": "fast"},
            measured_ms=7,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["latency_ms"], 7)

    def test_tuple_return_is_reported_as_malformed_not_indexed(self):
        """The shape `adl-s3-plugin` shipped: `result["supported"]` on a tuple
        raised TypeError and 500'd the admin button."""
        result = normalise_dispatch_test_result((True, "Connection successful"), channel_type="S3Upload")

        self.assertTrue(result["supported"])
        self.assertFalse(result["ok"])
        self.assertIn("S3Upload", result["message"])
        self.assertIn("tuple", result["message"])

    def test_result_missing_required_keys_is_reported_as_malformed(self):
        result = normalise_dispatch_test_result({"ok": True}, channel_type="S3Upload")

        self.assertTrue(result["supported"])
        self.assertFalse(result["ok"])
        self.assertIn("supported", result["message"])
        self.assertIn("message", result["message"])

    def test_none_return_is_reported_as_malformed(self):
        result = normalise_dispatch_test_result(None, channel_type="S3Upload")

        self.assertFalse(result["ok"])
        self.assertIn("NoneType", result["message"])


class RunDispatchConnectionTestTests(TestCase):
    def setUp(self):
        self.channel = Wis2BoxUploadFactory()

    def test_probe_return_is_normalised(self):
        with patch.object(Wis2BoxUpload, "test_connection", return_value=(True, "ok")):
            result = run_dispatch_connection_test(self.channel)

        self.assertFalse(result["ok"])
        self.assertTrue(result["supported"])
        self.assertIn("Wis2BoxUpload", result["message"])

    def test_a_channel_omitting_latency_still_reports_a_number(self):
        with patch.object(
            Wis2BoxUpload, "test_connection",
            return_value={"ok": True, "supported": True, "message": "reachable"},
        ):
            result = run_dispatch_connection_test(self.channel)

        self.assertTrue(result["ok"])
        self.assertIsInstance(result["latency_ms"], int)

    def test_raising_probe_is_reported_as_a_failure_not_propagated(self):
        with patch.object(
            Wis2BoxUpload, "test_connection", side_effect=RuntimeError("client blew up")
        ):
            result = run_dispatch_connection_test(self.channel)

        self.assertFalse(result["ok"])
        self.assertTrue(result["supported"])
        self.assertIn("RuntimeError", result["message"])
        self.assertIn("client blew up", result["message"])


class DispatchProbeWallClockTests(TestCase):
    """A channel lives in a plugin repo that upgrades on its own schedule, so
    the ~10 s in the base-class docstring is a contract, not a guarantee.
    `adl-s3-plugin` inherits boto3's 60 s connect + 60 s read + retries."""

    def setUp(self):
        self.channel = Wis2BoxUploadFactory()
        self.release = threading.Event()
        self.addCleanup(self.release.set)

    def blocking_probe(self, *args, **kwargs):
        self.release.wait(30)
        return {"ok": True, "supported": True, "message": "eventually", "latency_ms": 1}

    def test_the_default_budget_is_the_shared_wall_clock(self):
        """The same number on both sides, so the worst case an operator can
        experience is identical whichever button they press."""
        import inspect

        default = inspect.signature(run_dispatch_connection_test).parameters[
            "timeout_seconds"].default

        self.assertEqual(default, PROBE_WALL_CLOCK_SECONDS)

    def test_a_blocking_probe_reports_a_failure_naming_the_budget(self):
        with patch.object(Wis2BoxUpload, "test_connection", self.blocking_probe):
            result = run_dispatch_connection_test(self.channel, timeout_seconds=0.1)

        self.assertFalse(result["ok"])
        # `supported` stays True so the admin renders it as an error, not the
        # softer "not supported for this channel type"
        self.assertTrue(result["supported"])
        self.assertIn("0.1-second budget", result["message"])
        self.assertIn("Wis2BoxUpload", result["message"])

    def test_the_reported_latency_is_measured_not_the_budget_constant(self):
        with patch.object(Wis2BoxUpload, "test_connection", self.blocking_probe):
            result = run_dispatch_connection_test(self.channel, timeout_seconds=0.1)

        # Whatever was observed, not 100 assumed — honest if the bound ever
        # fires early
        self.assertIsInstance(result["latency_ms"], int)
        self.assertGreaterEqual(result["latency_ms"], 0)

    def test_the_bound_covers_client_construction_not_just_the_final_call(self):
        """The live s3 case: `S3Client.__init__` dials `head_bucket`, so the
        channel blocks before `test_connection`'s own call is reached."""

        def probe_blocking_in_get_client(*args, **kwargs):
            self.release.wait(30)  # stands in for the eager client constructor
            raise AssertionError("the destination-facing call is never reached")

        with patch.object(Wis2BoxUpload, "test_connection", probe_blocking_in_get_client):
            result = run_dispatch_connection_test(self.channel, timeout_seconds=0.1)

        self.assertFalse(result["ok"])
        self.assertIn("budget", result["message"])

    def test_an_abandoned_worker_does_not_extend_the_callers_wall_clock(self):
        """Fails if the executor were tidied up into a context manager:
        `with`-exit joins abandoned workers, so the caller would block until
        the stuck probe finished rather than returning at the bound."""
        started = time.monotonic()

        with patch.object(Wis2BoxUpload, "test_connection", self.blocking_probe):
            run_dispatch_connection_test(self.channel, timeout_seconds=0.1)

        elapsed = time.monotonic() - started

        # The worker is still blocked on `self.release` right now — the wait
        # is 30 s and the caller is already back
        self.assertFalse(self.release.is_set())
        self.assertLess(elapsed, 5)


class Wis2BoxTestConnectionTests(TestCase):
    def setUp(self):
        self.channel = Wis2BoxUploadFactory()

    def test_reachable_with_bucket_reports_ok_and_latency(self):
        with patch("adl.core.dispatchers.wis2box.Minio") as mock_minio:
            mock_minio.return_value.bucket_exists.return_value = True
            result = self.channel.test_connection()

        self.assertTrue(result["ok"])
        self.assertTrue(result["supported"])
        self.assertGreaterEqual(result["latency_ms"], 0)
        mock_minio.return_value.bucket_exists.assert_called_once_with("wis2box-incoming")

    def test_missing_bucket_reports_not_ok(self):
        with patch("adl.core.dispatchers.wis2box.Minio") as mock_minio:
            mock_minio.return_value.bucket_exists.return_value = False
            result = self.channel.test_connection()

        self.assertFalse(result["ok"])
        self.assertTrue(result["supported"])
        self.assertIn("wis2box-incoming", result["message"])

    def test_connection_error_reports_not_ok_without_raising(self):
        with patch("adl.core.dispatchers.wis2box.Minio") as mock_minio:
            mock_minio.return_value.bucket_exists.side_effect = Exception("connection refused")
            result = self.channel.test_connection()

        self.assertFalse(result["ok"])
        self.assertTrue(result["supported"])
        self.assertIn("connection refused", result["message"])


class TestConnectionAdminViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.channel = Wis2BoxUploadFactory()
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(self.user)
        self.url = reverse("dispatch_channel_test_connection", args=[self.channel.id])

    def test_post_runs_probe_and_redirects_with_result(self):
        probe_result = {"ok": True, "supported": True, "message": "reachable", "latency_ms": 12}
        with patch.object(Wis2BoxUpload, "test_connection", return_value=probe_result) as mock_probe:
            response = self.client.post(
                self.url, HTTP_REFERER="/admin/dispatch-channels/", follow=True
            )

        mock_probe.assert_called_once_with()
        rendered_messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("reachable" in m for m in rendered_messages))

    def test_malformed_probe_return_renders_an_error_instead_of_500ing(self):
        with patch.object(Wis2BoxUpload, "test_connection", return_value=(True, "Connection successful")):
            response = self.client.post(
                self.url, HTTP_REFERER="/admin/dispatch-channels/", follow=True
            )

        rendered_messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("Wis2BoxUpload" in m for m in rendered_messages))

    def test_anonymous_cannot_probe(self):
        self.client.logout()
        with patch.object(Wis2BoxUpload, "test_connection") as mock_probe:
            response = self.client.post(self.url)

        mock_probe.assert_not_called()
        self.assertIn("login", response["Location"])

    def test_a_blocking_channel_still_completes_the_request_as_an_error(self):
        """End to end: the operator gets a rendered error inside the budget
        rather than a wedged worker."""
        release = threading.Event()
        self.addCleanup(release.set)

        def blocking_probe(*args, **kwargs):
            release.wait(30)
            return {"ok": True, "supported": True, "message": "late", "latency_ms": 1}

        with patch.object(Wis2BoxUpload, "test_connection", blocking_probe), \
                patch("adl.core.views.run_dispatch_connection_test",
                      side_effect=lambda channel: run_dispatch_connection_test(
                          channel, timeout_seconds=0.1)):
            response = self.client.post(
                self.url, HTTP_REFERER="/admin/dispatch-channels/", follow=True
            )

        rendered = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("budget" in m for m in rendered), rendered)
        self.assertFalse(release.is_set())


class TestConnectionCooldownTests(TestCase):
    """The wall clock bounds a single press; nothing bounds ten of them. The
    cooldown is claimed before the probe fires, mirroring the source probe."""

    def setUp(self):
        cache.clear()
        self.channel = Wis2BoxUploadFactory()
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-pass"
        )
        self.client.force_login(self.user)
        self.url = reverse("dispatch_channel_test_connection", args=[self.channel.id])
        self.ok_result = {
            "ok": True, "supported": True, "message": "reachable", "latency_ms": 12,
        }

    def press(self):
        # Redirect back to a real admin page, so the assertions below read
        # the rendered messages off a 200 rather than an error page
        return self.client.post(
            self.url, HTTP_REFERER=reverse("wagtailadmin_home"), follow=True
        )

    def test_a_second_press_inside_the_cooldown_does_not_dial_the_destination(self):
        with patch.object(Wis2BoxUpload, "test_connection",
                          return_value=self.ok_result) as probe:
            self.press()
            response = self.press()

        self.assertEqual(probe.call_count, 1)
        self.assertEqual(response.status_code, 200)

        rendered = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("second(s) ago" in m for m in rendered), rendered)

    def test_a_press_inside_the_cooldown_is_a_message_not_an_error(self):
        with patch.object(Wis2BoxUpload, "test_connection", return_value=self.ok_result):
            self.press()
            response = self.press()

        levels = {m.level_tag for m in response.context["messages"]}
        self.assertNotIn("error", levels)
        self.assertIn("info", levels)

    def test_a_raising_probe_does_not_release_the_cooldown(self):
        """The destination was dialled either way, so the budget is spent."""
        with patch.object(Wis2BoxUpload, "test_connection",
                          side_effect=RuntimeError("boom")) as probe:
            self.press()
            self.press()

        self.assertEqual(probe.call_count, 1)

    def test_completion_does_not_extend_or_release_the_cooldown_ttl(self):
        key = dispatch_test_cooldown_key(self.channel)

        with patch.object(Wis2BoxUpload, "test_connection", return_value=self.ok_result), \
                patch.object(cache, "set") as cache_set, \
                patch.object(cache, "touch", create=True) as cache_touch, \
                patch.object(cache, "delete") as cache_delete:
            self.press()
            claim_after_first = cache.get(key)
            self.press()

        self.assertIsNotNone(claim_after_first)
        self.assertEqual(cache.get(key), claim_after_first)

        # The claim is written once, with `add`, before the probe fires and
        # is never touched again: no set/touch/delete may follow it, which is
        # what would extend (or release) the TTL. Unrelated admin-render
        # caching is ignored — only this key matters
        for mock in (cache_set, cache_touch, cache_delete):
            touched_keys = [call.args[0] for call in mock.call_args_list if call.args]
            self.assertNotIn(key, touched_keys)

    def test_a_channel_with_no_test_of_its_own_never_spends_a_budget(self):
        """The base implementation returns its verdict without going near the
        network, so pressing it costs nothing and must keep answering. Burning
        a budget here would tell the operator to wait instead of telling them
        again that this channel type has no test."""
        bare = DispatchChannel.objects.create(name="Bare Channel")
        url = reverse("dispatch_channel_test_connection", args=[bare.id])

        first = self.client.post(url, HTTP_REFERER=reverse("wagtailadmin_home"), follow=True)
        second = self.client.post(url, HTTP_REFERER=reverse("wagtailadmin_home"), follow=True)

        for response in (first, second):
            rendered = [str(m) for m in response.context["messages"]]
            self.assertTrue(any("not supported" in m for m in rendered), rendered)
            self.assertFalse(any("second(s) ago" in m for m in rendered), rendered)

    def test_the_cooldown_message_names_the_actual_cooldown(self):
        with patch.object(Wis2BoxUpload, "test_connection", return_value=self.ok_result):
            self.press()
            response = self.press()

        rendered = " ".join(str(m) for m in response.context["messages"])
        self.assertIn(f"every {PROBE_COOLDOWN_SECONDS} seconds", rendered)

    def test_an_unreadable_claim_reports_no_age_rather_than_a_made_up_one(self):
        key = dispatch_test_cooldown_key(self.channel)
        cache.add(key, "not-a-timestamp", timeout=PROBE_COOLDOWN_SECONDS)

        with patch.object(Wis2BoxUpload, "test_connection") as probe:
            response = self.press()

        probe.assert_not_called()
        rendered = " ".join(str(m) for m in response.context["messages"])
        self.assertIn("moments ago", rendered)
        self.assertNotIn("0 second(s)", rendered)

    def test_each_channel_gets_its_own_budget(self):
        other = Wis2BoxUploadFactory()

        self.assertNotEqual(dispatch_test_cooldown_key(self.channel),
                            dispatch_test_cooldown_key(other))

        with patch.object(Wis2BoxUpload, "test_connection",
                          return_value=self.ok_result) as probe:
            self.press()
            self.client.post(
                reverse("dispatch_channel_test_connection", args=[other.id]),
                HTTP_REFERER=reverse("wagtailadmin_home"), follow=True,
            )

        self.assertEqual(probe.call_count, 2)
