"""
Seam tests for the CSV a WIS2BOX Upload channel produces.

Real ObservationRecords go through the dispatch record fetch and the wis2box
CSV builder; assertions are on the CSV text. The expected AWS header is the
column list of the published csv2bufr AWS template
(https://training.wis2box.wis.wmo.int/csv2bufr-templates/aws-template/),
written out literally rather than read back from the template spec.
"""

import csv
from datetime import datetime, timezone as py_tz
from io import StringIO

from django.contrib.gis.geos import Point
from django.test import TestCase

from adl.core.dispatchers import get_station_dispatch_records
from adl.core.dispatchers.wis2box import channel_record_to_wis2box_csv
from adl.core.models import DispatchChannelParameterMapping, ObservationRecord
from .factories import (
    DataParameterFactory,
    StationFactory,
    StationLinkFactory,
    UnitFactory,
    Wis2BoxUploadFactory,
)

OBS_TIME = datetime(2025, 1, 1, 6, 0, tzinfo=py_tz.utc)

UNSET = object()

AWS_TEMPLATE_COLUMNS = [
    "wsi_series", "wsi_issuer", "wsi_issue_number", "wsi_local",
    "wmo_block_number", "wmo_station_number", "station_type",
    "year", "month", "day", "hour", "minute",
    "latitude", "longitude", "station_height_above_msl", "barometer_height_above_msl",
    "station_pressure", "msl_pressure", "geopotential_height", "thermometer_height",
    "air_temperature", "dewpoint_temperature", "relative_humidity",
    "method_of_ground_state_measurement", "ground_state",
    "method_of_snow_depth_measurement", "snow_depth", "precipitation_intensity",
    "anemometer_height", "time_period_of_wind", "wind_direction", "wind_speed",
    "maximum_wind_gust_direction_10_minutes", "maximum_wind_gust_speed_10_minutes",
    "maximum_wind_gust_direction_1_hour", "maximum_wind_gust_speed_1_hour",
    "maximum_wind_gust_direction_3_hours", "maximum_wind_gust_speed_3_hours",
    "rain_sensor_height", "total_precipitation_1_hour", "total_precipitation_3_hours",
    "total_precipitation_6_hours", "total_precipitation_12_hours",
    "total_precipitation_24_hours",
]


class Wis2BoxCsvTestCase(TestCase):
    def setUp(self):
        self.station = StationFactory(location=Point(36.8, -1.3), thermometer_height=1.25)
        self.link = StationLinkFactory(station=self.station)
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)

    def map_and_observe(self, channel_parameter, value, param=None, channel_unit=UNSET):
        param = param or DataParameterFactory()
        DispatchChannelParameterMapping.objects.create(
            dispatch_channel=self.channel,
            parameter=param,
            channel_parameter=channel_parameter,
            channel_unit=param.unit if channel_unit is UNSET else channel_unit,
        )
        ObservationRecord.objects.create(
            station=self.station,
            connection=self.link.network_connection,
            parameter=param,
            value=value,
            time=OBS_TIME,
        )

    def build_csv(self):
        [record] = get_station_dispatch_records(self.channel, self.link)
        csv_content, _filename = channel_record_to_wis2box_csv(self.channel, record)
        reader = csv.DictReader(StringIO(csv_content))
        [row] = list(reader)
        return reader.fieldnames, row


class AwsTemplateCsvTests(Wis2BoxCsvTestCase):
    def test_channels_default_to_the_aws_template(self):
        self.assertEqual(self.channel.template, "aws")

    def test_header_is_the_aws_template_columns_in_order(self):
        self.map_and_observe("air_temperature", 20.0)

        header, _row = self.build_csv()

        self.assertEqual(header, AWS_TEMPLATE_COLUMNS)

    def test_mapped_observation_lands_in_its_column(self):
        kelvin = UnitFactory(name="Kelvin", symbol="K")
        self.map_and_observe("air_temperature", 293.15, param=DataParameterFactory(unit=kelvin))

        _header, row = self.build_csv()

        self.assertEqual(row["air_temperature"], "293.15")
        self.assertEqual(row["wind_speed"], "")

    def test_station_and_timestamp_columns_come_from_the_station_and_time(self):
        self.map_and_observe("air_temperature", 20.0)

        _header, row = self.build_csv()

        self.assertEqual(row["latitude"], "-1.3")
        self.assertEqual(row["longitude"], "36.8")
        self.assertEqual(
            [row["year"], row["month"], row["day"], row["hour"], row["minute"]],
            ["2025", "1", "1", "6", "0"],
        )

    def test_a_mapping_cannot_overwrite_a_station_column(self):
        self.map_and_observe("latitude", 99.0)

        _header, row = self.build_csv()

        self.assertEqual(row["latitude"], "-1.3")

    def test_a_mapping_cannot_overwrite_a_timestamp_column(self):
        self.map_and_observe("year", 1999)

        _header, row = self.build_csv()

        self.assertEqual(row["year"], "2025")

    def test_thermometer_height_comes_from_the_station(self):
        self.map_and_observe("air_temperature", 20.0)

        _header, row = self.build_csv()

        self.assertEqual(row["thermometer_height"], "1.25")


