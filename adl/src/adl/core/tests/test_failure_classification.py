from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.test import SimpleTestCase, TestCase

from adl.core.classification import classify_failure, exception_class_name
from adl.core.models import Wis2BoxUpload
from adl.core.tasks import dispatch_station
from adl.monitoring.models import StationLinkActivityLog
from .factories import StationLinkFactory, Wis2BoxUploadFactory
from .helpers import make_test_plugin


class ClassifyFailureTests(SimpleTestCase):
    """Unit tests for the write-time classifier itself."""

    def test_known_type_matches_via_mro_table(self):
        self.assertEqual(classify_failure(ConnectionRefusedError()), ("TCP_REFUSED", 4))

    def test_subclass_of_known_type_matches_the_base(self):
        class VendorRefused(ConnectionRefusedError):
            pass

        self.assertEqual(classify_failure(VendorRefused()), ("TCP_REFUSED", 4))

    def test_unknown_type_declines(self):
        self.assertEqual(classify_failure(RuntimeError("boom")), (None, None))

    def test_plugin_stamp_wins_over_the_type_table(self):
        e = ConnectionRefusedError()
        e.adl_category = "AUTH_FAILED"
        e.adl_layer = 5
        self.assertEqual(classify_failure(e), ("AUTH_FAILED", 5))

    def test_plugin_category_outside_vocabulary_is_dropped_entirely(self):
        e = RuntimeError()
        e.adl_category = "SOMETHING_MADE_UP"
        e.adl_layer = 5
        self.assertEqual(classify_failure(e), (None, None))

    def test_invalid_plugin_category_on_known_type_falls_to_the_table(self):
        # A bogus plugin stamp is dropped, not fatal: the type table still
        # gets its say, per the decision's precedence (validate, then MRO).
        e = ConnectionRefusedError()
        e.adl_category = "SOMETHING_MADE_UP"
        self.assertEqual(classify_failure(e), ("TCP_REFUSED", 4))

    def test_tls_errors_carry_category_but_decline_the_layer(self):
        import ssl

        self.assertEqual(classify_failure(ssl.SSLError()), ("TLS_FAILURE", None))

    def test_invalid_plugin_layer_dropped_but_valid_category_kept(self):
        e = RuntimeError()
        e.adl_category = "AUTH_FAILED"
        e.adl_layer = 7
        self.assertEqual(classify_failure(e), ("AUTH_FAILED", None))

    def test_plugin_category_without_layer_is_honoured_with_layer_none(self):
        e = RuntimeError()
        e.adl_category = "PATH_NOT_FOUND"
        self.assertEqual(classify_failure(e), ("PATH_NOT_FOUND", None))

    def test_exception_class_name_is_fully_qualified(self):
        self.assertEqual(
            exception_class_name(RuntimeError("x")), "builtins.RuntimeError"
        )


class PullStampingTestCase(TestCase):
    """Task-seam tests, pull direction: process_station stamps its FAILED log."""

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

    def fail_with(self, exc):
        with patch.object(self.plugin, "get_station_data", side_effect=exc):
            self.plugin.process_station(self.link, bypass_lock=True)
        return StationLinkActivityLog.objects.get()

    def test_known_type_is_stamped(self):
        log = self.fail_with(ConnectionRefusedError("refused"))

        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(log.error_category, "TCP_REFUSED")
        self.assertEqual(log.error_layer, 4)
        self.assertEqual(log.exception_class, "builtins.ConnectionRefusedError")

    def test_ambiguous_type_declines_but_records_exception_class(self):
        log = self.fail_with(RuntimeError("something odd"))

        self.assertIsNone(log.error_category)
        self.assertIsNone(log.error_layer)
        self.assertEqual(log.exception_class, "builtins.RuntimeError")

    def test_plugin_supplied_attribute_is_honoured(self):
        e = RuntimeError("530 Login incorrect")
        e.adl_category = "AUTH_FAILED"
        e.adl_layer = 5

        log = self.fail_with(e)

        self.assertEqual(log.error_category, "AUTH_FAILED")
        self.assertEqual(log.error_layer, 5)
        self.assertEqual(log.exception_class, "builtins.RuntimeError")

    def test_invalid_plugin_value_is_dropped_not_stored(self):
        e = RuntimeError("boom")
        e.adl_category = "NOT_A_CATEGORY"
        e.adl_layer = 5

        log = self.fail_with(e)

        self.assertIsNone(log.error_category)
        self.assertIsNone(log.error_layer)

    def test_successful_run_leaves_all_three_null(self):
        self.plugin.records = []

        self.plugin.process_station(self.link, bypass_lock=True)

        log = StationLinkActivityLog.objects.get()
        self.assertIsNone(log.error_category)
        self.assertIsNone(log.error_layer)
        self.assertIsNone(log.exception_class)

    def test_soft_time_limit_records_exception_class(self):
        with patch.object(
            self.plugin, "get_station_data", side_effect=SoftTimeLimitExceeded()
        ):
            with self.assertRaises(SoftTimeLimitExceeded):
                self.plugin.process_station(self.link, bypass_lock=True)

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertIsNotNone(log.exception_class)
        self.assertIn("SoftTimeLimitExceeded", log.exception_class)


class PushStampingTests(TestCase):
    """Task-seam tests, push direction: dispatch_station stamps its FAILED log."""

    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        self.records = [{"station_id": self.link.station_id}]

    def fail_with(self, exc):
        with patch(
            "adl.core.tasks.get_station_dispatch_records", return_value=self.records
        ), patch.object(Wis2BoxUpload, "send_station_data", side_effect=exc):
            try:
                dispatch_station(self.channel.id, self.link.id)
            except type(exc):
                pass
        return StationLinkActivityLog.objects.get()

    def test_known_type_is_stamped(self):
        log = self.fail_with(ConnectionRefusedError("refused"))

        self.assertEqual(log.direction, "push")
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(log.error_category, "TCP_REFUSED")
        self.assertEqual(log.error_layer, 4)
        self.assertEqual(log.exception_class, "builtins.ConnectionRefusedError")

    def test_ambiguous_type_declines_but_records_exception_class(self):
        log = self.fail_with(RuntimeError("bucket unreachable"))

        self.assertIsNone(log.error_category)
        self.assertEqual(log.exception_class, "builtins.RuntimeError")

    def test_soft_time_limit_records_exception_class(self):
        log = self.fail_with(SoftTimeLimitExceeded())

        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertIsNotNone(log.exception_class)
        self.assertIn("SoftTimeLimitExceeded", log.exception_class)
