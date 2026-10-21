"""
Seam tests for the wis2box station-list CSV.

The expected text is fixed literal output in the shape of wis2box's own
``tests/data/metadata/station/station_list.csv`` fixture, which is what
``wis2box metadata station publish-collection`` reads with ``csv.DictReader``.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from adl.wis2box.export import ELIGIBLE, ExportRow, build_wis2box_station_csv


def eligible_row(**values):
    row_values = {
        "station_name": "BONIFATI",
        "wigos_station_identifier": "0-20000-0-16337",
        "traditional_station_identifier": "16337",
        "facility_type": "landFixed",
        "latitude": 39.5847222222,
        "longitude": 15.8913888889,
        "elevation": 484,
        "territory_name": "ITA",
        "wmo_region": "europe",
    }
    row_values.update(values)
    return ExportRow(station=SimpleNamespace(), status=ELIGIBLE, values=row_values)


class BuildWis2BoxStationCsvTests(SimpleTestCase):
    def test_writes_the_header_and_columns_wis2box_reads(self):
        csv_text = build_wis2box_station_csv([eligible_row()], {"0-20000-0-16337": 485.0})

        self.assertEqual(
            csv_text,
            "station_name,wigos_station_identifier,traditional_station_identifier,facility_type,"
            "latitude,longitude,elevation,barometer_height,territory_name,wmo_region\r\n"
            "BONIFATI,0-20000-0-16337,16337,landFixed,39.5847222222,15.8913888889,484,485.0,ITA,europe\r\n",
        )

    def test_quotes_a_station_name_containing_a_comma(self):
        csv_text = build_wis2box_station_csv(
            [eligible_row(station_name="BONIFATI, CALABRIA")], {"0-20000-0-16337": 485.0}
        )

        self.assertIn('\r\n"BONIFATI, CALABRIA",0-20000-0-16337,', csv_text)
