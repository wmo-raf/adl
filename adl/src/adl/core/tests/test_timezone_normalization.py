from datetime import datetime, timezone as py_tz

from django.test import TestCase

from adl.core.models import ObservationRecord
from .factories import StationLinkFactory, DataParameterFactory, KelvinUnitFactory, CelsiusUnitFactory
from .helpers import make_test_plugin, make_mapping


class TimezoneNormalizationTests(TestCase):
    def test_naive_local_interpreted_as_station_tz(self):
        """
        StationLink uses connection tz Africa/Nairobi (UTC+3).
        Naive 12:00 local -> stored instant corresponds to 09:00 UTC.
        """
        plugin = make_test_plugin()
        link = StationLinkFactory()  # tz Africa/Nairobi via connection
        unit_c = CelsiusUnitFactory()
        unit_k = KelvinUnitFactory()
        param_temp = DataParameterFactory(name="air_temperature", unit=unit_c)

        mapping = make_mapping(param_temp, unit_k)
        link.get_variable_mappings = lambda: [mapping]

        naive_local = datetime(2025, 1, 1, 12, 0)  # naive, assumed station-local
        plugin.records = [{"observation_time": naive_local, "temp_K": 300.0}]
        window_start = datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc)
        window_end = datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc)
        plugin.save_records(link, plugin.records, window_start, window_end)

        rec = ObservationRecord.objects.get()
        # Should be 09:00 UTC after interpreting naive as Africa/Nairobi time
        self.assertEqual((rec.utc_time.hour, rec.utc_time.minute), (9, 0))
