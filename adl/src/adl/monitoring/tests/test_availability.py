"""Availability read model: expected/present hours and cell states per local day.

Tests write real ``ObservationRecord`` rows and read them back through
``HourlyObsAgg``, which has real-time aggregation on, so unmaterialised rows
are visible without a refresh.
"""

from datetime import date, datetime, timedelta, timezone as py_tz

from django.db import connection as connection_db
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from adl.core.tests.factories import (
    DataParameterFactory,
    NetworkConnectionFactory,
    ObservationRecordFactory,
    StationFactory,
    StationLinkFactory,
)
from adl.monitoring.availability import (
    COMPLETE,
    EMPTY,
    NOT_EXPECTED,
    MISSING,
    PARTIAL,
    PRESENT,
    connection_availability,
    day_availability,
    month_availability,
    whole_day_window,
)
from adl.core.source_checks import SourceCheckStatus
from adl.core.tests.helpers import make_mapping
from adl.monitoring.models import AvailabilityCheck

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


class ParameterGapMarkerTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 20, 12, 15)

    def map_parameters(self, link, *parameters):
        unit = parameters[0].unit
        link.get_variable_mappings = lambda: [
            make_mapping(p, unit, source_name=p.name) for p in parameters
        ]

    def test_complete_day_missing_a_mapped_parameter_for_some_hours_is_marked(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        temp, wind = DataParameterFactory(), DataParameterFactory()
        self.map_parameters(link, temp, wind)
        for hour in range(24):
            self.record(link, utc(2026, 3, 5, hour, 30), temp)
        for hour in range(23):
            self.record(link, utc(2026, 3, 5, hour, 30), wind)

        day = month_availability(link, 2026, 3, now=self.NOW).days[4]

        self.assertEqual(day.state, COMPLETE)
        self.assertTrue(day.has_parameter_gap)

    def test_complete_day_with_every_mapped_parameter_has_no_marker(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        temp = DataParameterFactory()
        self.map_parameters(link, temp)
        self.fill_day(link, 2026, 3, 5)  # other parameter; temp is missing
        for hour in range(24):
            self.record(link, utc(2026, 3, 6, hour, 30), temp)

        days = month_availability(link, 2026, 3, now=self.NOW).days

        self.assertTrue(days[4].has_parameter_gap)
        self.assertFalse(days[5].has_parameter_gap)

    def test_day_missing_only_an_unmapped_parameter_has_no_marker(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        temp, unmapped = DataParameterFactory(), DataParameterFactory()
        self.map_parameters(link, temp)
        for hour in range(24):
            self.record(link, utc(2026, 3, 5, hour, 30), temp)
        self.record(link, utc(2026, 3, 5, 3, 30), unmapped)

        day = month_availability(link, 2026, 3, now=self.NOW).days[4]

        self.assertFalse(day.has_parameter_gap)

    def test_no_mappings_means_no_markers(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        self.fill_day(link, 2026, 3, 5, hours=range(10))

        days = month_availability(link, 2026, 3, now=self.NOW).days

        self.assertFalse(any(d.has_parameter_gap for d in days))

    def test_days_with_nothing_expected_have_no_marker(self):
        link = self.make_link(start_date=utc(2026, 3, 10))
        self.map_parameters(link, DataParameterFactory())

        days = month_availability(link, 2026, 3, now=self.NOW).days

        self.assertFalse(days[0].has_parameter_gap)  # before the floor
        self.assertFalse(days[24].has_parameter_gap)  # future


class DayAvailabilityTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 20, 12, 15)

    def setUp(self):
        self.temp, self.wind = DataParameterFactory(), DataParameterFactory()

    def map_parameters(self, link, *parameters):
        link.get_variable_mappings = lambda: [
            make_mapping(p, p.unit, source_name=p.name) for p in parameters
        ]

    def day_of(self, link, day=5, now=None):
        return day_availability(link, date(2026, 3, day), now=now or self.NOW)

    def row(self, detail, parameter):
        return next(r for r in detail.rows if r.parameter == parameter)

    def states(self, row):
        return [c.state for c in row.cells]

    def test_any_row_matches_the_month_calendar_cell(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        self.map_parameters(link, self.temp)
        for hour in range(18):
            self.record(link, utc(2026, 3, 5, hour, 30), self.temp)

        detail = self.day_of(link)
        cell = month_availability(link, 2026, 3, now=self.NOW).days[4]

        self.assertEqual(len(detail.any_row.cells), 24)
        self.assertEqual(
            sum(c.state == PRESENT for c in detail.any_row.cells), cell.present_hours
        )
        self.assertEqual(
            sum(c.state == MISSING for c in detail.any_row.cells), cell.missing_hours
        )

    def test_any_row_is_present_when_any_parameter_has_the_hour(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        self.map_parameters(link, self.temp, self.wind)
        self.record(link, utc(2026, 3, 5, 2, 30), self.temp)
        self.record(link, utc(2026, 3, 5, 3, 30), self.wind)

        detail = self.day_of(link)

        self.assertEqual(self.states(detail.any_row)[2:5], [PRESENT, PRESENT, MISSING])
        self.assertEqual(self.states(self.row(detail, self.temp))[2:4], [PRESENT, MISSING])
        self.assertEqual(self.states(self.row(detail, self.wind))[2:4], [MISSING, PRESENT])

    def test_cells_carry_records_count_and_local_hour(self):
        link = self.make_link(tz="Africa/Nairobi", start_date=utc(2026, 3, 1))
        self.map_parameters(link, self.temp)
        self.record(link, utc(2026, 3, 5, 6, 10), self.temp)
        self.record(link, utc(2026, 3, 5, 6, 40), self.temp)

        detail = self.day_of(link)
        cell = detail.rows[0].cells[9]  # 06:00Z is 09:00 in Nairobi

        self.assertEqual((cell.state, cell.records_count), (PRESENT, 2))
        self.assertEqual(cell.local_time.strftime("%H:%M"), "09:00")
        self.assertEqual(detail.rows[0].cells[0].records_count, 0)
        self.assertEqual(detail.timezone_name, "Africa/Nairobi")

    def test_mapped_parameter_without_data_is_a_row_of_missing_hours(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        self.map_parameters(link, self.temp, self.wind)
        self.record(link, utc(2026, 3, 5, 2, 30), self.temp)

        row = self.row(self.day_of(link), self.wind)

        self.assertTrue(row.mapped)
        self.assertEqual(self.states(row), [MISSING] * 24)

    def test_unmapped_parameter_with_data_is_a_flagged_row(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        self.map_parameters(link, self.temp)
        self.record(link, utc(2026, 3, 5, 2, 30), self.wind)

        detail = self.day_of(link)

        self.assertEqual([r.parameter for r in detail.rows], [self.temp, self.wind])
        self.assertTrue(detail.rows[0].mapped)
        self.assertFalse(detail.rows[1].mapped)
        self.assertEqual(detail.rows[1].cells[2].state, PRESENT)

    def test_data_of_another_station_link_is_ignored(self):
        link = self.make_link(start_date=utc(2026, 3, 1))
        other = self.make_link()
        self.map_parameters(link, self.temp)
        self.record(other, utc(2026, 3, 5, 2, 30), self.wind)

        detail = self.day_of(link)

        self.assertEqual([r.parameter for r in detail.rows], [self.temp])
        self.assertEqual(self.states(detail.any_row), [MISSING] * 24)

    def test_hours_outside_the_expected_range_are_not_expected(self):
        link = self.make_link(start_date=utc(2026, 3, 20, 6, 0))
        self.map_parameters(link, self.temp)

        detail = self.day_of(link, day=20, now=utc(2026, 3, 20, 10, 30))

        # expected: 06:00 to 10:00 elapsed
        self.assertEqual(
            self.states(detail.any_row),
            [NOT_EXPECTED] * 6 + [MISSING] * 4 + [NOT_EXPECTED] * 14,
        )

    def test_day_follows_the_local_calendar(self):
        # 22:30Z on the 4th is 01:30 local on the 5th in Nairobi
        link = self.make_link(tz="Africa/Nairobi", start_date=utc(2026, 3, 1))
        self.map_parameters(link, self.temp)
        self.record(link, utc(2026, 3, 4, 22, 30), self.temp)

        detail = self.day_of(link)

        self.assertEqual(detail.any_row.cells[1].state, PRESENT)
        self.assertEqual(detail.any_row.cells[1].local_time.hour, 1)

    def test_without_a_floor_nothing_is_expected(self):
        link = self.make_link()
        self.map_parameters(link, self.temp)

        detail = self.day_of(link)

        self.assertEqual(set(self.states(detail.any_row)), {NOT_EXPECTED})


class ConnectionGridTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 10, 0, 0)

    def make_links(self, *specs, tz="UTC"):
        """Links of one connection; each spec is ``(name, enabled)``."""
        connection = NetworkConnectionFactory(stations_timezone=tz)
        links = []
        for name, enabled in specs:
            link = StationLinkFactory(
                network_connection=connection,
                station=StationFactory(name=name),
                enabled=enabled,
            )
            link.get_first_collection_date = lambda: utc(2026, 3, 1)
            links.append(link)
        return connection, links

    def fill(self, link, hours):
        parameter = DataParameterFactory()
        for hour in range(hours):
            self.record(link, utc(2026, 3, 1, 0, 30) + timedelta(hours=hour), parameter)

    def grid(self, connection, links, **kwargs):
        return connection_availability(connection, links, 2026, 3, now=self.NOW, **kwargs)

    def test_rows_carry_day_lists_and_hour_summaries(self):
        connection, (link,) = self.make_links(("Alpha", True))
        self.fill(link, 48)

        grid = self.grid(connection, [link])

        row = grid.rows[0]
        self.assertEqual(len(row.days), 31)
        self.assertEqual(row.days[0].state, COMPLETE)
        self.assertEqual(row.expected_hours, 9 * 24)
        self.assertEqual(row.present_hours, 48)
        self.assertEqual(row.missing_hours, 9 * 24 - 48)
        self.assertEqual(row.percent, round(100 * 48 / 216))

    def test_percent_is_none_when_nothing_is_expected(self):
        connection, (link,) = self.make_links(("Alpha", True))
        link.get_first_collection_date = lambda: utc(2026, 4, 1)

        self.assertIsNone(self.grid(connection, [link]).rows[0].percent)

    def test_percent_does_not_round_up_to_100_with_missing_hours(self):
        connection, (link,) = self.make_links(("Alpha", True))
        self.fill(link, 9 * 24 - 1)  # 215 of 216 expected: 99.5%

        self.assertEqual(self.grid(connection, [link]).rows[0].percent, 99)

    def test_enabled_links_rank_worst_first_by_missing_hours(self):
        connection, (a, b, c) = self.make_links(("Alpha", True), ("Bravo", True), ("Charlie", True))
        self.fill(a, 200)
        self.fill(b, 10)
        self.fill(c, 100)

        grid = self.grid(connection, [a, b, c])

        self.assertEqual([row.name for row in grid.rows], ["Bravo", "Charlie", "Alpha"])

    def test_sort_name_orders_alphabetically(self):
        connection, (a, b, c) = self.make_links(("Charlie", True), ("alpha", True), ("Bravo", True))
        self.fill(c, 200)

        grid = self.grid(connection, [a, b, c], sort="name")

        self.assertEqual([row.name for row in grid.rows], ["alpha", "Bravo", "Charlie"])

    def test_disabled_links_are_separated_and_never_ranked(self):
        connection, (a, b, c) = self.make_links(("Alpha", True), ("Bravo", False), ("Aaa", False))
        self.fill(a, 200)

        grid = self.grid(connection, [a, b, c])

        self.assertEqual([row.name for row in grid.rows], ["Alpha"])
        self.assertEqual([row.name for row in grid.disabled_rows], ["Aaa", "Bravo"])

    def test_corner_marker_follows_the_links_mapped_parameters(self):
        connection, (link,) = self.make_links(("Alpha", True))
        mapped = DataParameterFactory()
        link.get_variable_mappings = lambda: [make_mapping(mapped, None)]
        for hour in range(24):
            self.record(link, utc(2026, 3, 1, hour, 30), DataParameterFactory())

        day = self.grid(connection, [link]).rows[0].days[0]

        self.assertEqual(day.state, COMPLETE)
        self.assertTrue(day.has_parameter_gap)

    def test_matches_the_single_link_month_view(self):
        connection, (link,) = self.make_links(("Alpha", True), tz="Africa/Nairobi")
        self.fill(link, 30)

        grid_days = self.grid(connection, [link]).rows[0].days
        month_days = month_availability(link, 2026, 3, now=self.NOW).days

        self.assertEqual(grid_days, month_days)

    def test_uses_each_links_own_timezone_when_not_the_connections(self):
        connection, (link,) = self.make_links(("Alpha", True))
        link.use_connection_timezone = False
        link.timezone_info = "Africa/Nairobi"

        self.assertEqual(self.grid(connection, [link]).rows[0].timezone_name, "Africa/Nairobi")

    def test_empty_connection_has_an_empty_grid(self):
        connection, _links = self.make_links()

        grid = self.grid(connection, [])

        self.assertEqual((grid.rows, grid.disabled_rows), ([], []))

    def test_query_count_does_not_grow_with_the_number_of_links(self):
        def count(n):
            connection, links = self.make_links(*[(f"Station {n}-{i}", True) for i in range(n)])
            for link in links:
                link.get_first_collection_date = lambda: None  # forces the first-record query
                self.fill(link, 3)
            with CaptureQueriesContext(connection_db) as queries:
                self.grid(connection, links)
            return len(queries)

        self.assertEqual(count(2), count(12))


class WholeDayWindowTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 20, 12, 15)
    DAY = date(2026, 3, 5)

    def setUp(self):
        self.temp, self.wind = DataParameterFactory(), DataParameterFactory()
        self.link = self.make_link(start_date=utc(2026, 3, 1))
        self.link.get_variable_mappings = lambda: [
            make_mapping(p, p.unit, source_name=p.name) for p in (self.temp, self.wind)
        ]

    def fill(self, parameter, hours):
        for hour in hours:
            self.record(self.link, utc(2026, 3, 5, hour, 30), parameter)

    def window(self):
        return whole_day_window(self.link, self.DAY, now=self.NOW)

    def test_spans_first_to_last_hour_with_a_missing_mapped_parameter(self):
        self.fill(self.temp, [h for h in range(24) if h != 3])
        self.fill(self.wind, [h for h in range(24) if h != 17])

        self.assertEqual(self.window(), (utc(2026, 3, 5, 3), utc(2026, 3, 5, 18)))

    def test_a_parameter_only_gap_creates_the_window(self):
        self.fill(self.temp, range(24))
        self.fill(self.wind, [h for h in range(24) if h not in (9, 10)])

        self.assertEqual(self.window(), (utc(2026, 3, 5, 9), utc(2026, 3, 5, 11)))

    def test_fully_present_edge_hours_do_not_extend_it(self):
        self.fill(self.temp, range(24))
        self.fill(self.wind, [h for h in range(24) if h != 12])

        self.assertEqual(self.window(), (utc(2026, 3, 5, 12), utc(2026, 3, 5, 13)))

    def test_unmapped_parameters_never_extend_it(self):
        unmapped = DataParameterFactory()
        self.fill(self.temp, range(24))
        self.fill(self.wind, range(24))
        self.fill(unmapped, [4])

        self.assertIsNone(self.window())

    def test_a_day_with_no_mapped_parameter_gap_offers_no_check(self):
        self.fill(self.temp, range(24))
        self.fill(self.wind, range(24))

        self.assertIsNone(self.window())

    def test_a_link_without_mappings_offers_no_check(self):
        self.link.get_variable_mappings = lambda: []

        self.assertIsNone(self.window())

    def test_a_day_with_nothing_expected_offers_no_check(self):
        self.assertIsNone(whole_day_window(self.link, date(2026, 2, 20), now=self.NOW))
        self.assertIsNone(whole_day_window(self.link, date(2026, 3, 25), now=self.NOW))

    def test_follows_the_station_link_timezone(self):
        link = self.make_link(tz="Africa/Nairobi", start_date=utc(2026, 3, 1))
        link.get_variable_mappings = lambda: [make_mapping(self.temp, self.temp.unit, source_name="t")]
        # local 5 March is 04 March 21:00 UTC to 5 March 21:00 UTC; leave local 08:00-10:00 empty
        for hour in range(24):
            if hour not in (8, 9):
                self.record(link, utc(2026, 3, 4, 21, 30) + timedelta(hours=hour), self.temp)

        self.assertEqual(
            whole_day_window(link, self.DAY, now=self.NOW),
            (utc(2026, 3, 5, 5), utc(2026, 3, 5, 7)),
        )


class CheckedMarkerTests(MonthAvailabilityTestCase):
    NOW = utc(2026, 3, 20, 12, 15)

    def setUp(self):
        self.temp = DataParameterFactory()
        self.link = self.make_link(start_date=utc(2026, 3, 1))
        self.link.get_variable_mappings = lambda: [
            make_mapping(self.temp, self.temp.unit, source_name="t")
        ]
        # 5 March has gaps at 06:00-09:00 and 15:00
        for hour in range(24):
            if hour not in (6, 7, 8, 15):
                self.record(self.link, utc(2026, 3, 5, hour, 30), self.temp)

    def store(self, start_hour, end_hour, status=SourceCheckStatus.OK, day=5):
        return AvailabilityCheck.objects.create(
            station_link=self.link,
            window_start=utc(2026, 3, day) + timedelta(hours=start_hour),
            window_end=utc(2026, 3, day) + timedelta(hours=end_hour),
            created_at=self.NOW, tier="fetch", status=status,
        )

    def march_5(self):
        return month_availability(self.link, 2026, 3, now=self.NOW).days[4]

    def test_a_day_with_a_gap_and_no_check_is_not_checked(self):
        self.assertFalse(self.march_5().checked)

    def test_a_check_over_only_some_gaps_is_not_enough(self):
        self.store(6, 9)

        self.assertFalse(self.march_5().checked)

    def test_every_gap_covered_by_stored_results_marks_the_day(self):
        self.store(6, 9)
        self.store(15, 16)

        self.assertTrue(self.march_5().checked)

    def test_a_whole_day_check_marks_the_day(self):
        self.store(6, 16)

        self.assertTrue(self.march_5().checked)

    def test_a_check_that_did_not_answer_does_not_count(self):
        self.store(0, 24, status=SourceCheckStatus.FAILED)

        self.assertFalse(self.march_5().checked)

    def test_hours_that_fill_drop_out_of_the_gaps_that_must_be_covered(self):
        self.store(6, 9)
        self.assertFalse(self.march_5().checked)  # 15:00 is uncovered

        self.record(self.link, utc(2026, 3, 5, 15, 30), self.temp)

        self.assertTrue(self.march_5().checked)

    def test_a_filled_day_is_not_checked(self):
        self.store(6, 9)
        self.store(15, 16)
        for hour in (6, 7, 8, 15):
            self.record(self.link, utc(2026, 3, 5, hour, 30), self.temp)

        day = self.march_5()

        self.assertEqual(day.state, COMPLETE)
        self.assertFalse(day.checked)

    def test_a_parameter_only_gap_can_be_checked(self):
        wind = DataParameterFactory()
        self.link.get_variable_mappings = lambda: [
            make_mapping(p, p.unit, source_name=p.name) for p in (self.temp, wind)
        ]
        for hour in range(24):
            self.record(self.link, utc(2026, 3, 6, hour, 30), self.temp)
        self.store(0, 24, day=6)

        day = month_availability(self.link, 2026, 3, now=self.NOW).days[5]

        self.assertTrue(day.has_parameter_gap)
        self.assertTrue(day.checked)

    def test_other_station_links_checks_are_ignored(self):
        other = StationLinkFactory(network_connection=self.link.network_connection)
        AvailabilityCheck.objects.create(
            station_link=other, window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0),
            created_at=self.NOW, tier="fetch", status=SourceCheckStatus.OK,
        )

        self.assertFalse(self.march_5().checked)

    def test_the_connection_grid_carries_the_marker_too(self):
        self.store(6, 9)
        self.store(15, 16)

        grid = connection_availability(
            self.link.network_connection, [self.link], 2026, 3, now=self.NOW)

        self.assertTrue(grid.rows[0].days[4].checked)
        self.assertFalse(grid.rows[0].days[5].checked)
