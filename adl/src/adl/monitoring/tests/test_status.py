from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as dj_timezone

from adl.core.tests.factories import NetworkConnectionFactory, Wis2BoxUploadFactory
from adl.monitoring.status import (
    ACTIVE,
    ERROR,
    WARNING,
    StatusThresholds,
    compute_station_status,
    connection_thresholds,
    dispatch_channel_thresholds,
)

# 15 min pipeline tolerance, 20 min / 60 min freshness — round numbers to
# make the boundary assertions below readable.
THRESHOLDS = StatusThresholds(
    pipeline_tolerance=timedelta(minutes=15),
    freshness_warning_limit=timedelta(minutes=20),
    freshness_error_limit=timedelta(minutes=60),
)


class ComputeStationStatusTests(TestCase):
    def setUp(self):
        self.now = dj_timezone.now()

    def status(self, last_check=None, last_check_success=True, last_data_time=None):
        return compute_station_status(
            last_check=last_check,
            last_check_success=last_check_success,
            last_data_time=last_data_time,
            thresholds=THRESHOLDS,
            now=self.now,
        )

    def ago(self, **kwargs):
        return self.now - timedelta(**kwargs)

    def test_healthy_station_is_active_on_both_axes(self):
        status = self.status(last_check=self.ago(minutes=2), last_data_time=self.ago(minutes=5))

        self.assertEqual(status.pipeline_status, ACTIVE)
        self.assertEqual(status.data_status, ACTIVE)
        self.assertEqual(status.overall_status, ACTIVE)

    def test_never_checked_station_warns_on_both_axes(self):
        status = self.status(last_check=None, last_data_time=None)

        self.assertEqual(status.pipeline_status, WARNING)
        self.assertEqual(status.data_status, WARNING)
        self.assertEqual(status.overall_status, WARNING)

    def test_last_run_failed_is_a_pipeline_error(self):
        status = self.status(
            last_check=self.ago(minutes=2),
            last_check_success=False,
            last_data_time=self.ago(minutes=5),
        )

        self.assertEqual(status.pipeline_status, ERROR)
        self.assertEqual(status.data_status, ACTIVE)
        self.assertEqual(status.overall_status, ERROR)

    def test_failed_run_outranks_staleness_of_the_check_itself(self):
        # An old *and* failed check is an error, not a scheduler warning.
        status = self.status(last_check=self.ago(hours=5), last_check_success=False)

        self.assertEqual(status.pipeline_status, ERROR)

    def test_scheduler_stopped_warns_even_though_last_run_succeeded(self):
        status = self.status(last_check=self.ago(minutes=16), last_data_time=self.ago(minutes=5))

        self.assertEqual(status.pipeline_status, WARNING)
        self.assertEqual(status.data_status, ACTIVE)
        self.assertEqual(status.overall_status, WARNING)

    def test_check_exactly_at_tolerance_is_still_active(self):
        status = self.status(last_check=self.ago(minutes=15))

        self.assertEqual(status.pipeline_status, ACTIVE)

    def test_stale_data_is_a_data_error(self):
        status = self.status(last_check=self.ago(minutes=2), last_data_time=self.ago(minutes=61))

        self.assertEqual(status.pipeline_status, ACTIVE)
        self.assertEqual(status.data_status, ERROR)
        self.assertEqual(status.overall_status, ERROR)

    def test_ageing_data_warns_before_it_errors(self):
        status = self.status(last_check=self.ago(minutes=2), last_data_time=self.ago(minutes=30))

        self.assertEqual(status.data_status, WARNING)
        self.assertEqual(status.overall_status, WARNING)

    def test_data_exactly_at_each_freshness_limit_takes_the_kinder_status(self):
        self.assertEqual(self.status(last_data_time=self.ago(minutes=20)).data_status, ACTIVE)
        self.assertEqual(self.status(last_data_time=self.ago(minutes=60)).data_status, WARNING)

    def test_missing_data_warns_even_when_the_pipeline_is_healthy(self):
        status = self.status(last_check=self.ago(minutes=2), last_data_time=None)

        self.assertEqual(status.pipeline_status, ACTIVE)
        self.assertEqual(status.data_status, WARNING)
        self.assertEqual(status.overall_status, WARNING)

    def test_error_on_either_axis_wins_the_roll_up(self):
        status = self.status(
            last_check=self.ago(minutes=16),  # warning
            last_data_time=self.ago(minutes=61),  # error
        )

        self.assertEqual(status.overall_status, ERROR)

    def test_now_defaults_to_the_current_time(self):
        status = compute_station_status(
            last_check=dj_timezone.now(),
            last_check_success=True,
            last_data_time=dj_timezone.now(),
            thresholds=THRESHOLDS,
        )

        self.assertEqual(status.overall_status, ACTIVE)


class ConnectionThresholdsTests(TestCase):
    def test_high_frequency_limits_scale_with_the_interval(self):
        connection = NetworkConnectionFactory(plugin_processing_interval=15, is_daily_data=False)

        thresholds = connection_thresholds(connection)

        self.assertEqual(thresholds.pipeline_tolerance, timedelta(minutes=45))
        self.assertEqual(thresholds.freshness_warning_limit, timedelta(minutes=60))
        self.assertEqual(thresholds.freshness_error_limit, timedelta(minutes=180))

    def test_daily_connections_use_fixed_freshness_limits(self):
        connection = NetworkConnectionFactory(plugin_processing_interval=60, is_daily_data=True)

        thresholds = connection_thresholds(connection)

        self.assertEqual(thresholds.pipeline_tolerance, timedelta(minutes=180))
        self.assertEqual(thresholds.freshness_warning_limit, timedelta(hours=26))
        self.assertEqual(thresholds.freshness_error_limit, timedelta(hours=48))


class DispatchChannelThresholdsTests(TestCase):
    def test_limits_scale_with_the_check_interval(self):
        channel = Wis2BoxUploadFactory(data_check_interval=10, send_aggregated_data=False)

        thresholds = dispatch_channel_thresholds(channel)

        self.assertEqual(thresholds.pipeline_tolerance, timedelta(minutes=30))
        self.assertEqual(thresholds.freshness_warning_limit, timedelta(minutes=40))
        self.assertEqual(thresholds.freshness_error_limit, timedelta(minutes=120))

    def test_hourly_aggregation_buys_the_window_plus_slack(self):
        channel = Wis2BoxUploadFactory(
            data_check_interval=10,
            send_aggregated_data=True,
            aggregation_period="hourly",
        )

        thresholds = dispatch_channel_thresholds(channel)

        offset = timedelta(hours=2, minutes=5)
        self.assertEqual(thresholds.pipeline_tolerance, timedelta(minutes=30))
        self.assertEqual(thresholds.freshness_warning_limit, timedelta(minutes=40) + offset)
        self.assertEqual(thresholds.freshness_error_limit, timedelta(minutes=120) + offset)

    def test_daily_aggregation_buys_a_day_plus_slack(self):
        channel = Wis2BoxUploadFactory(
            data_check_interval=10,
            send_aggregated_data=True,
            aggregation_period="daily",
        )

        thresholds = dispatch_channel_thresholds(channel)

        offset = timedelta(days=1, minutes=5)
        self.assertEqual(thresholds.freshness_warning_limit, timedelta(minutes=40) + offset)
        self.assertEqual(thresholds.freshness_error_limit, timedelta(minutes=120) + offset)
