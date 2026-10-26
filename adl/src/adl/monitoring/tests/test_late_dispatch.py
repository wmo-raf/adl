"""
Late dispatch at the gap-service seam: a recovered window is sent to a channel
without reading or moving the channel's dispatch cursor. The channel is a real
``DispatchChannel`` whose ``send_station_data`` is substituted; nothing is dialled.
"""

from datetime import datetime, timedelta, timezone as py_tz
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from adl.core.models import (
    DispatchChannel,
    DispatchChannelParameterMapping,
    DispatchChannelStationLink,
    ObservationRecord,
    StationChannelDispatchStatus,
)
from adl.core.tasks import dispatch_station_lock_key
from adl.core.tests.factories import (
    DataParameterFactory,
    NetworkConnectionFactory,
    StationLinkFactory,
)
from adl.monitoring import gap_service
from adl.monitoring.gap_service import InvalidWindow, late_dispatch_channels, send_window
from adl.monitoring.models import (
    TRIGGER_LATE_DISPATCH,
    AvailabilityCheck,
    StationLinkActivityLog,
)
from adl.monitoring.tasks import run_late_dispatch
from adl.core.source_checks import SourceCheckStatus
from adl.core.availability_checks import TIER_FETCH

UTC = py_tz.utc
START, END = datetime(2026, 3, 5, 6, tzinfo=UTC), datetime(2026, 3, 5, 9, tzinfo=UTC)


class LateDispatchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.connection = NetworkConnectionFactory(stations_timezone="UTC")
        self.link = StationLinkFactory(network_connection=self.connection)
        self.parameter = DataParameterFactory(name="air_temperature")
        self.channel = self.make_channel("Channel")
        self.check = AvailabilityCheck.objects.create(
            station_link=self.link, window_start=START, window_end=END, created_at=END,
            tier=TIER_FETCH, status=SourceCheckStatus.OK, ranges=[], recovered=True)

        self.sent = []

        def send(channel, station_link, records):
            self.sent.append(records)
            return len(records), records[-1]["timestamp"]

        patcher = patch.object(DispatchChannel, "send_station_data", send)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(
            run_late_dispatch, "delay",
            side_effect=lambda *args: run_late_dispatch.apply(args=args))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_channel(self, name):
        channel = DispatchChannel.objects.create(name=name)
        channel.network_connections.add(self.connection)
        DispatchChannelParameterMapping.objects.create(
            dispatch_channel=channel, parameter=self.parameter,
            channel_parameter="temp", channel_unit=self.parameter.unit)
        return channel

    def observe(self, *hours, value=20.0):
        for hour in hours:
            ObservationRecord.objects.create(
                station=self.link.station, connection=self.connection,
                parameter=self.parameter, value=value, time=START.replace(hour=hour))

    def test_only_eligible_channels_are_listed(self):
        disabled = self.make_channel("Disabled")
        DispatchChannelStationLink.objects.create(
            dispatch_channel=disabled, station_link=self.link, disabled=True)
        elsewhere = DispatchChannel.objects.create(name="Elsewhere")  # other connection

        channels = set(late_dispatch_channels(self.link))

        self.assertEqual(channels, {self.channel})
        self.assertNotIn(elsewhere, channels)
        with self.assertRaises(InvalidWindow):
            send_window(self.link, self.check.id, disabled.id)

    def test_sends_the_windows_records_shaped_as_in_normal_dispatch(self):
        self.observe(5, 6, 7, 8, 9)  # 5 and 9 lie outside [06:00, 09:00)

        send_window(self.link, self.check.id, self.channel.id)

        [records] = self.sent
        self.assertEqual([r["timestamp"] for r in records],
                         [START, START + timedelta(hours=1), START + timedelta(hours=2)])
        self.assertEqual(records[0]["values"], {"temp": 20.0})
        self.assertEqual(records[0]["wigos_id"], self.link.station.wigos_id)

    def test_the_dispatch_cursor_is_neither_read_nor_moved(self):
        self.observe(6, 7, 8)
        cursor = START + timedelta(hours=10)  # past the window: a read would skip it all
        StationChannelDispatchStatus.objects.create(
            channel=self.channel, station=self.link.station, last_sent_obs_time=cursor)

        send_window(self.link, self.check.id, self.channel.id)

        self.assertEqual(len(self.sent[0]), 3)
        status = StationChannelDispatchStatus.objects.get(channel=self.channel)
        self.assertEqual(status.last_sent_obs_time, cursor)

    def test_no_cursor_row_is_created(self):
        self.observe(6)

        send_window(self.link, self.check.id, self.channel.id)

        self.assertFalse(StationChannelDispatchStatus.objects.exists())

    def test_writes_an_activity_row_naming_the_window(self):
        self.observe(6, 7)

        send_window(self.link, self.check.id, self.channel.id)

        row = StationLinkActivityLog.objects.get(station_link=self.link)
        self.assertEqual(row.trigger, TRIGGER_LATE_DISPATCH)
        self.assertEqual(row.direction, "push")
        self.assertEqual(row.dispatch_channel, self.channel)
        self.assertEqual((row.obs_start_time, row.obs_end_time), (START, END))
        self.assertEqual(row.records_count, 2)
        self.assertTrue(row.success)
        self.assertIn("2026-03-05 06:00", row.message)

    def test_a_failing_channel_is_recorded_and_releases_the_lock(self):
        self.observe(6)

        with patch.object(DispatchChannel, "send_station_data", side_effect=RuntimeError("down")):
            result = run_late_dispatch.apply(args=(self.link.id, self.check.id, self.channel.id))

        self.assertIsInstance(result.result, RuntimeError)
        row = StationLinkActivityLog.objects.get(station_link=self.link)
        self.assertFalse(row.success)
        self.assertEqual(row.trigger, TRIGGER_LATE_DISPATCH)
        self.assertIsNone(cache.get(dispatch_station_lock_key(self.channel.id, self.link.id)))

    def test_a_held_dispatch_lock_means_busy_and_nothing_is_sent(self):
        self.observe(6)
        cache.set(dispatch_station_lock_key(self.channel.id, self.link.id), "locked", timeout=60)

        report = run_late_dispatch.apply(
            args=(self.link.id, self.check.id, self.channel.id)).result

        self.assertTrue(report["busy"])
        self.assertEqual(self.sent, [])
        self.assertFalse(StationLinkActivityLog.objects.exists())

    def test_only_a_recovered_check_of_the_link_can_be_sent(self):
        self.check.recovered = False
        self.check.save()
        with self.assertRaises(InvalidWindow):
            send_window(self.link, self.check.id, self.channel.id)
        with self.assertRaises(InvalidWindow):
            send_window(self.link, self.check.id + 99, self.channel.id)
