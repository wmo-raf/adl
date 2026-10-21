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
    Wis2BoxUploadFactory,
)

OBS_TIME = datetime(2025, 1, 1, 6, 0, tzinfo=py_tz.utc)

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

    def map_and_observe(self, channel_parameter, value):
        param = DataParameterFactory()
        DispatchChannelParameterMapping.objects.create(
            dispatch_channel=self.channel,
            parameter=param,
            channel_parameter=channel_parameter,
            channel_unit=param.unit,
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
        self.map_and_observe("air_temperature", 20.0)

        _header, row = self.build_csv()

        self.assertEqual(row["air_temperature"], "20.0")
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
