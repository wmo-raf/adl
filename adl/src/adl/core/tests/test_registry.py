from django.test import SimpleTestCase

from adl.core.exceptions import InstanceTypeAlreadyRegistered
from adl.core.registries import plugin_registry, Plugin


class _TempPlugin(Plugin):
    type = "temp_plugin_type_for_tests"
    label = "Temp Plugin"

    def get_station_data(self, station_link, start_date=None, end_date=None):
        return []


class PluginRegistryTests(SimpleTestCase):
    def test_plugin_registry_register_and_get(self):
        # Register
        plugin_registry.register(_TempPlugin())
        # Get back
        got = plugin_registry.get("temp_plugin_type_for_tests")
        self.assertIsInstance(got, _TempPlugin)
        self.assertEqual(got.label, "Temp Plugin")

        # Registering the same type again should raise
        with self.assertRaises(InstanceTypeAlreadyRegistered):
            plugin_registry.register(_TempPlugin())
