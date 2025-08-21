import pytest

from adl.core.registries import Plugin
from adl.core.tests.factories import NetworkConnectionFactory


@pytest.fixture
def conn_id(db):
    return NetworkConnectionFactory().id


@pytest.fixture
def test_plugin():
    class _TestPlugin(Plugin):
        type = "test_plugin"
        label = "Test Plugin"
        records = []
        
        def get_station_data(self, station_link, start_date=None, end_date=None):
            # In tests we inject `self.records` directly
            return list(self.records)
    
    return _TestPlugin()
