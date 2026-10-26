"""The availability-check contract: defaults and normalisation of plugin returns."""

from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from adl.core.availability_checks import (
    TIER_FETCH,
    TIER_LISTING,
    AvailabilityCheckResult,
    AvailabilityRange,
    normalise_availability_check_result,
)
from adl.core.models import NetworkConnection, StationLink
from adl.core.source_checks import SourceCheckStatus
from adl.core.tests.factories import StationLinkFactory

UTC = py_tz.utc
T0 = datetime(2026, 3, 5, 6, 0, tzinfo=UTC)
T1 = datetime(2026, 3, 5, 9, 0, tzinfo=UTC)


class BaseStationLinkTests(TestCase):
    def test_base_station_link_is_unsupported(self):
        link = StationLinkFactory()

        result = link.check_availability(T0, T1)

        self.assertEqual(result.status, SourceCheckStatus.UNSUPPORTED)

    def test_supported_property_is_false_for_the_base_class(self):
        self.assertFalse(StationLinkFactory().availability_check_supported)

    def test_supported_property_needs_an_override_and_an_external_source(self):
        link = StationLinkFactory()

        # A subclass-like override, answered by class identity without any call
        with patch.object(type(link), "check_availability", lambda self, s, e: None):
            # patching the base itself leaves it "not overridden"
            self.assertFalse(link.availability_check_supported)

        class Overriding(StationLink):
            class Meta:
                proxy = True
                app_label = "core"

            def check_availability(self, start, end):
                raise AssertionError("must not be called to decide support")

        overriding = Overriding(network_connection=link.network_connection, station=link.station)
        self.assertTrue(overriding.availability_check_supported)
        with patch.object(NetworkConnection, "has_external_source", False):
            self.assertFalse(overriding.availability_check_supported)


class NormalisationTests(SimpleTestCase):
    def norm(self, value, tier=TIER_LISTING):
        return normalise_availability_check_result(value, tier)

    def test_a_well_formed_result_passes_with_the_tier_stamped_by_core(self):
        result = self.norm(AvailabilityCheckResult(
            status=SourceCheckStatus.OK,
            ranges=[(T0, T1, 3, "a.csv"), AvailabilityRange(T1, T1.replace(hour=10))],
            tier=TIER_FETCH,  # a plugin cannot claim a tier
        ))

        self.assertEqual(result.status, SourceCheckStatus.OK)
        self.assertEqual(result.tier, TIER_LISTING)
        self.assertEqual(len(result.ranges), 2)
        self.assertEqual(result.ranges[0].label, "a.csv")

    def test_wrong_type_is_malformed(self):
        for value in (None, {"status": "OK"}, "OK"):
            with self.subTest(value=value):
                self.assertEqual(self.norm(value).status, SourceCheckStatus.MALFORMED)

    def test_invented_status_is_malformed(self):
        result = self.norm(AvailabilityCheckResult(status="GREAT"))
        self.assertEqual(result.status, SourceCheckStatus.MALFORMED)

    def test_malformed_ranges_are_malformed(self):
        naive = datetime(2026, 3, 5, 6, 0)
        for ranges in (
            "nope",
            [(T0, T1)],  # wrong arity
            [(T0, T1, 1, 5)],  # label not a string
            [(T1, T0, 1, "")],  # backwards
            [(naive, T1, 1, "")],  # naive datetime
            [(T0, T1, -1, "")],  # negative count
            [(T0, T1, True, "")],  # bool is not a count
            ["x"],
        ):
            with self.subTest(ranges=ranges):
                result = self.norm(AvailabilityCheckResult(
                    status=SourceCheckStatus.OK, ranges=ranges))
                self.assertEqual(result.status, SourceCheckStatus.MALFORMED)

    def test_malformed_parameter_coverage_is_malformed(self):
        for coverage in ("x", {"a": (T0,)}, {1: "x"}, {1: (datetime(2026, 1, 1),)}):
            with self.subTest(coverage=coverage):
                result = self.norm(AvailabilityCheckResult(
                    status=SourceCheckStatus.OK, parameter_coverage=coverage))
                self.assertEqual(result.status, SourceCheckStatus.MALFORMED)

    def test_unknown_category_is_dropped_and_the_message_is_redacted(self):
        result = self.norm(AvailabilityCheckResult(
            status=SourceCheckStatus.FAILED,
            category="MADE_UP",
            message="GET https://h/x?password=hunter2 failed",
        ))

        self.assertEqual(result.status, SourceCheckStatus.FAILED)
        self.assertIsNone(result.category)
        self.assertNotIn("hunter2", result.message)
