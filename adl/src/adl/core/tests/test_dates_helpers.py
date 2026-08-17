from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as dj_tz
from freezegun import freeze_time

from adl.core.models import DataParameter, ObservationRecord, Unit
from .factories import StationLinkFactory
from .helpers import make_test_plugin


def seed_record(link, t_utc):
    """Save one observation for ``link`` at ``t_utc`` so the DB-resume path has a latest record."""
    unit = Unit.objects.create(name="Celsius", symbol="degC")
    param = DataParameter.objects.create(name="T", unit=unit)
    ObservationRecord.objects.create(
        station=link.station,
        connection=link.network_connection,
        parameter=param,
        value=1.0,
        time=t_utc,
    )


class DatesHelpersTests(TestCase):
    def setUp(self):
        self.plugin = make_test_plugin()

    @freeze_time("2025-01-01 11:30:00", tz_offset=3)  # Africa/Nairobi UTC+3
    def test_dates_latest_window_is_one_hour_on_the_hour(self):
        link = StationLinkFactory()
        start, end = self.plugin.get_dates_for_station(link, latest=True)
        # invariants: aligned to hour, and 1-hour window
        self.assertIsNotNone(start.tzinfo)
        self.assertIsNotNone(end.tzinfo)
        self.assertEqual((start.minute, start.second, start.microsecond), (0, 0, 0))
        self.assertEqual((end.minute, end.second, end.microsecond), (0, 0, 0))
        self.assertEqual((end - start).total_seconds(), 3600)

    def test_dates_use_latest_from_db_when_available(self):
        link = StationLinkFactory()
        # seed a record at 08:00 UTC (== 11:00 in Nairobi)
        t_utc = datetime(2025, 1, 1, 8, 0, tzinfo=py_tz.utc)
        seed_record(link, t_utc)

        start, end = self.plugin.get_dates_for_station(link, latest=False)
        # start should be >= the latest DB time localized to station tz
        start_utc = start.astimezone(py_tz.utc)
        self.assertGreaterEqual(start_utc, t_utc)
        self.assertGreater(end, start)

    def test_dates_fall_back_to_station_first_collection_date_when_no_db(self):
        link = StationLinkFactory()

        # simulate StationLink.get_first_collection_date() returning an AWARE datetime
        naive_local = datetime(2025, 1, 2, 10, 0)  # station-local naive
        aware_local = dj_tz.make_aware(naive_local, timezone=link.timezone)
        link.get_first_collection_date = lambda: aware_local

        start, end = self.plugin.get_dates_for_station(link, latest=False)
        # start should equal 10:00 local (in station tz)
        self.assertEqual((start.hour, start.minute), (10, 0))
        self.assertGreater(end, start)


class CollectionStartDateFloorTests(TestCase):
    """The station's configured collection start date is a floor on the
    resolved window: ingestion never starts before it, even once records
    exist. Moving it forward past the latest saved record skips the gap."""

    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()

    def test_floor_later_than_db_latest_wins_and_is_logged(self):
        db_latest = datetime(2025, 1, 1, 8, 0, tzinfo=py_tz.utc)
        floor = datetime(2025, 6, 1, 8, 0, tzinfo=py_tz.utc)
        seed_record(self.link, db_latest)
        self.link.get_first_collection_date = lambda: floor

        with self.assertLogs("adl.core.logging", level="INFO") as captured:
            start, end = self.plugin.get_dates_for_station(self.link)

        self.assertEqual(start.astimezone(py_tz.utc), floor)
        self.assertGreater(end, start)
        self.assertTrue(
            any("skipping the gap" in line for line in captured.output),
            captured.output,
        )

    def test_db_latest_later_than_floor_wins(self):
        floor = datetime(2025, 1, 1, 8, 0, tzinfo=py_tz.utc)
        db_latest = datetime(2025, 6, 1, 8, 0, tzinfo=py_tz.utc)
        seed_record(self.link, db_latest)
        self.link.get_first_collection_date = lambda: floor

        start, _ = self.plugin.get_dates_for_station(self.link)

        self.assertEqual(start.astimezone(py_tz.utc), db_latest)

    def test_db_latest_used_when_no_floor_configured(self):
        db_latest = datetime(2025, 6, 1, 8, 0, tzinfo=py_tz.utc)
        seed_record(self.link, db_latest)
        self.assertIsNone(self.link.get_first_collection_date())

        start, _ = self.plugin.get_dates_for_station(self.link)

        self.assertEqual(start.astimezone(py_tz.utc), db_latest)

    @freeze_time("2025-01-01 11:30:00")
    def test_default_window_when_neither_db_nor_floor(self):
        self.assertIsNone(self.link.get_first_collection_date())

        start, end = self.plugin.get_dates_for_station(self.link)

        self.assertEqual((end - start).total_seconds(), 3600)
        self.assertEqual(start.astimezone(py_tz.utc), datetime(2025, 1, 1, 11, 0, tzinfo=py_tz.utc))

    def test_floor_used_when_no_db(self):
        floor = datetime(2025, 1, 2, 10, 0, tzinfo=py_tz.utc)
        self.link.get_first_collection_date = lambda: floor

        start, _ = self.plugin.get_dates_for_station(self.link)

        self.assertEqual(start.astimezone(py_tz.utc), floor)

    def test_floor_and_db_latest_compared_as_instants_across_timezones(self):
        # DB latest is 09:00 UTC. The floor reads 10:00 on the wall clock but
        # in a UTC+3 zone, i.e. 07:00 UTC — an EARLIER instant despite the
        # later wall-clock hour. Naive comparison would pick the floor.
        db_latest = datetime(2025, 1, 1, 9, 0, tzinfo=py_tz.utc)
        seed_record(self.link, db_latest)
        floor_local = dj_tz.make_aware(datetime(2025, 1, 1, 10, 0), timezone=self.link.timezone)
        self.assertEqual(str(self.link.timezone), "Africa/Nairobi")
        self.link.get_first_collection_date = lambda: floor_local

        start, _ = self.plugin.get_dates_for_station(self.link)

        self.assertEqual(start.astimezone(py_tz.utc), db_latest)

    def test_initial_start_date_override_beats_the_floor(self):
        db_latest = datetime(2025, 1, 1, 8, 0, tzinfo=py_tz.utc)
        floor = datetime(2025, 6, 1, 8, 0, tzinfo=py_tz.utc)
        override = datetime(2024, 1, 1, 0, 0, tzinfo=py_tz.utc)
        seed_record(self.link, db_latest)
        self.link.get_first_collection_date = lambda: floor

        with patch.object(self.plugin, "get_station_data", return_value=[]) as mock_get:
            self.plugin.process_station(self.link, initial_start_date=override)

        self.assertEqual(mock_get.call_args.kwargs["start_date"], override)
