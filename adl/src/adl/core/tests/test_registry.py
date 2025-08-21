import pytest

from adl.core.exceptions import InstanceTypeAlreadyRegistered
from adl.core.registries import plugin_registry, Plugin


class _TempPlugin(Plugin):
    type = "temp_plugin_type_for_tests"
    label = "Temp Plugin"
    
    def get_station_data(self, station_link, start_date=None, end_date=None):
        return []


def test_plugin_registry_register_and_get():
    # Register
    plugin_registry.register(_TempPlugin())
    # Get back
    got = plugin_registry.get("temp_plugin_type_for_tests")
    assert isinstance(got, _TempPlugin)
    assert got.label == "Temp Plugin"
    
    # Registering the same type again should raise
    with pytest.raises(InstanceTypeAlreadyRegistered):
        plugin_registry.register(_TempPlugin())
