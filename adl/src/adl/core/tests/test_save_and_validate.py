from datetime import datetime, timedelta, timezone as py_tz

from django.test import TestCase

from adl.core.models import ObservationRecord
from .factories import (
    StationLinkFactory,
    DataParameterFactory,
    KelvinUnitFactory,
    CelsiusUnitFactory,
)
from .helpers import make_test_plugin, make_mapping


class SaveAndValidateTests(TestCase):
    def setUp(self):
        self.plugin = make_test_plugin()
        self.link = StationLinkFactory()
        unit_c = CelsiusUnitFactory()
        self.unit_k = KelvinUnitFactory()
        self.param_temp = DataParameterFactory(name="air_temperature", unit=unit_c)

        # Map vendor field `temp_K` (Kelvin) -> ADL param (degC)
        mapping = make_mapping(self.param_temp, self.unit_k)
        self.link.get_variable_mappings = lambda: [mapping]

        # Accepted time window used across tests
        self.window_start = datetime(2025, 1, 1, 0, 0, tzinfo=py_tz.utc)
        self.window_end = datetime(2025, 1, 2, 0, 0, tzinfo=py_tz.utc)

    def test_happy_path_kelvin_to_celsius(self):
        # 293.15 K ≈ 20 °C
        ts = datetime(2025, 1, 1, 12, 0, tzinfo=py_tz.utc)
        self.plugin.records = [{"observation_time": ts, "temp_K": 293.15}]

        total_saved, earliest, latest = self.plugin.save_records(
            self.link, self.plugin.records, self.window_start, self.window_end
        )
        self.assertEqual(total_saved, 1)
        self.assertIsNotNone(earliest)
        self.assertIsNotNone(latest)

        rec = ObservationRecord.objects.get()
        self.assertAlmostEqual(rec.value, 20.0, delta=0.01)
        # Django stores UTC internally; utc_time should equal original instant
        self.assertEqual(rec.utc_time.replace(tzinfo=py_tz.utc), ts)

    def test_reject_non_numeric_value(self):
        ts = datetime(2025, 1, 1, 12, 0, tzinfo=py_tz.utc)
        self.plugin.records = [{"observation_time": ts, "temp_K": "oops"}]

        total_saved, earliest, latest = self.plugin.save_records(
            self.link, self.plugin.records, self.window_start, self.window_end
        )
        self.assertEqual(total_saved, 0)
        self.assertEqual(ObservationRecord.objects.count(), 0)

    def test_missing_observation_time_is_skipped(self):
        self.plugin.records = [{"temp_K": 300.0}]  # no observation_time

        total_saved, earliest, latest = self.plugin.save_records(
            self.link, self.plugin.records, self.window_start, self.window_end
        )
        self.assertEqual(total_saved, 0)
        self.assertEqual(ObservationRecord.objects.count(), 0)

    def test_out_of_window_record_is_dropped(self):
        # A valid record whose timestamp falls before the accepted window
        ts = self.window_start - timedelta(hours=2)
        self.plugin.records = [{"observation_time": ts, "temp_K": 293.15}]

        total_saved, earliest, latest = self.plugin.save_records(
            self.link, self.plugin.records, self.window_start, self.window_end
        )
        self.assertEqual(total_saved, 0)
        self.assertEqual(ObservationRecord.objects.count(), 0)

    def test_upsert_on_conflict(self):
        ts = datetime(2025, 1, 1, 12, 0, tzinfo=py_tz.utc)

        # Insert
        self.plugin.records = [{"observation_time": ts, "temp_K": 293.15}]  # ~20C
        self.plugin.save_records(self.link, self.plugin.records, self.window_start, self.window_end)

        # Update same natural key => 294.15K (~21C)
        self.plugin.records = [{"observation_time": ts, "temp_K": 294.15}]
        self.plugin.save_records(self.link, self.plugin.records, self.window_start, self.window_end)

        self.assertEqual(ObservationRecord.objects.count(), 1)
        rec = ObservationRecord.objects.get()
        self.assertAlmostEqual(rec.value, 21.0, delta=0.01)
