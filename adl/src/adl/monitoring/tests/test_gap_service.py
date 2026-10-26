"""
The gap service seam: window validation, the two check tiers, the in-flight
claim and the day overlay. Plugins are substituted at their contract methods;
no test dials a host.
"""

from datetime import datetime, timedelta, timezone as py_tz
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from adl.core.availability_checks import (
    TIER_FETCH,
    TIER_LISTING,
    AvailabilityCheckResult,
    AvailabilityRange,
)
from adl.core.models import ObservationRecord, StationLink
from adl.core.registries import plugin_registry
from adl.core.source_checks import SourceCheckStatus
from adl.core.tests.factories import (
    DataParameterFactory,
    NetworkConnectionFactory,
    ObservationRecordFactory,
    StationLinkFactory,
)
from adl.core.tests.helpers import make_mapping, make_test_plugin
from adl.monitoring import gap_service
from adl.monitoring.availability import day_availability, whole_day_window
from adl.monitoring.gap_service import (
    CheckCoolingDown,
    CheckInFlight,
    CheckUnavailable,
    InvalidWindow,
    check,
    check_whole_day,
    covered_missing_hours,
    day_check_overlay,
    validate_window,
)
from adl.monitoring.models import AvailabilityCheck
from adl.monitoring.tasks import run_availability_check

