"""Availability read model: expected/present hours and cell states per local day.

Tests write real ``ObservationRecord`` rows and read them back through
``HourlyObsAgg``, which has real-time aggregation on, so unmaterialised rows
are visible without a refresh.
"""

from datetime import datetime, timedelta, timezone as py_tz

from django.test import TestCase

from adl.core.tests.factories import (
    DataParameterFactory,
    NetworkConnectionFactory,
    ObservationRecordFactory,
    StationLinkFactory,
)
from adl.monitoring.availability import (
    COMPLETE,
    EMPTY,
    NOT_EXPECTED,
    PARTIAL,
    month_availability,
)

UTC = py_tz.utc


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class MonthAvailabilityTestCase(TestCase):
    def make_link(self, tz="UTC", start_date=None):
        connection = NetworkConnectionFactory(stations_timezone=tz)
        link = StationLinkFactory(network_connection=connection)
        link.get_first_collection_date = lambda: start_date
        return link

    def record(self, link, time, parameter=None):
        return ObservationRecordFactory(
            station=link.station,
            connection=link.network_connection,
            parameter=parameter or DataParameterFactory(),
            time=time,
        )

    def fill_day(self, link, year, month, day, hours=range(24)):
        parameter = DataParameterFactory()
        for hour in hours:
            self.record(link, utc(year, month, day, hour, 30), parameter)

    def day(self, result, day):
        return result.days[day - 1]


class FloorTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 20, 12, 15)

    def test_first_record_is_the_floor_without_a_collection_start_date(self):
        link = self.make_link()
        self.fill_day(link, 2026, 3, 5)

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertEqual(self.day(result, 4).state, NOT_EXPECTED)
        self.assertEqual(self.day(result, 5).state, COMPLETE)
        self.assertEqual(
            (self.day(result, 5).expected_hours, self.day(result, 5).present_hours), (24, 24)
        )
        # the day after the first record has no data: every hour is a gap
        self.assertEqual(self.day(result, 6).state, EMPTY)

    def test_collection_start_date_wins_and_earlier_hours_are_gaps(self):
        link = self.make_link(start_date=utc(2026, 3, 3, 0, 0))
        self.fill_day(link, 2026, 3, 5)

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertEqual(self.day(result, 2).state, NOT_EXPECTED)
        self.assertEqual(self.day(result, 3).state, EMPTY)
        self.assertEqual(self.day(result, 3).expected_hours, 24)
        self.assertEqual(self.day(result, 4).state, EMPTY)
        self.assertEqual(self.day(result, 5).state, COMPLETE)

    def test_hours_before_a_start_date_later_than_data_are_not_expected(self):
        link = self.make_link(start_date=utc(2026, 3, 8, 12, 0))
        self.fill_day(link, 2026, 3, 5)
        self.fill_day(link, 2026, 3, 8, hours=range(12, 24))

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertEqual(self.day(result, 5).state, NOT_EXPECTED)
        self.assertEqual(self.day(result, 5).expected_hours, 0)
        eighth = self.day(result, 8)
        self.assertEqual((eighth.expected_hours, eighth.present_hours), (12, 12))
        self.assertEqual(eighth.state, COMPLETE)

    def test_no_data_and_no_start_date_expects_nothing(self):
        link = self.make_link()

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertTrue(all(d.state == NOT_EXPECTED for d in result.days))


class DayStateTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 20, 12, 15)

    def test_partial_day_reports_counts_and_intensity_growing_with_missing_hours(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        self.fill_day(link, 2026, 3, 5, hours=range(18))
        self.fill_day(link, 2026, 3, 6, hours=range(6))

        result = month_availability(link, 2026, 3, now=self.NOW)

        mostly, barely = self.day(result, 5), self.day(result, 6)
        self.assertEqual((mostly.state, mostly.present_hours, mostly.expected_hours), (PARTIAL, 18, 24))
        self.assertEqual(barely.state, PARTIAL)
        self.assertLess(mostly.intensity, barely.intensity)
        self.assertTrue(0 < mostly.intensity < barely.intensity <= 1)

    def test_an_hour_is_present_if_any_parameter_has_a_record(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        for parameter in (DataParameterFactory(), DataParameterFactory()):
            self.record(link, utc(2026, 3, 5, 9, 10), parameter)
            self.record(link, utc(2026, 3, 5, 9, 50), parameter)

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertEqual(self.day(result, 5).present_hours, 1)

    def test_records_of_another_station_link_are_ignored(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        other = self.make_link()
        self.fill_day(other, 2026, 3, 5)

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertEqual(self.day(result, 5).state, EMPTY)

    def test_every_month_day_is_returned(self):
        link = self.make_link()
        self.assertEqual(len(month_availability(link, 2026, 2, now=self.NOW).days), 28)


class TodayTests(MonthAvailabilityTestCase):
    def test_today_counts_only_elapsed_hours(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        now = utc(2026, 3, 20, 10, 30)
        self.fill_day(link, 2026, 3, 20, hours=range(10))

        result = month_availability(link, 2026, 3, now=now)

        today = self.day(result, 20)
        # 00:00-10:00 have elapsed; the 10:00 hour is still running
        self.assertEqual((today.expected_hours, today.present_hours), (10, 10))
        self.assertEqual(today.state, COMPLETE)

    def test_future_days_are_not_expected(self):
        link = self.make_link(start_date=utc(2026, 3, 1))

        result = month_availability(link, 2026, 3, now=utc(2026, 3, 20, 10, 30))

        self.assertEqual(self.day(result, 21).state, NOT_EXPECTED)
        self.assertEqual(self.day(result, 31).expected_hours, 0)

    def test_first_hour_of_the_day_leaves_today_not_expected(self):
        link = self.make_link(start_date=utc(2026, 3, 1))

        result = month_availability(link, 2026, 3, now=utc(2026, 3, 20, 0, 40))

        self.assertEqual(self.day(result, 20).state, NOT_EXPECTED)


class TimezoneTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 20, 12, 15)

    def test_records_straddling_utc_midnight_land_on_the_right_local_day(self):
        # Nairobi is UTC+3: 22:30Z on the 4th is 01:30 local on the 5th
        link = self.make_link(tz="Africa/Nairobi", start_date=utc(2026, 3, 3))
        self.record(link, utc(2026, 3, 4, 22, 30))
        self.record(link, utc(2026, 3, 4, 20, 30))

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertEqual(self.day(result, 4).present_hours, 1)  # 23:30 local
        self.assertEqual(self.day(result, 5).present_hours, 1)  # 01:30 local

    def test_a_local_day_is_twenty_four_hours_in_a_fixed_offset_zone(self):
        link = self.make_link(tz="Africa/Nairobi", start_date=utc(2026, 3, 1))

        result = month_availability(link, 2026, 3, now=self.NOW)

        self.assertEqual(self.day(result, 10).expected_hours, 24)

    def test_month_bounds_follow_the_local_calendar(self):
        # 22:30Z on 31 March is 01:30 local on 1 April: not in March
        link = self.make_link(tz="Africa/Nairobi", start_date=utc(2026, 3, 1))
        self.record(link, utc(2026, 3, 31, 22, 30))

        result = month_availability(link, 2026, 3, now=utc(2026, 5, 1))

        self.assertEqual(self.day(result, 31).present_hours, 0)

    def test_result_names_the_effective_timezone(self):
        link = self.make_link(tz="Africa/Nairobi")
        result = month_availability(link, 2026, 3, now=self.NOW)
        self.assertEqual(result.timezone_name, "Africa/Nairobi")

    def test_station_timezone_is_used_when_the_connection_one_is_not(self):
        link = self.make_link(tz="UTC")
        link.use_connection_timezone = False
        link.timezone_info = "Africa/Nairobi"
        result = month_availability(link, 2026, 3, now=self.NOW)
        self.assertEqual(result.timezone_name, "Africa/Nairobi")


class CellTextTests(MonthAvailabilityTestCase):
    def test_cell_text_is_present_over_expected(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        self.fill_day(link, 2026, 3, 5, hours=range(18))

        result = month_availability(link, 2026, 3, now=utc(2026, 3, 20, 12, 15))

        self.assertEqual(self.day(result, 5).label, "18/24")
        self.assertEqual(self.day(result, 25).label, "")
