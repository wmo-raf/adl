import pytest

from .factories import StationLinkFactory


@pytest.mark.django_db
def test_dates_window_latest(test_plugin):
    link = StationLinkFactory()
    start, end = test_plugin.get_dates_for_station(link, latest=True)
    assert (end - start).total_seconds() == 3600
    assert start.minute == 0 and start.second == 0
    assert end.minute == 0 and end.second == 0
