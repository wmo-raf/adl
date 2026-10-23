from datetime import datetime, timedelta, timezone as py_tz
from unittest.mock import patch

from django.test import TransactionTestCase

from adl.core import aggregates
from adl.core.models import (
    DataParameter,
    HourlyObsAgg,
    Network,
    NetworkConnection,
    ObservationRecord,
    Station,
    Unit,
)
from adl.monitoring.models import StationLinkActivityLog
from .factories import (
    CelsiusUnitFactory,
    DataParameterFactory,
    KelvinUnitFactory,
    ObservationRecordFactory,
    StationLinkFactory,
)
from .helpers import make_mapping, make_test_plugin

# Well outside the aggregate's 90-day refresh policy
OLD_HOUR = datetime(2025, 1, 1, 10, 0, tzinfo=py_tz.utc)
WINDOW_START = datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc)
WINDOW_END = datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc)


class ExplicitWindowAggregateRefreshTests(TransactionTestCase):
    """The refresh cannot run inside a transaction, hence TransactionTestCase."""

    def _fixture_teardown(self):
        # Not the default flush: it truncates django_content_type and the
        # recreated ids no longer match the ones the app caches, which breaks
        # every later test on a kept test database. Delete only what this
        # class creates; the cascade takes the dependent rows.
        for model in (NetworkConnection, Station, DataParameter, Unit, Network):
            model.objects.all().delete()

    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()
        self.param = DataParameterFactory(name="air_temperature", unit=CelsiusUnitFactory())
        mapping = make_mapping(self.param, KelvinUnitFactory())
        self.link.get_variable_mappings = lambda: [mapping]
        self.plugin.records = [
            {"observation_time": OLD_HOUR + timedelta(minutes=m), "temp_K": 293.15}
            for m in (0, 20, 40)
        ]
        # Move the aggregate's watermark past the old window, as the refresh
        # policy does in production. Below the watermark, raw rows are
        # invisible to HourlyObsAgg until that window is refreshed.
        ObservationRecordFactory(time=datetime(2025, 6, 1, 5, 0, tzinfo=py_tz.utc))
        aggregates.refresh_hourly_aggregate(
            datetime(2025, 6, 1, tzinfo=py_tz.utc), datetime(2025, 6, 2, tzinfo=py_tz.utc)
        )
        patcher = patch.object(
            type(self.plugin), "get_dates_for_station",
            return_value=(WINDOW_START, WINDOW_END),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def agg_rows(self):
        return HourlyObsAgg.objects.filter(
            station=self.link.station, connection=self.link.network_connection
        )

    def test_old_window_appears_in_aggregate_after_explicit_dates_run(self):
        saved = self.plugin.process_station(
            self.link, initial_start_date=WINDOW_START, initial_end_date=WINDOW_END
        )

        self.assertEqual(saved, 3)
        row = self.agg_rows().get()
        self.assertEqual(row.bucket, OLD_HOUR)
        self.assertEqual(row.records_count, 3)

    def test_refresh_covers_only_the_saved_window_hour_aligned(self):
        with patch.object(
            aggregates, "refresh_hourly_aggregate", wraps=aggregates.refresh_hourly_aggregate
        ) as spy:
            self.plugin.process_station(
                self.link, initial_start_date=WINDOW_START, initial_end_date=WINDOW_END
            )

        spy.assert_called_once()
        start, end = aggregates.hour_aligned_window(*spy.call_args.args)
        self.assertEqual(start, OLD_HOUR)
        self.assertEqual(end, OLD_HOUR + timedelta(hours=1))

    def test_scheduled_run_without_explicit_dates_does_not_refresh(self):
        with patch.object(aggregates, "refresh_hourly_aggregate") as mock_refresh:
            self.plugin.process_station(self.link)

        mock_refresh.assert_not_called()

    def test_failing_refresh_is_logged_and_does_not_fail_ingestion(self):
        with patch.object(
            aggregates, "refresh_hourly_aggregate", side_effect=RuntimeError("cagg busy")
        ):
            saved = self.plugin.process_station(
                self.link, initial_start_date=WINDOW_START, initial_end_date=WINDOW_END
            )

        self.assertEqual(saved, 3)
        self.assertEqual(ObservationRecord.objects.filter(station=self.link.station).count(), 3)
        log = StationLinkActivityLog.objects.get()
        self.assertEqual(log.status, StationLinkActivityLog.ActivityStatus.COMPLETED)
        self.assertTrue(log.success)
