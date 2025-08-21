from datetime import datetime, timezone as py_tz
from types import SimpleNamespace

import pytest

from adl.core.models import ObservationRecord
from .factories import (
    StationLinkFactory,
    DataParameterFactory,
    KelvinUnitFactory,
    CelsiusUnitFactory,
)


@pytest.mark.django_db
def test_happy_path_kelvin_to_celsius(monkeypatch, test_plugin):
    link = StationLinkFactory()
    unit_c = CelsiusUnitFactory()
    unit_k = KelvinUnitFactory()
    param_temp = DataParameterFactory(name="air_temperature", unit=unit_c)
    
    # Map vendor field `temp_K` (Kelvin) -> ADL param (degC)
    mapping = SimpleNamespace(
        id=1,
        adl_parameter=param_temp,
        source_parameter_name="temp_K",
        source_parameter_unit=unit_k,
    )
    monkeypatch.setattr(link, "get_variable_mappings", lambda: [mapping])
    
    # 293.15 K ≈ 20 °C
    ts = datetime(2025, 1, 1, 12, 0, tzinfo=py_tz.utc)
    test_plugin.records = [{"observation_time": ts, "temp_K": 293.15}]
    
    saved = test_plugin.save_records(link, test_plugin.records)
    assert saved and len(saved) == 1
    
    rec = ObservationRecord.objects.get()
    assert abs(rec.value - 20.0) < 0.01
    # Django stores UTC internally; utc_time should equal original instant
    assert rec.utc_time.replace(tzinfo=py_tz.utc) == ts


@pytest.mark.django_db
def test_reject_non_numeric_value(monkeypatch, test_plugin):
    link = StationLinkFactory()
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
    
    test_plugin.records = [{"observation_time": datetime.now(py_tz.utc), "temp_K": "oops"}]
    
    saved = test_plugin.save_records(link, test_plugin.records)
    assert saved is None
    assert ObservationRecord.objects.count() == 0


@pytest.mark.django_db
def test_missing_observation_time_is_skipped(monkeypatch, test_plugin):
    link = StationLinkFactory()
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
    
    test_plugin.records = [{"temp_K": 300.0}]  # no observation_time
    saved = test_plugin.save_records(link, test_plugin.records)
    
    assert saved is None
    assert ObservationRecord.objects.count() == 0


@pytest.mark.django_db
def test_upsert_on_conflict(monkeypatch, test_plugin):
    link = StationLinkFactory()
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
    
    ts = datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc)
    
    # Insert
    test_plugin.records = [{"observation_time": ts, "temp_K": 293.15}]  # ~20C
    test_plugin.save_records(link, test_plugin.records)
    
    # Update same natural key => 294.15K (~21C)
    test_plugin.records = [{"observation_time": ts, "temp_K": 294.15}]
    test_plugin.save_records(link, test_plugin.records)
    
    assert ObservationRecord.objects.count() == 1
    rec = ObservationRecord.objects.get()
    assert abs(rec.value - 21.0) < 0.01
