from datetime import datetime, timezone as py_tz

import pytest
from django.utils import timezone as dj_tz
from freezegun import freeze_time

from .factories import StationLinkFactory


@pytest.mark.django_db
@freeze_time("2025-01-01 11:30:00", tz_offset=3)  # Africa/Nairobi UTC+3
def test_dates_latest_window_is_one_hour_on_the_hour(test_plugin):
    link = StationLinkFactory()
    start, end = test_plugin.get_dates_for_station(link, latest=True)
    # invariants: aligned to hour, and 1-hour window
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start.minute == 0 and start.second == 0 and start.microsecond == 0
    assert end.minute == 0 and end.second == 0 and end.microsecond == 0
    assert (end - start).total_seconds() == 3600


@pytest.mark.django_db
def test_dates_use_latest_from_db_when_available(test_plugin):
    link = StationLinkFactory()
    # seed a record at 08:00 UTC (== 11:00 in Nairobi)
    t_utc = datetime(2025, 1, 1, 8, 0, tzinfo=py_tz.utc)
    from adl.core.models import ObservationRecord, DataParameter, Unit
    unit = Unit.objects.create(name="Celsius", symbol="degC")
    param = DataParameter.objects.create(name="T", unit=unit)
    
    ObservationRecord.objects.create(
        station=link.station,
        connection=link.network_connection,
        parameter=param,
        value=1.23,
        time=t_utc,
    )
    
    start, end = test_plugin.get_dates_for_station(link, latest=False)
    # start should be >= the latest DB time localized to station tz
    start_utc = start.astimezone(py_tz.utc)
    assert start_utc >= t_utc
    assert end > start


@pytest.mark.django_db
def test_dates_fall_back_to_station_first_collection_date_when_no_db(test_plugin, monkeypatch):
    link = StationLinkFactory()
    
    # simulate StationLink.get_first_collection_date() returning an AWARE datetime
    naive_local = datetime(2025, 1, 2, 10, 0)  # station-local naive
    aware_local = dj_tz.make_aware(naive_local, timezone=link.timezone)
    monkeypatch.setattr(link, "get_first_collection_date", lambda: aware_local)
    
    start, end = test_plugin.get_dates_for_station(link, latest=False)
    # start should equal 10:00 local (in station tz)
    assert start.hour == 10 and start.minute == 0
    assert end > start