UTC = py_tz.utc
NOW = datetime(2026, 3, 10, 0, 0, tzinfo=UTC)
FLOOR = datetime(2026, 3, 1, tzinfo=UTC)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class GapServiceTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.plugin = make_test_plugin()
        self.parameter = DataParameterFactory()
        self.mapping = make_mapping(self.parameter, None, source_name="te")
        self.link = self.make_link()

        # The service reloads the link in its task, so the contract methods
        # are substituted on the class, not on one instance
        mapping = self.mapping
        for patcher in (
            patch.object(StationLink, "get_first_collection_date", lambda self: FLOOR),
            patch.object(StationLink, "get_variable_mappings", lambda self: [mapping]),
            patch.object(plugin_registry, "get", return_value=self.plugin),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_link(self):
        connection = NetworkConnectionFactory(stations_timezone="UTC")
        return StationLinkFactory(network_connection=connection)

    def run_tasks_eagerly(self):
        """Make ``.delay`` run the task body in-process, as a worker would."""
        patcher = patch.object(
            run_availability_check, "delay",
            side_effect=lambda *args: run_availability_check.apply(args=args),
        )
        self.delay = patcher.start()
        self.addCleanup(patcher.stop)

    def support_listing(self, fn):
        """Give every station link a listing-tier ``check_availability``."""
        for patcher in (
            patch.object(StationLink, "check_availability", fn),
            patch.object(StationLink, "availability_check_supported", True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def window(self, start_hour=6, end_hour=9, day=5):
        return utc(2026, 3, day, start_hour), utc(2026, 3, day, end_hour)


class ValidateWindowTests(GapServiceTestCase):
    def test_a_run_of_missing_hours_is_the_window(self):
        window = validate_window(self.link, *self.window(), now=NOW)

        self.assertEqual(window.hours, [utc(2026, 3, 5, h) for h in (6, 7, 8)])

    def test_window_longer_than_one_local_day_is_rejected(self):
        with self.assertRaises(InvalidWindow):
            validate_window(self.link, utc(2026, 3, 5, 0), utc(2026, 3, 6, 1), now=NOW)

    def test_window_spanning_midnight_is_rejected(self):
        with self.assertRaises(InvalidWindow):
            validate_window(self.link, utc(2026, 3, 5, 22), utc(2026, 3, 6, 2), now=NOW)

    def test_a_whole_local_day_is_allowed(self):
        window = validate_window(self.link, utc(2026, 3, 5, 0), utc(2026, 3, 6, 0), now=NOW)

        self.assertEqual(len(window.hours), 24)

    def test_unmapped_parameter_row_cannot_create_a_window(self):
        other = DataParameterFactory()

        with self.assertRaises(InvalidWindow):
            validate_window(self.link, *self.window(), parameter_id=other.id, now=NOW)

    def test_mapped_parameter_row_is_accepted(self):
        window = validate_window(self.link, *self.window(), parameter_id=self.parameter.id, now=NOW)

        self.assertEqual(window.parameter_id, self.parameter.id)

    def test_window_must_consist_only_of_missing_hours(self):
        ObservationRecordFactory(
            station=self.link.station, connection=self.link.network_connection,
            parameter=self.parameter, time=utc(2026, 3, 5, 7, 30),
        )

        with self.assertRaises(InvalidWindow):
            validate_window(self.link, *self.window(), now=NOW)

    def test_hours_that_are_not_expected_are_not_a_window(self):
        with self.assertRaises(InvalidWindow):  # before the 1 March floor
            validate_window(self.link, utc(2026, 2, 20, 6), utc(2026, 2, 20, 9), now=NOW)

    def test_malformed_times_are_rejected(self):
        for start, end in (
            (utc(2026, 3, 5, 9), utc(2026, 3, 5, 6)),
            (utc(2026, 3, 5, 6, 30), utc(2026, 3, 5, 9)),
            (datetime(2026, 3, 5, 6), utc(2026, 3, 5, 9)),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(InvalidWindow):
                validate_window(self.link, start, end, now=NOW)


class WholeDayWindowValidationTests(GapServiceTestCase):
    DAY = datetime(2026, 3, 5).date()

    def record(self, hour, day=5):
        ObservationRecordFactory(
            station=self.link.station, connection=self.link.network_connection,
            parameter=self.parameter, time=utc(2026, 3, day, hour, 30),
        )

    def test_the_trimmed_span_is_valid_even_with_present_hours_inside(self):
        for hour in range(24):
            if hour not in (3, 4, 9):
                self.record(hour)

        start, end = whole_day_window(self.link, self.DAY, now=NOW)
        validated = validate_window(self.link, start, end, now=NOW)

        self.assertEqual((validated.start, validated.end), (utc(2026, 3, 5, 3), utc(2026, 3, 5, 10)))
        self.assertIsNone(validated.parameter_id)

    def test_a_day_without_mapped_parameter_gaps_offers_none(self):
        for hour in range(24):
            self.record(hour)

        self.assertIsNone(whole_day_window(self.link, self.DAY, now=NOW))

    def test_a_span_that_is_not_the_trim_still_needs_to_be_missing_hours(self):
        for hour in range(24):
            if hour not in (3, 9):
                self.record(hour)

        with self.assertRaises(InvalidWindow):
            validate_window(self.link, utc(2026, 3, 5, 2), utc(2026, 3, 5, 10), now=NOW)

    def test_a_trimmed_span_is_not_valid_for_a_parameter_row(self):
        for hour in range(24):
            if hour not in (3, 9):
                self.record(hour)
        start, end = whole_day_window(self.link, self.DAY, now=NOW)

        with self.assertRaises(InvalidWindow):
            validate_window(self.link, start, end, parameter_id=self.parameter.id, now=NOW)

    def test_a_check_of_the_trimmed_span_is_enqueued_like_any_other(self):
        for hour in range(24):
            if hour not in (3, 9):
                self.record(hour)
        start, end = whole_day_window(self.link, self.DAY, now=NOW)

        with patch.object(run_availability_check, "delay") as delay:
            delay.return_value.id = "t1"
            outcome = check(self.link, start, end, now=NOW)

        self.assertEqual(outcome.tier, TIER_FETCH)


    def test_asks_about_the_trimmed_span_of_the_day(self):
        for hour in range(24):
            if hour not in (3, 9):
                self.record(hour)

        with patch.object(run_availability_check, "delay") as delay:
            delay.return_value.id = "t1"
            outcome = check_whole_day(self.link, self.DAY, now=NOW)

        self.assertEqual(outcome.task_id, "t1")
        self.assertEqual(delay.call_args.args[1:3],
                         (utc(2026, 3, 5, 3).isoformat(), utc(2026, 3, 5, 10).isoformat()))

    def test_a_day_with_no_mapped_parameter_gap_is_refused_and_takes_no_claim(self):
        for hour in range(24):
            self.record(hour)

        with self.assertRaises(InvalidWindow):
            check_whole_day(self.link, self.DAY, now=NOW)

        self.assertTrue(cache.add(gap_service.inflight_key(self.link.id), "x"))


class CoverageTests(TestCase):
    def test_partially_overlapping_ranges_cover_the_hours_they_touch(self):
        missing = [utc(2026, 3, 5, h) for h in (6, 7, 8, 9)]
        ranges = [
            AvailabilityRange(utc(2026, 3, 5, 5, 30), utc(2026, 3, 5, 6, 10)),  # starts before
            AvailabilityRange(utc(2026, 3, 5, 7, 50), utc(2026, 3, 5, 8, 0)),  # ends on the hour
        ]

        covered = covered_missing_hours(ranges, missing)

        self.assertEqual(covered, [utc(2026, 3, 5, 6), utc(2026, 3, 5, 7)])

    def test_a_range_ending_where_an_hour_starts_does_not_cover_it(self):
        ranges = [AvailabilityRange(utc(2026, 3, 5, 5), utc(2026, 3, 5, 6))]

        self.assertEqual(covered_missing_hours(ranges, [utc(2026, 3, 5, 6)]), [])

    def test_a_daily_range_covers_a_whole_window(self):
        ranges = [AvailabilityRange(utc(2026, 3, 5), utc(2026, 3, 6), 1, "day.csv")]
        missing = [utc(2026, 3, 5, h) for h in range(6, 9)]

        self.assertEqual(covered_missing_hours(ranges, missing), missing)


class FetchTierTests(GapServiceTestCase):
    def setUp(self):
        super().setUp()
        self.run_tasks_eagerly()

    def records(self, *specs):
        self.plugin.records = [
            {"observation_time": time, "te": value} for time, value in specs
        ]

    def test_counts_records_per_hour_and_per_parameter_and_saves_nothing(self):
        self.records(
            (utc(2026, 3, 5, 6, 10), 20.0),
            (utc(2026, 3, 5, 6, 40), 21.0),
            (utc(2026, 3, 5, 8, 0), 22.0),
            (utc(2026, 3, 5, 12, 0), 23.0),  # outside the window
        )
        before = ObservationRecord.objects.count()

        outcome = check(self.link, *self.window(), now=NOW)

        stored = AvailabilityCheck.objects.get()
        self.assertEqual(outcome.tier, TIER_FETCH)
        self.assertEqual((stored.tier, stored.status), (TIER_FETCH, SourceCheckStatus.OK))
        self.assertEqual(
            [(r["start"], r["count"]) for r in stored.ranges],
            [(utc(2026, 3, 5, 6).isoformat(), 2), (utc(2026, 3, 5, 8).isoformat(), 1)],
        )
        self.assertEqual(
            stored.parameter_coverage,
            {str(self.parameter.id): [utc(2026, 3, 5, 6).isoformat(), utc(2026, 3, 5, 8).isoformat()]},
        )
        self.assertEqual(ObservationRecord.objects.count(), before)

    def test_a_record_with_several_mapped_values_counts_once_per_hour(self):
        second = DataParameterFactory()
        mappings = [self.mapping, make_mapping(second, None, source_name="rh")]
        self.plugin.records = [{"observation_time": utc(2026, 3, 5, 6, 10), "te": 1.0, "rh": 2.0}]

        with patch.object(StationLink, "get_variable_mappings", lambda self: mappings):
            check(self.link, *self.window(), now=NOW)

        stored = AvailabilityCheck.objects.get()
        self.assertEqual([r["count"] for r in stored.ranges], [1])
        self.assertEqual(set(stored.parameter_coverage), {str(self.parameter.id), str(second.id)})

    def test_values_the_station_link_does_not_map_are_not_counted(self):
        self.plugin.records = [{"observation_time": utc(2026, 3, 5, 6, 10), "unmapped": 1}]

        check(self.link, *self.window(), now=NOW)

        self.assertEqual(AvailabilityCheck.objects.get().ranges, [])

    def test_naive_record_times_are_station_local(self):
        self.link.network_connection.stations_timezone = "Africa/Nairobi"
        self.link.network_connection.save()
        self.plugin.records = [{"observation_time": datetime(2026, 3, 5, 10, 0), "te": 1.0}]  # 07:00 UTC

        check(self.link, *self.window(), now=NOW)

        self.assertEqual(AvailabilityCheck.objects.get().ranges[0]["start"],
                         utc(2026, 3, 5, 7).isoformat())

    def test_a_raising_source_is_a_stored_failure_with_redacted_message(self):
        def boom(*args, **kwargs):
            raise RuntimeError("login failed for https://h/x?password=hunter2")
        self.plugin.get_station_data = boom

        check(self.link, *self.window(), now=NOW)

        stored = AvailabilityCheck.objects.get()
        self.assertEqual(stored.status, SourceCheckStatus.FAILED)
        self.assertNotIn("hunter2", stored.message)

    def test_the_claim_is_released_when_the_task_ends(self):
        check(self.link, *self.window(), now=NOW)

        self.assertIsNone(cache.get(gap_service.inflight_key(self.link.id)))


class InFlightTests(GapServiceTestCase):
    def test_a_second_check_is_refused_while_one_is_in_flight(self):
        with patch.object(run_availability_check, "delay") as delay:
            check(self.link, *self.window(), now=NOW)

            with self.assertRaises(CheckInFlight):
                check(self.link, *self.window(), now=NOW)

        self.assertEqual(delay.call_count, 1)

    def test_a_different_station_link_is_unaffected(self):
        other = self.make_link()

        with patch.object(run_availability_check, "delay") as delay:
            check(self.link, *self.window(), now=NOW)
            check(other, *self.window(), now=NOW)

        self.assertEqual(delay.call_count, 2)

    def test_a_recovery_claim_also_blocks_a_check(self):
        cache.add(gap_service.inflight_key(self.link.id), "recovery", timeout=60)

        with self.assertRaises(CheckInFlight):
            check(self.link, *self.window(), now=NOW)

    def test_the_claim_is_released_when_enqueueing_fails(self):
        with patch.object(run_availability_check, "delay", side_effect=ConnectionError):
            with self.assertRaises(ConnectionError):
                check(self.link, *self.window(), now=NOW)

        self.assertIsNone(cache.get(gap_service.inflight_key(self.link.id)))

    def test_an_invalid_window_takes_no_claim(self):
        with self.assertRaises(InvalidWindow):
            check(self.link, utc(2026, 3, 5, 0), utc(2026, 3, 7, 0), now=NOW)

        self.assertIsNone(cache.get(gap_service.inflight_key(self.link.id)))

    def test_a_connection_without_an_external_source_cannot_be_checked(self):
        with patch.object(type(self.link.network_connection), "has_external_source", False):
            with self.assertRaises(CheckUnavailable):
                check(self.link, *self.window(), now=NOW)


class ListingTierTests(GapServiceTestCase):
    def test_a_supported_link_is_answered_synchronously_and_stored(self):
        self.support_listing(lambda self, start, end: AvailabilityCheckResult(
            status=SourceCheckStatus.OK,
            ranges=[(utc(2026, 3, 5), utc(2026, 3, 6), 1, "20260305.csv")],
        ))

        with patch.object(run_availability_check, "delay") as delay:
            outcome = check(self.link, *self.window(), now=NOW)

        delay.assert_not_called()
        self.assertEqual(outcome.tier, TIER_LISTING)
        self.assertEqual(outcome.check.ranges[0]["label"], "20260305.csv")
        self.assertIsNone(cache.get(gap_service.inflight_key(self.link.id)))

    def test_the_plugin_receives_the_window_in_the_station_timezone(self):
        seen = []
        self.link.network_connection.stations_timezone = "Africa/Nairobi"
        self.link.network_connection.save()
        self.support_listing(lambda self, start, end: seen.append((start, end))
                             or AvailabilityCheckResult(status=SourceCheckStatus.OK))

        check(self.link, utc(2026, 3, 5, 6), utc(2026, 3, 5, 9), now=NOW)

        self.assertEqual(seen[0][0].hour, 9)
        self.assertEqual(seen[0][0].utcoffset(), timedelta(hours=3))

    def test_failed_and_malformed_results_do_not_fall_through_to_fetching(self):
        for result in (
            AvailabilityCheckResult(status=SourceCheckStatus.FAILED, message="no route"),
            "not a result",
        ):
            with self.subTest(result=result):
                cache.clear()
                self.support_listing(lambda self, start, end, r=result: r)

                with patch.object(run_availability_check, "delay") as delay:
                    outcome = check(self.link, *self.window(), now=NOW)

                delay.assert_not_called()
                self.assertEqual(outcome.check.tier, TIER_LISTING)
                self.assertIn(outcome.check.status,
                              (SourceCheckStatus.FAILED, SourceCheckStatus.MALFORMED))

    def test_a_raising_listing_is_a_stored_failure(self):
        def boom(self, start, end):
            raise OSError("connection reset")
        self.support_listing(boom)

        outcome = check(self.link, *self.window(), now=NOW)

        self.assertEqual(outcome.check.status, SourceCheckStatus.FAILED)

    def test_unsupported_for_this_link_falls_back_to_fetching(self):
        self.support_listing(lambda self, start, end: AvailabilityCheckResult(
            status=SourceCheckStatus.UNSUPPORTED))

        with patch.object(run_availability_check, "delay") as delay:
            outcome = check(self.link, *self.window(), now=NOW)

        delay.assert_called_once()
        self.assertEqual(outcome.tier, TIER_FETCH)

    def test_force_fetch_skips_the_listing(self):
        calls = []
        self.support_listing(lambda self, start, end: calls.append(1))

        with patch.object(run_availability_check, "delay") as delay:
            check(self.link, *self.window(), force_fetch=True, now=NOW)

        self.assertEqual(calls, [])
        delay.assert_called_once()


class ListingFailureHandlingTests(GapServiceTestCase):
    def test_a_listing_over_the_wall_clock_is_a_stored_timeout_not_a_wedge(self):
        self.support_listing(lambda self, start, end: AvailabilityCheckResult(
            status=SourceCheckStatus.OK))

        with patch.object(gap_service, "run_bounded", side_effect=gap_service.ProbeTimeout), \
                patch.object(run_availability_check, "delay") as delay:
            outcome = check(self.link, *self.window(), now=NOW)

        delay.assert_not_called()
        self.assertEqual(outcome.check.status, SourceCheckStatus.FAILED)
        self.assertEqual(outcome.check.tier, TIER_LISTING)
        self.assertIn("did not complete", outcome.check.message)
        self.assertIsNone(cache.get(gap_service.inflight_key(self.link.id)))

    def test_a_failed_listing_message_is_stored_redacted(self):
        def boom(self, start, end):
            raise OSError("login failed password=hunter2")
        self.support_listing(boom)

        outcome = check(self.link, *self.window(), now=NOW)

        self.assertNotIn("hunter2", outcome.check.message)

    def test_the_explicit_fetch_request_enqueues_tier_two_after_a_failure(self):
        self.support_listing(lambda self, start, end: AvailabilityCheckResult(
            status=SourceCheckStatus.FAILED, message="no route"))
        check(self.link, *self.window(), now=NOW)

        with patch.object(run_availability_check, "delay") as delay:
            outcome = check(self.link, *self.window(), force_fetch=True, now=NOW)

        delay.assert_called_once()
        self.assertEqual(outcome.tier, TIER_FETCH)


class StoredParameterTests(GapServiceTestCase):
    def test_a_check_remembers_the_parameter_row_it_was_made_from(self):
        self.support_listing(lambda s, start, end: AvailabilityCheckResult(
            status=SourceCheckStatus.FAILED, message="down"))

        stored = check(self.link, *self.window(), parameter_id=self.parameter.id, now=NOW).check

        self.assertEqual(stored.parameter_id, self.parameter.id)

    def test_an_any_parameter_check_stores_no_parameter(self):
        self.support_listing(lambda s, start, end: AvailabilityCheckResult(
            status=SourceCheckStatus.FAILED, message="down"))

        self.assertIsNone(check(self.link, *self.window(), now=NOW).check.parameter_id)


class ListingCooldownTests(GapServiceTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.support_listing(lambda s, start, end: self.calls.append(1)
                             or AvailabilityCheckResult(status=SourceCheckStatus.OK))

    def test_a_second_listing_inside_the_cooldown_is_refused_without_dialling(self):
        check(self.link, *self.window(), now=NOW)

        with self.assertRaises(CheckCoolingDown):
            check(self.link, *self.window(), now=NOW)

        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(cache.get(gap_service.inflight_key(self.link.id)))

    def test_the_cooldown_is_keyed_per_station_link(self):
        check(self.link, *self.window(), now=NOW)
        other = self.make_link()

        check(other, *self.window(), now=NOW)

        self.assertEqual(len(self.calls), 2)

    def test_an_unsupported_answer_leaves_no_cooldown_behind(self):
        self.support_listing(lambda s, start, end: AvailabilityCheckResult(
            status=SourceCheckStatus.UNSUPPORTED))

        with patch.object(run_availability_check, "delay"):
            check(self.link, *self.window(), now=NOW)
            cache.delete(gap_service.inflight_key(self.link.id))  # the task ended

            check(self.link, *self.window(), now=NOW)  # not refused as cooling down

    def test_the_explicit_fetch_is_not_held_back_by_the_listing_cooldown(self):
        check(self.link, *self.window(), now=NOW)

        with patch.object(run_availability_check, "delay") as delay:
            check(self.link, *self.window(), force_fetch=True, now=NOW)

        delay.assert_called_once()


class OverlayTests(GapServiceTestCase):
    DAY = datetime(2026, 3, 5).date()

    def store(self, start_hour, end_hour, ranges=(), status=SourceCheckStatus.OK, coverage=None,
              created=None):
        return AvailabilityCheck.objects.create(
            station_link=self.link,
            window_start=utc(2026, 3, 5, start_hour), window_end=utc(2026, 3, 5, end_hour),
            created_at=created or NOW, tier=TIER_FETCH, status=status,
            ranges=[{"start": s.isoformat(), "end": e.isoformat(), "count": None, "label": ""}
                    for s, e in ranges],
            parameter_coverage=coverage,
        )

    def overlay(self):
        detail = day_availability(self.link, self.DAY, now=NOW)
        return day_check_overlay(self.link, detail)

    def test_an_answered_check_marks_covered_and_uncovered_missing_hours(self):
        self.store(6, 9, ranges=[(utc(2026, 3, 5, 6), utc(2026, 3, 5, 8))])

        overlay = self.overlay()

        self.assertEqual(overlay.cells[(None, utc(2026, 3, 5, 6))], gap_service.HAS_DATA)
        self.assertEqual(overlay.cells[(None, utc(2026, 3, 5, 8))], gap_service.NOTHING)
        summary = overlay.summaries[0]
        self.assertEqual((summary.covered, summary.missing_total), (2, 3))
        self.assertEqual(summary.verdict, gap_service.HAS_DATA)

    def test_a_check_with_no_ranges_says_the_source_has_nothing(self):
        self.store(6, 9)

        summary = self.overlay().summaries[0]

        self.assertEqual(summary.verdict, gap_service.NOTHING)

    def test_a_failed_check_is_listed_but_marks_no_cell(self):
        self.store(6, 9, status=SourceCheckStatus.FAILED)

        overlay = self.overlay()

        self.assertEqual(overlay.cells, {})
        self.assertIsNone(overlay.summaries[0].verdict)

    def test_the_latest_check_for_an_hour_applies(self):
        self.store(6, 9, created=NOW - timedelta(hours=2))
        self.store(6, 9, ranges=[(utc(2026, 3, 5, 6), utc(2026, 3, 5, 9))], created=NOW)

        overlay = self.overlay()

        self.assertEqual(overlay.cells[(None, utc(2026, 3, 5, 7))], gap_service.HAS_DATA)
        self.assertEqual(len(overlay.summaries), 2)
        self.assertEqual(overlay.summaries[0].verdict, gap_service.HAS_DATA)  # newest first

    def test_per_parameter_coverage_answers_the_parameter_row_exactly(self):
        self.store(6, 9, ranges=[(utc(2026, 3, 5, 6), utc(2026, 3, 5, 9))],
                   coverage={str(self.parameter.id): [utc(2026, 3, 5, 7).isoformat()]})

        overlay = self.overlay()

        key = self.parameter.id
        self.assertEqual(overlay.cells[(key, utc(2026, 3, 5, 7))], gap_service.HAS_DATA)
        self.assertEqual(overlay.cells[(key, utc(2026, 3, 5, 6))], gap_service.NOTHING)
        self.assertEqual(overlay.summaries[0].parameter_counts[0][1], 1)

    def test_a_result_stops_showing_once_its_hours_fill(self):
        self.store(6, 9)
        for hour in (6, 7, 8):
            ObservationRecordFactory(
                station=self.link.station, connection=self.link.network_connection,
                parameter=self.parameter, time=utc(2026, 3, 5, hour, 30),
            )

        overlay = self.overlay()

        self.assertEqual(overlay.summaries, [])
        self.assertEqual(overlay.cells, {})
