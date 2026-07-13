from types import SimpleNamespace

from adl.core.registries import Plugin


def make_test_plugin():
    """Fresh stub plugin per test. Records are injected via `plugin.records`."""

    class _TestPlugin(Plugin):
        type = "test_plugin"
        label = "Test Plugin"
        records = []

        def get_station_data(self, station_link, start_date=None, end_date=None):
            # In tests we inject `self.records` directly
            return list(self.records)

    return _TestPlugin()


def make_mapping(param, unit, source_name="temp_K"):
    """Duck-typed variable mapping, as consumed by the core validation pipeline."""
    return SimpleNamespace(
        id=1,
        adl_parameter=param,
        source_parameter_name=source_name,
        source_parameter_unit=unit,
    )
