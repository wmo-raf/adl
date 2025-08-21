from datetime import datetime
from types import SimpleNamespace

import pytest

from adl.core.models import ObservationRecord
from .factories import StationLinkFactory, DataParameterFactory, KelvinUnitFactory, CelsiusUnitFactory


@pytest.mark.django_db
def test_naive_local_interpreted_as_station_tz(monkeypatch, test_plugin):
    """
    StationLink uses connection tz Africa/Nairobi (UTC+3).
    Naive 12:00 local -> stored instant corresponds to 09:00 UTC.
    """
    link = StationLinkFactory()  # tz Africa/Nairobi via connection
    unit_c = CelsiusUnitFactory()
    unit_k = KelvinUnitFactory()
    param_temp = DataParameterFactory(name="air_temperature", unit=unit_c)
    
    mapping = SimpleNamespace(
        id=1,
        adl_parameter=param_temp,
        source_parameter_name="temp_K",
        source_parameter_unit=unit_k,
    )
    monkeypatch.setattr(link, "get_variable_mappings", lambda: [mapping])
    
    naive_local = datetime(2025, 1, 1, 12, 0)  # naive, assumed station-local
    test_plugin.records = [{"observation_time": naive_local, "temp_K": 300.0}]
    test_plugin.save_records(link, test_plugin.records)
    
    rec = ObservationRecord.objects.get()
    # Should be 09:00 UTC after interpreting naive as Africa/Nairobi time
    assert rec.utc_time.hour == 9 and rec.utc_time.minute == 0
