"""
Seam tests: every write point that stores an exception's text redacts it.

The unit tests in ``test_redaction`` prove the redactor; these prove it is
actually reached on each path that persists or serves failure text — the
regression that matters, because the leak was never in the redactor but in
a write that forgot to call one.
"""

from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from adl.core.dispatch_checks import (
    normalise_dispatch_test_result,
    run_dispatch_connection_test,
)
from adl.core.models import Wis2BoxUpload
from adl.core.source_checks import (
    SourceCheckResult,
    SourceCheckStatus,
    normalise_source_check_result,
)
from adl.core.logging import TaskLogger
from adl.core.tasks import dispatch_station
from adl.monitoring.models import StationLinkActivityLog
from .factories import StationLinkFactory, Wis2BoxUploadFactory
from .helpers import make_test_plugin

LEAKY_ERROR = (
    "401 Client Error: Unauthorized for url: "
    "https://api.example.org/data?token=s3cr3t-value&station=42"
)


class PullWritePointTests(TestCase):
    """process_station's FAILED log carries no credential."""

    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()

        window = (
            datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc),
            datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc),
        )
        patcher = patch.object(
            type(self.plugin), "get_dates_for_station", return_value=window
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_query_string_token_is_redacted_in_the_stored_message(self):
        with patch.object(
            self.plugin, "get_station_data", side_effect=RuntimeError(LEAKY_ERROR)
        ):
            self.plugin.process_station(self.link, bypass_lock=True)

        log = StationLinkActivityLog.objects.get()
        self.assertNotIn("s3cr3t-value", log.message)
        self.assertIn("token=***", log.message)
        # The diagnostic part of the message survives.
        self.assertIn("401 Client Error", log.message)
        self.assertIn("station=42", log.message)


class PushWritePointTests(TestCase):
    """dispatch_station's FAILED log carries no credential."""

    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)

    def test_credential_is_redacted_in_the_stored_message(self):
        error = RuntimeError("upload rejected (password=hunter2)")
        with patch(
            "adl.core.tasks.get_station_dispatch_records",
            return_value=[{"station_id": self.link.station_id}],
        ), patch.object(Wis2BoxUpload, "send_station_data", side_effect=error):
            with self.assertRaises(RuntimeError):
                dispatch_station(self.channel.id, self.link.id)

        log = StationLinkActivityLog.objects.get()
        self.assertNotIn("hunter2", log.message)
        self.assertIn("password=***", log.message)


class SourceCheckWritePointTests(SimpleTestCase):
    """A plugin's own source-check message is redacted before it is stored."""

    def test_plugin_message_is_redacted(self):
        result = normalise_source_check_result(
            SourceCheckResult(status=SourceCheckStatus.FAILED, message=LEAKY_ERROR)
        )

        self.assertNotIn("s3cr3t-value", result.message)
        self.assertIn("token=***", result.message)

    def test_status_and_category_still_survive_normalisation(self):
        result = normalise_source_check_result(
            SourceCheckResult(
                status=SourceCheckStatus.FAILED,
                category="AUTH_FAILED",
                message="no secret here",
            )
        )

        self.assertEqual(result.status, SourceCheckStatus.FAILED)
        self.assertEqual(result.category, "AUTH_FAILED")
        self.assertEqual(result.message, "no secret here")

    def test_unknown_category_is_still_dropped(self):
        result = normalise_source_check_result(
            SourceCheckResult(status=SourceCheckStatus.FAILED, category="MADE_UP")
        )

        self.assertIsNone(result.category)


class DispatchTestConnectionWritePointTests(SimpleTestCase):
    """A channel's test-connection message is redacted for the operator."""

    def test_channel_supplied_message_is_redacted(self):
        result = normalise_dispatch_test_result(
            {"ok": False, "supported": True, "message": LEAKY_ERROR, "latency_ms": 5}
        )

        self.assertNotIn("s3cr3t-value", result["message"])
        self.assertIn("token=***", result["message"])

    def test_raised_exception_text_is_redacted(self):
        class Channel:
            id = 1

            def test_connection(self):
                raise RuntimeError(LEAKY_ERROR)

        result = run_dispatch_connection_test(Channel())

        self.assertFalse(result["ok"])
        self.assertNotIn("s3cr3t-value", result["message"])
        self.assertIn("token=***", result["message"])


class StreamedLogTests(SimpleTestCase):
    """What leaves the process for a browser carries no credential."""

    def test_sse_message_is_redacted_but_the_local_log_is_not(self):
        logger = TaskLogger(task_id="abc", plugin_label="Test")

        with patch("adl.core.logging.send_event") as send_event, \
                patch.object(logger, "standard_logger") as standard_logger:
            logger.error("fetch failed: %s", LEAKY_ERROR)

        streamed = send_event.call_args.args[2]["message"]
        self.assertNotIn("s3cr3t-value", streamed)
        self.assertIn("token=***", streamed)

        # The worker's own log keeps the full text — it is not a shared surface.
        logged = standard_logger.error.call_args.args[0]
        self.assertIn("s3cr3t-value", logged)
