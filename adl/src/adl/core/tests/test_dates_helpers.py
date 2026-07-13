from datetime import datetime, timezone as py_tz

from django.test import TestCase
from django.utils import timezone as dj_tz
from freezegun import freeze_time

from .factories import StationLinkFactory
from .helpers import make_test_plugin


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
        from adl.core.models import ObservationRecord, DataParameter, Unit
        unit = Unit.objects.create(name="Celsius", symbol="degC")
        param = DataParameter.objects.create(name="T", unit=unit)

        ObservationRecord.objects.create(
            station=link.station,
            connection=link.network_connection,
            parameter=param,
            value=1.23,
            time=t_utc,
        )

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
