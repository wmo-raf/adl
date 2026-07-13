from datetime import datetime, timezone as py_tz

from django.test import TestCase

from adl.core.models import StationLink
from .factories import (
    NetworkConnectionFactory,
    StationFactory,
    CelsiusUnitFactory,
    KelvinUnitFactory,
    DataParameterFactory,
)
from .helpers import make_test_plugin, make_mapping


class RunnerTests(TestCase):
    def test_runner_skips_disabled(self):
        plugin = make_test_plugin()
        connection = NetworkConnectionFactory()
        station1 = StationFactory()
        station2 = StationFactory()  # different station

        sl_enabled = StationLink.objects.create(
            network_connection=connection, station=station1, enabled=True,
            use_connection_timezone=True, timezone_info="UTC"
        )
        sl_disabled = StationLink.objects.create(
            network_connection=connection, station=station2, enabled=False,
            use_connection_timezone=True, timezone_info="UTC"
        )

        unit_c = CelsiusUnitFactory()
        unit_k = KelvinUnitFactory()
        param_temp = DataParameterFactory(name="air_temperature", unit=unit_c)

        mapping = make_mapping(param_temp, unit_k)
        sl_enabled.get_variable_mappings = lambda: [mapping]
        sl_disabled.get_variable_mappings = lambda: [mapping]

        plugin.records = [
            {"observation_time": datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc), "temp_K": 293.15}
        ]

        results = plugin.run_process(connection)

        # Only enabled link is processed and appears in results
        self.assertIn(sl_enabled.station.id, results)
        self.assertNotIn(sl_disabled.station.id, results)
