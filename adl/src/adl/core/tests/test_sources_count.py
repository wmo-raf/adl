from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from django.test import TestCase

from adl.monitoring.models import StationLinkActivityLog
from .factories import StationLinkFactory
from .helpers import make_test_plugin


class SourcesCountTestCase(TestCase):
    """Shared fixture: one stub plugin and one station link, with the plugin's
    date-window resolution stubbed so tests exercise only the sources-count
    handover seam."""

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

    def run_with_reported_count(self, value):
        """Run process_station with a get_station_data that sets the duck-typed
        attribute the way a real plugin would — while listing."""

        def fetch(station_link, start_date=None, end_date=None):
            station_link.adl_sources_count = value
            return []

        with patch.object(self.plugin, "get_station_data", side_effect=fetch):
            self.plugin.process_station(self.link, bypass_lock=True)

        return StationLinkActivityLog.objects.get()


class SourcesCountRecordingTests(SourcesCountTestCase):
    def test_plugin_that_does_not_report_leaves_null(self):
        self.plugin.records = []

        self.plugin.process_station(self.link, bypass_lock=True)

        log = StationLinkActivityLog.objects.get()
        self.assertIsNone(log.sources_count)

    def test_zero_is_stored_as_zero_not_null(self):
        log = self.run_with_reported_count(0)
        self.assertEqual(log.sources_count, 0)

    def test_positive_count_is_stored(self):
        log = self.run_with_reported_count(7)
        self.assertEqual(log.sources_count, 7)

    def test_negative_degrades_to_null(self):
        log = self.run_with_reported_count(-3)
        self.assertIsNone(log.sources_count)

    def test_non_integer_degrades_to_null(self):
        log = self.run_with_reported_count("many")
        self.assertIsNone(log.sources_count)

    def test_float_degrades_to_null(self):
        log = self.run_with_reported_count(3.0)
        self.assertIsNone(log.sources_count)

    def test_bool_degrades_to_null(self):
        # bool is an int subclass; True must not be stored as 1
        log = self.run_with_reported_count(True)
        self.assertIsNone(log.sources_count)

    def test_stale_value_from_a_previous_run_does_not_leak(self):
        # Core must re-initialise the attribute before each fetch, so a
        # leftover value on a reused station link instance cannot be recorded
        # as if this run had reported it.
        self.link.adl_sources_count = 5
        self.plugin.records = []

        self.plugin.process_station(self.link, bypass_lock=True)

        log = StationLinkActivityLog.objects.get()
        self.assertIsNone(log.sources_count)

    def test_failed_run_still_records_what_was_reported(self):
        # The plugin sets the count while listing, so a failure after listing
        # still leaves an honest number on the terminal FAILED log.
        def fetch(station_link, start_date=None, end_date=None):
            station_link.adl_sources_count = 4
            raise RuntimeError("host unreachable")

        with patch.object(self.plugin, "get_station_data", side_effect=fetch):
            self.plugin.process_station(self.link, bypass_lock=True)

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertEqual(log.sources_count, 4)


class NoneReturnConvergenceTests(SourcesCountTestCase):
    def test_none_return_converges_to_the_normal_terminal_path(self):
        # Historically `get_station_data` returning None short-circuited before
        # the activity log was finalised, leaving a permanently-STARTED row.
        # It now behaves exactly like an empty iterable.
        def fetch(station_link, start_date=None, end_date=None):
            station_link.adl_sources_count = 0
            return None

        with patch.object(self.plugin, "get_station_data", side_effect=fetch):
            result = self.plugin.process_station(self.link, bypass_lock=True)

        self.assertEqual(result, 0)
        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.COMPLETED)
        self.assertTrue(log.success)
        self.assertEqual(log.records_count, 0)
        self.assertEqual(log.sources_count, 0)
        self.assertEqual(log.message, "No new records to save.")
