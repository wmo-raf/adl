"""
Recovery of a window older than the hourly aggregate's 90-day refresh policy:
the read model must show the recovered hours present. The aggregate refresh
cannot run inside a transaction, hence ``TransactionTestCase``.
"""

from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from django.core.cache import cache
from django.test import TransactionTestCase

from adl.core import aggregates
from adl.core.models import (
    DataParameter,
    NetworkConnection,
    Station,
    StationLink,
    Network,
    Unit,
)
from adl.core.registries import plugin_registry
from adl.core.tests.factories import (
    CelsiusUnitFactory,
    DataParameterFactory,
    KelvinUnitFactory,
    NetworkConnectionFactory,
    ObservationRecordFactory,
    StationLinkFactory,
)
from adl.core.tests.helpers import make_mapping, make_test_plugin
from adl.monitoring import gap_service
from adl.monitoring.availability import missing_hours
from adl.monitoring.tasks import run_gap_recovery

UTC = py_tz.utc
NOW = datetime(2026, 10, 1, tzinfo=UTC)
FLOOR = datetime(2025, 1, 1, tzinfo=UTC)
START, END = datetime(2025, 1, 5, 6, tzinfo=UTC), datetime(2025, 1, 5, 9, tzinfo=UTC)


class OldWindowRecoveryTests(TransactionTestCase):
    def _fixture_teardown(self):
        # see core/tests/test_aggregate_refresh.py: a flush breaks cached content types
        for model in (NetworkConnection, Station, DataParameter, Unit, Network):
            model.objects.all().delete()

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.plugin = make_test_plugin()
        self.parameter = DataParameterFactory(unit=CelsiusUnitFactory())
        mapping = make_mapping(self.parameter, KelvinUnitFactory(), source_name="te")
        self.link = StationLinkFactory(
            network_connection=NetworkConnectionFactory(stations_timezone="UTC"))
        self.plugin.records = [
            {"observation_time": START.replace(hour=hour, minute=10), "te": 293.15}
            for hour in (6, 7, 8)
        ]
        # move the aggregate's watermark past the old window, as the policy does
        # kept below the other tests' data: the watermark never moves back
        ObservationRecordFactory(time=datetime(2025, 6, 1, 5, tzinfo=UTC))
        aggregates.refresh_hourly_aggregate(
            datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 2, tzinfo=UTC))
        for patcher in (
            patch.object(StationLink, "get_first_collection_date", lambda self: FLOOR),
            patch.object(StationLink, "get_variable_mappings", lambda self: [mapping]),
            patch.object(plugin_registry, "get", return_value=self.plugin),
            patch.object(run_gap_recovery, "delay",
                         side_effect=lambda *args: run_gap_recovery.apply(args=args)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_recovered_hours_of_an_old_window_are_present_in_the_read_model(self):
        self.assertEqual(len(missing_hours(self.link, START, END, None, now=NOW)), 3)

        gap_service.recover(self.link, START, END, now=NOW)

        self.assertEqual(missing_hours(self.link, START, END, None, now=NOW), [])
