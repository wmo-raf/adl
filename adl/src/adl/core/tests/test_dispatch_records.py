from datetime import datetime, timedelta, timezone as py_tz

from django.test import TestCase

from adl.core.dispatchers import get_station_dispatch_records
from adl.core.models import (
    DispatchChannelParameterMapping,
    ObservationRecord,
    StationChannelDispatchStatus,
)
from .factories import (
    DataParameterFactory,
    StationLinkFactory,
    UnitFactory,
    Wis2BoxUploadFactory,
)

BASE_TIME = datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc)


class DispatchRecordFetchTestCase(TestCase):
    """Seam: the record-fetching path, with real ObservationRecords — no mocks."""

    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = self.make_channel()
        self.param = DataParameterFactory(name="air_temperature")
        self.map_parameter(self.param)

    def make_channel(self, **kwargs):
        channel = Wis2BoxUploadFactory(**kwargs)
        channel.network_connections.add(self.link.network_connection)
        return channel

    def map_parameter(self, param, channel=None):
        DispatchChannelParameterMapping.objects.create(
            dispatch_channel=channel or self.channel,
            parameter=param,
            channel_parameter=param.name,
            channel_unit=param.unit,
        )

    def seed_observations(self, hours, param=None, value=20.0):
        for h in hours:
            ObservationRecord.objects.create(
                station=self.link.station,
                connection=self.link.network_connection,
                parameter=param or self.param,
                value=value,
                time=BASE_TIME + timedelta(hours=h),
            )

    def record_times(self, records):
        return [r["timestamp"] for r in records]


class DispatchRecordCapTests(DispatchRecordFetchTestCase):
    def test_cap_returns_oldest_records_first(self):
        self.channel = self.make_channel(max_records_per_dispatch=2)
        self.map_parameter(self.param)
        self.seed_observations(hours=[0, 1, 2, 3, 4])

        records = get_station_dispatch_records(self.channel, self.link)

        self.assertEqual(len(records), 2)
        self.assertEqual(
            self.record_times(records),
            [BASE_TIME, BASE_TIME + timedelta(hours=1)],
        )

    def test_cap_counts_observation_times_not_rows(self):
        """A capped run must never split one observation time's parameters."""
        self.channel = self.make_channel(max_records_per_dispatch=2)
        self.map_parameter(self.param)
        humidity = DataParameterFactory(
            name="relative_humidity", unit=UnitFactory(name="Percent", symbol="pct")
        )
        self.map_parameter(humidity)

        # 3 observation times x 2 parameters = 6 rows
        self.seed_observations(hours=[0, 1, 2], param=self.param, value=20.0)
        self.seed_observations(hours=[0, 1, 2], param=humidity, value=55.0)

        records = get_station_dispatch_records(self.channel, self.link)

        self.assertEqual(len(records), 2)  # 2 times, not 2 rows
        for record in records:
            self.assertEqual(
                set(record["values"].keys()),
                {"air_temperature", "relative_humidity"},
            )

    def test_resumes_after_last_sent_obs_time(self):
        self.seed_observations(hours=[0, 1, 2, 3])
        StationChannelDispatchStatus.objects.create(
            channel=self.channel,
            station=self.link.station,
            last_sent_obs_time=BASE_TIME + timedelta(hours=1),
        )

        records = get_station_dispatch_records(self.channel, self.link)

        self.assertEqual(
            self.record_times(records),
            [BASE_TIME + timedelta(hours=2), BASE_TIME + timedelta(hours=3)],
        )

    def test_backlog_drains_across_runs_without_duplicates(self):
        self.channel = self.make_channel(max_records_per_dispatch=2)
        self.map_parameter(self.param)
        self.seed_observations(hours=[0, 1, 2, 3, 4])

        delivered = []
        for _ in range(10):  # more rounds than needed; loop must go quiet
            records = get_station_dispatch_records(self.channel, self.link)
            if not records:
                break
            delivered.extend(self.record_times(records))
            # advance the checkpoint like dispatch_station does after a send
            StationChannelDispatchStatus.objects.update_or_create(
                channel=self.channel,
                station=self.link.station,
                defaults={"last_sent_obs_time": records[-1]["timestamp"]},
            )

        expected = [BASE_TIME + timedelta(hours=h) for h in range(5)]
        self.assertEqual(delivered, expected)  # complete, ordered, no duplicates
