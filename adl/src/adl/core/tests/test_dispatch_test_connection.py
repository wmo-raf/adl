from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from adl.core.dispatch_checks import (
    normalise_dispatch_test_result,
    run_dispatch_connection_test,
)
from adl.core.models import DispatchChannel, Wis2BoxUpload
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
