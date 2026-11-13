"""
Hourly aggregated rows are labelled with the end of the hour they cover
(WMO convention, #401); the dispatch cursor keeps the start of the last
hour sent, so consecutive runs skip nothing.
"""
from datetime import datetime, timedelta, timezone as py_tz
from unittest.mock import patch

from django.core.cache import cache

from adl.core.dispatchers import get_station_dispatch_records
from adl.core.models import ObservationRecord, StationChannelDispatchStatus, Wis2BoxUpload
from adl.core.tasks import dispatch_station
from .test_dispatch_records import DispatchRecordFetchTestCase

HOUR = timedelta(hours=1)
# Recent, so the hours are above the aggregate's watermark on a kept test
# database (another test moves it past mid-2025) and HourlyObsAgg sees them
# in real time without a refresh.
TEN = (datetime.now(py_tz.utc) - timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)


class DispatchPeriodLabelTestCase(DispatchRecordFetchTestCase):
    def seed_hour(self, hour_start, minutes=(0, 20, 40), value=20.0):
        for m in minutes:
            ObservationRecord.objects.create(
                station=self.link.station,
                connection=self.link.network_connection,
                parameter=self.param,
                value=value,
                time=hour_start + timedelta(minutes=m),
            )

    def make_aggregating_channel(self, **kwargs):
        channel = self.make_channel(send_aggregated_data=True, aggregation_period="hourly", **kwargs)
        self.map_parameter(self.param, channel=channel)
        return channel


class AggregatedLabelTests(DispatchPeriodLabelTestCase):
    def test_hourly_row_is_labelled_with_the_end_of_its_hour(self):
        channel = self.make_aggregating_channel()
        self.seed_hour(TEN)

        records = get_station_dispatch_records(channel, self.link)

        self.assertEqual(self.record_times(records), [TEN + HOUR])

    def test_raw_dispatch_keeps_the_observation_time(self):
        self.seed_hour(TEN, minutes=(0, 20))

        records = get_station_dispatch_records(self.channel, self.link)

        self.assertEqual(
            self.record_times(records),
            [TEN, TEN + timedelta(minutes=20)],
        )

    def test_late_dispatch_window_labels_the_same_way(self):
        channel = self.make_aggregating_channel()
        self.seed_hour(TEN)
        self.seed_hour(TEN + HOUR)

        records = get_station_dispatch_records(channel, self.link, window=(TEN, TEN + HOUR))

        self.assertEqual(self.record_times(records), [TEN + HOUR])


class AggregatedCursorTests(DispatchPeriodLabelTestCase):
    def setUp(self):
        super().setUp()
        self.channel = self.make_aggregating_channel(max_records_per_dispatch=1)
        self.lock_key = f"lock:dispatch:{self.channel.id}:{self.link.id}"
        self.addCleanup(cache.delete, self.lock_key)
        self.sent = []

    def fake_send(self, station_link, records):
        self.sent.extend(r["timestamp"] for r in records)
        return len(records), records[-1]["timestamp"]

    def run_dispatch(self):
        with patch.object(Wis2BoxUpload, "send_station_data", side_effect=self.fake_send):
            dispatch_station(self.channel.id, self.link.id)

    def cursor(self):
        return StationChannelDispatchStatus.objects.get(
            channel=self.channel, station=self.link.station
        ).last_sent_obs_time

    def test_consecutive_runs_send_every_hour_once(self):
        for h in range(3):
            self.seed_hour(TEN + h * HOUR)

        for _ in range(5):  # more runs than hours; the extra ones send nothing
            self.run_dispatch()

        self.assertEqual(self.sent, [TEN + HOUR, TEN + 2 * HOUR, TEN + 3 * HOUR])

    def test_cursor_keeps_the_start_of_the_last_hour_sent(self):
        self.seed_hour(TEN)

        self.run_dispatch()

        self.assertEqual(self.sent, [TEN + HOUR])
        self.assertEqual(self.cursor(), TEN)

    def test_existing_cursor_resumes_with_the_next_hour(self):
        # A cursor written before the change: the start of the last hour sent
        for h in range(3):
            self.seed_hour(TEN + h * HOUR)
        StationChannelDispatchStatus.objects.create(
            channel=self.channel, station=self.link.station, last_sent_obs_time=TEN
        )

        self.run_dispatch()

        self.assertEqual(self.sent, [TEN + 2 * HOUR])  # the 11:00-11:59 hour
