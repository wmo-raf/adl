from datetime import datetime, timezone as py_tz
from types import SimpleNamespace

import pytest

from adl.core.models import StationLink
from .factories import (
    NetworkConnectionFactory,
    StationFactory,
    CelsiusUnitFactory,
    KelvinUnitFactory,
    DataParameterFactory
)


@pytest.mark.django_db
def test_runner_skips_disabled(monkeypatch, test_plugin):
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
    
    mapping = SimpleNamespace(
        id=1,
        adl_parameter=param_temp,
        source_parameter_name="temp_K",
        source_parameter_unit=unit_k,
    )
    monkeypatch.setattr(sl_enabled, "get_variable_mappings", lambda: [mapping])
    monkeypatch.setattr(sl_disabled, "get_variable_mappings", lambda: [mapping])
    
    test_plugin.records = [
        {"observation_time": datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc), "temp_K": 293.15}
    ]
    
    results = test_plugin.run_process(connection)
    
    # Only enabled link is processed and appears in results
    assert sl_enabled.station.id in results
    assert sl_disabled.station.id not in results
