from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TestCase

from adl.core.models import StationChannelDispatchStatus, Wis2BoxUpload
from adl.core.tasks import dispatch_station, perform_channel_dispatch
from adl.monitoring.models import StationLinkActivityLog
from .factories import StationLinkFactory, Wis2BoxUploadFactory


class DispatchStationTests(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()
        self.channel.network_connections.add(self.link.network_connection)
        self.obs_time = datetime(2025, 1, 1, 12, 0, tzinfo=py_tz.utc)
        self.records = [
            {
                "station_id": self.link.station_id,
                "timestamp": self.obs_time,
                "values": {"air_temperature": 20.0},
            }
        ]

    def test_successful_dispatch_logs_completed_and_advances_checkpoint(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", return_value=(1, self.obs_time)):
            result = dispatch_station(self.channel.id, self.link.id)

        self.assertEqual(result, {"records_sent": 1})

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.direction, "push")
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.COMPLETED)
        self.assertTrue(log.success)
        self.assertEqual(log.records_count, 1)
        self.assertEqual(log.dispatch_channel_id, self.channel.id)
        self.assertIsNotNone(log.duration_ms)

        checkpoint = StationChannelDispatchStatus.objects.get(
            channel=self.channel, station=self.link.station
        )
        self.assertEqual(checkpoint.last_sent_obs_time, self.obs_time)


    def test_timed_out_dispatch_logged_as_failed_without_raising(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", side_effect=SoftTimeLimitExceeded()):
            dispatch_station(self.channel.id, self.link.id)  # must not raise

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("timed out", log.message)
        self.assertIsNotNone(log.duration_ms)
        # no checkpoint advance on timeout
        self.assertFalse(StationChannelDispatchStatus.objects.exists())


    def test_send_failure_logged_as_failed_and_reraised(self):
        with patch("adl.core.tasks.get_station_dispatch_records", return_value=self.records), \
                patch.object(Wis2BoxUpload, "send_station_data", side_effect=RuntimeError("bucket unreachable")):
            with self.assertRaises(RuntimeError):
                dispatch_station(self.channel.id, self.link.id)

        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.FAILED)
        self.assertFalse(log.success)
        self.assertIn("bucket unreachable", log.message)
        self.assertIsNotNone(log.duration_ms)


class PerformChannelDispatchTests(TestCase):
    def test_station_tasks_enqueued_with_channel_timeout_limits(self):
        link = StationLinkFactory()
        channel = Wis2BoxUploadFactory(dispatch_timeout_seconds=120)
        channel.network_connections.add(link.network_connection)

        with patch("adl.core.tasks.dispatch_station.apply_async") as mock_apply:
            perform_channel_dispatch(channel.id)

        mock_apply.assert_called_once()
        kwargs = mock_apply.call_args.kwargs
        self.assertEqual(kwargs["args"], [channel.id, link.id])
        self.assertEqual(kwargs["soft_time_limit"], 120)
        self.assertEqual(kwargs["time_limit"], 150)  # soft + 30s grace
