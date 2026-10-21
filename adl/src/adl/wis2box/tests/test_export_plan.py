"""
Seam tests for planning a wis2box station bulk-insert export.

``plan_wis2box_export`` is pure: it takes the ADL stations, the WIGOS ids
wis2box already holds, and raw OSCAR search records, and decides per
ADL-only station whether it can go into the CSV and with what values.
ADL contributes only the WIGOS id; everything else must come from OSCAR.
"""

from django.test import TestCase

from adl.core.tests.factories import StationFactory
from adl.wis2box.export import plan_wis2box_export, ELIGIBLE, NOT_IN_OSCAR, INVALID_OSCAR_DATA


def oscar_record(wigos_id, **overrides):
    """A raw OSCAR station-search record, as returned for a country query."""
    record = {
        "name": "BALAKA",
        "region": "Africa",
        "territory": "Malawi",
        "latitude": -14.983333,
        "longitude": 34.966666,
        "elevation": 618,
        "stationTypeName": "Land (fixed)",
        "wigosId": wigos_id,
        "wigosStationIdentifiers": [{"wigosStationIdentifier": wigos_id, "primary": True}],
    }
    record.update(overrides)
    return record


class PlanWis2BoxExportTests(TestCase):
    def test_matched_station_takes_every_value_from_oscar(self):
        station = StationFactory(station_id="0-454-2-AWSBALAKA", name="Balaka ADL name")

        rows = plan_wis2box_export([station], set(), [oscar_record("0-454-2-AWSBALAKA")])

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.status, ELIGIBLE)
        self.assertEqual(row.values, {
            "station_name": "BALAKA",
            "wigos_station_identifier": "0-454-2-AWSBALAKA",
            "traditional_station_identifier": "",
            "facility_type": "landFixed",
            "latitude": -14.983333,
            "longitude": 34.966666,
            "elevation": 618,
            "territory_name": "MWI",
            "wmo_region": "africa",
        })

    def test_station_already_on_wis2box_is_left_out(self):
        on_wis2box = StationFactory(station_id="0-20000-0-67693")
        missing = StationFactory(station_id="0-454-2-AWSBALAKA")

        rows = plan_wis2box_export(
            [on_wis2box, missing],
            {"0-20000-0-67693"},
            [oscar_record("0-20000-0-67693"), oscar_record("0-454-2-AWSBALAKA")],
        )

        self.assertEqual([row.station for row in rows], [missing])

    def test_station_missing_from_oscar_is_excluded(self):
        station = StationFactory(station_id="0-454-2-AWSNEW")

        rows = plan_wis2box_export([station], set(), [oscar_record("0-454-2-AWSBALAKA")])

        self.assertEqual(rows[0].status, NOT_IN_OSCAR)
        self.assertEqual(rows[0].values, {})

    def test_station_matches_a_secondary_oscar_identifier(self):
        station = StationFactory(station_id="0-20000-0-67693")
        record = oscar_record(
            "0-454-2-AWSBALAKA",
            wigosStationIdentifiers=[
                {"wigosStationIdentifier": "0-454-2-AWSBALAKA", "primary": True},
                {"wigosStationIdentifier": "0-20000-0-67693", "primary": False},
            ],
        )

        rows = plan_wis2box_export([station], set(), [record])

        self.assertEqual(rows[0].status, ELIGIBLE)
        self.assertEqual(rows[0].values["wigos_station_identifier"], "0-20000-0-67693")

    def test_oscar_label_without_a_wmdr_code_excludes_the_station(self):
        station = StationFactory(station_id="0-454-2-AWSBALAKA")
        record = oscar_record("0-454-2-AWSBALAKA", territory="Republic of Nowhere")

        rows = plan_wis2box_export([station], set(), [record])

        self.assertEqual(rows[0].status, INVALID_OSCAR_DATA)
        self.assertIn("territory_name", rows[0].reason)
        self.assertIn("Republic of Nowhere", rows[0].reason)

    def test_fixed_station_without_elevation_in_oscar_is_excluded(self):
        # wis2box refuses a fixed station whose coordinates are not all numeric
        station = StationFactory(station_id="0-454-2-AWSBALAKA")
        record = oscar_record("0-454-2-AWSBALAKA", elevation=None)

        rows = plan_wis2box_export([station], set(), [record])

        self.assertEqual(rows[0].status, INVALID_OSCAR_DATA)
        self.assertIn("elevation", rows[0].reason)

    def test_traditional_identifier_is_the_local_part_of_a_20000_issued_id(self):
        # As in wis2box's own fixture: 0-20000-0-16337 -> 16337
        station = StationFactory(station_id="0-20000-0-67693")

        rows = plan_wis2box_export([station], set(), [oscar_record("0-20000-0-67693")])

        self.assertEqual(rows[0].values["traditional_station_identifier"], "67693")
