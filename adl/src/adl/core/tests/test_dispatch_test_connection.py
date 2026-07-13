from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from adl.core.models import DispatchChannel, Wis2BoxUpload
from .factories import Wis2BoxUploadFactory


class BaseTestConnectionContractTests(TestCase):
    def test_base_channel_reports_not_supported_without_raising(self):
        channel = DispatchChannel.objects.create(name="Bare Channel")

        result = channel.test_connection()

        self.assertFalse(result["supported"])
        self.assertFalse(result["ok"])
        self.assertIn("not supported", result["message"])


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

    def test_anonymous_cannot_probe(self):
        self.client.logout()
        with patch.object(Wis2BoxUpload, "test_connection") as mock_probe:
            response = self.client.post(self.url)

        mock_probe.assert_not_called()
        self.assertIn("login", response["Location"])