class TemplateUnitTests(Wis2BoxCsvTestCase):
    """The csv2bufr template's unit wins over the unit stored on the mapping."""

    def unit(self, name, symbol):
        return UnitFactory(name=name, symbol=symbol)

    def test_a_wrong_stored_channel_unit_is_ignored(self):
        hpa = self.unit("Hectopascal", "hPa")
        pressure = DataParameterFactory(unit=hpa)
        # the stored unit claims the template wants hPa; it wants Pa
        self.map_and_observe("station_pressure", 1013.2, param=pressure, channel_unit=hpa)

        _header, row = self.build_csv()

        self.assertAlmostEqual(float(row["station_pressure"]), 101320.0, places=3)

    def test_values_are_converted_to_the_template_unit(self):
        # DataParameterFactory defaults to degC; the template wants Kelvin
        self.map_and_observe("air_temperature", 20.0)

        _header, row = self.build_csv()

        self.assertAlmostEqual(float(row["air_temperature"]), 293.15, places=3)

    def test_a_blank_stored_channel_unit_still_gets_the_template_unit(self):
        self.map_and_observe("air_temperature", 20.0, channel_unit=None)

        # a blank unit never published anything wrong, so there is nothing to flag
        with self.assertNoLogs("adl.core.models", level="WARNING"):
            _header, row = self.build_csv()

        self.assertAlmostEqual(float(row["air_temperature"]), 293.15, places=3)

    def test_precipitation_in_mm_is_published_in_kg_per_square_metre(self):
        # no custom unit context on the parameter: the template column supplies it
        rainfall = DataParameterFactory(unit=self.unit("Millimetre", "mm"))
        self.map_and_observe("total_precipitation_1_hour", 2.4, param=rainfall)

        _header, row = self.build_csv()

        self.assertAlmostEqual(float(row["total_precipitation_1_hour"]), 2.4, places=6)

    def test_a_column_without_a_unit_is_sent_as_is(self):
        code = DataParameterFactory(unit=self.unit("Code", "dimensionless"))
        self.map_and_observe("ground_state", 4, param=code)

        _header, row = self.build_csv()

        self.assertEqual(float(row["ground_state"]), 4)

    def test_a_stored_unit_that_differs_from_the_template_is_logged(self):
        hpa = self.unit("Hectopascal", "hPa")
        pressure = DataParameterFactory(unit=hpa)
        self.map_and_observe("station_pressure", 1013.2, param=pressure, channel_unit=hpa)

        with self.assertLogs("adl.core.models", level="WARNING") as logs:
            self.build_csv()

        [message] = logs.output
        self.assertIn(self.channel.name, message)
        self.assertIn("station_pressure", message)
        self.assertIn("hPa", message)
        self.assertIn("Pa", message)

    def test_a_stored_unit_matching_the_template_is_not_logged(self):
        kelvin = self.unit("Kelvin", "K")
        temperature = DataParameterFactory(unit=kelvin)
        self.map_and_observe("air_temperature", 293.15, param=temperature, channel_unit=kelvin)

        with self.assertNoLogs("adl.core.models", level="WARNING"):
            self.build_csv()

    def test_a_unit_that_cannot_convert_to_the_template_unit_is_left_out(self):
        # a parameter whose unit is not a pressure cannot fill station_pressure;
        # the rest of the row must still go out
        self.map_and_observe("air_temperature", 20.0)
        rainfall = DataParameterFactory(unit=self.unit("Millimetre", "mm"))
        self.map_and_observe("station_pressure", 3.0, param=rainfall)

        with self.assertLogs("adl.core.models", level="ERROR") as logs:
            _header, row = self.build_csv()

        self.assertEqual(row["station_pressure"], "")
        self.assertAlmostEqual(float(row["air_temperature"]), 293.15, places=3)
        [message] = logs.output
        self.assertIn("station_pressure", message)
        self.assertIn("mm", message)

    def test_precipitation_stored_in_mm_is_not_logged(self):
        # 1 mm of rain is 1 kg m-2: the channel was already sending the right numbers
        mm = self.unit("Millimetre", "mm")
        rainfall = DataParameterFactory(unit=mm)
        self.map_and_observe("total_precipitation_1_hour", 2.4, param=rainfall, channel_unit=mm)

        with self.assertNoLogs("adl.core.models", level="WARNING"):
            self.build_csv()

    def test_a_stored_unit_mismatch_is_logged_once_not_on_every_run(self):
        hpa = self.unit("Hectopascal", "hPa")
        pressure = DataParameterFactory(unit=hpa)
        self.map_and_observe("station_pressure", 1013.2, param=pressure, channel_unit=hpa)

        with self.assertLogs("adl.core.models", level="WARNING") as logs:
            self.build_csv()
            self.build_csv()

        self.assertEqual(len(logs.output), 1)

    def test_the_channel_data_path_also_uses_the_template_unit(self):
        # get_data_records_by_station builds records separately from the
        # per-station path; both must send the template's unit
        self.map_and_observe("air_temperature", 20.0)

        records_by_station = self.channel.get_data_records_by_station()

        [record] = records_by_station[self.station.id]
        self.assertAlmostEqual(record["values"]["air_temperature"], 293.15, places=3)
