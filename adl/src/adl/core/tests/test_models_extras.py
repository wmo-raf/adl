import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone as dj_tz

from adl.core.models import ObservationRecord
from .factories import (
    StationLinkFactory,
    DataParameterFactory,
    UnitFactory,
    StationFactory,
)


@pytest.mark.django_db
def test_station_wigos_id_format():
    s = StationFactory(wsi_series=1, wsi_issuer=2, wsi_issue_number=3, wsi_local="ABC")
    assert s.wigos_id == "1-2-3-ABC"


@pytest.mark.django_db
def test_stationlink_timezone_switch():
    sl = StationLinkFactory(use_connection_timezone=True, timezone_info="UTC")
    # when use_connection_timezone=True, we expect connection tz (Africa/Nairobi)
    assert "Africa/Nairobi" in str(sl.timezone)
    # flip to station’s own tz
    sl.use_connection_timezone = False
    assert "UTC" in str(sl.timezone)


@pytest.mark.django_db
def test_cannot_change_parameter_unit_if_records_exist():
    param = DataParameterFactory()
    other_unit = UnitFactory(name="Millimetre", symbol="mm")
    sl = StationLinkFactory()
    
    ObservationRecord.objects.create(
        station=sl.station,
        connection=sl.network_connection,
        parameter=param,
        value=1.0,
        time=dj_tz.now(),
    )
    
    # attempting to change parameter.unit should fail validation
    param.unit = other_unit
    with pytest.raises(ValidationError):
        param.clean()
