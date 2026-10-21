"""
Seam tests for the WIS2BOX Upload channel edit form's parameter mappings.

The form is the one the admin builds from the channel's panels, bound to POST
data as the edit view would receive it; assertions are on whether it
validates, which fields carry errors, and what it saves.
"""

from django.test import TestCase
from wagtail.admin.panels import get_edit_handler

from adl.core.models import DispatchChannelParameterMapping, Unit, Wis2BoxUpload
from .factories import (
    DataParameterFactory,
    NetworkConnectionFactory,
    UnitFactory,
    Wis2BoxUploadFactory,
)

PREFIX = "parameter_mappings"


class Wis2BoxMappingFormTestCase(TestCase):
    def setUp(self):
        self.connection = NetworkConnectionFactory()
        self.channel = Wis2BoxUploadFactory()
        self.form_class = get_edit_handler(Wis2BoxUpload).get_form_class()

    def unit(self, name, symbol):
        return UnitFactory(name=name, symbol=symbol)

    def mapping(self, parameter, channel_parameter, channel_unit=None):
        return {"parameter": parameter, "channel_parameter": channel_parameter, "channel_unit": channel_unit}

    def bind(self, *mappings, instance=None):
        data = {
            "name": self.channel.name,
            "network_connections": [self.connection.pk],
            "enabled": "on",
            "data_check_interval": 10,
            "dispatch_timeout_seconds": 300,
            "max_records_per_dispatch": 500,
            "aggregation_period": "hourly",
            "sort_order": 0,
            "storage_endpoint": self.channel.storage_endpoint,
            "storage_username": self.channel.storage_username,
            "storage_password": self.channel.storage_password,
            "dataset_id": self.channel.dataset_id,
            "template": "aws",
            f"{PREFIX}-TOTAL_FORMS": len(mappings),
            f"{PREFIX}-INITIAL_FORMS": 0,
            f"{PREFIX}-MIN_NUM_FORMS": 0,
            f"{PREFIX}-MAX_NUM_FORMS": 1000,
        }
        for i, m in enumerate(mappings):
            data.update({
                f"{PREFIX}-{i}-parameter": m["parameter"].pk,
                f"{PREFIX}-{i}-channel_parameter": m["channel_parameter"],
                f"{PREFIX}-{i}-channel_unit": m["channel_unit"].pk if m["channel_unit"] else "",
                f"{PREFIX}-{i}-aggregation_measure": "avg_value",
                f"{PREFIX}-{i}-ORDER": i,
            })
        return self.form_class(data, instance=self.channel if instance is None else instance)

    def mapping_errors(self, form, index=0):
        return form.formsets[PREFIX].forms[index].errors

    def save(self, *mappings):
        form = self.bind(*mappings)
        self.assertTrue(form.is_valid(), form.formsets[PREFIX].errors)
        form.save()
        return DispatchChannelParameterMapping.objects.filter(dispatch_channel=self.channel)


class ObservationColumnOnlyTests(Wis2BoxMappingFormTestCase):
    def test_a_station_column_cannot_be_mapped(self):
        form = self.bind(self.mapping(DataParameterFactory(), "latitude"))

        self.assertFalse(form.is_valid())
        self.assertIn("channel_parameter", self.mapping_errors(form))

    def test_a_timestamp_column_cannot_be_mapped(self):
        form = self.bind(self.mapping(DataParameterFactory(), "year"))

        self.assertFalse(form.is_valid())
        self.assertIn("channel_parameter", self.mapping_errors(form))

    def test_a_name_that_is_not_in_the_template_is_rejected(self):
        form = self.bind(self.mapping(DataParameterFactory(), "air_temp"))

        self.assertFalse(form.is_valid())
        self.assertIn("channel_parameter", self.mapping_errors(form))

    def test_a_blank_column_name_only_says_it_is_required(self):
        form = self.bind(self.mapping(DataParameterFactory(), ""))

        self.assertFalse(form.is_valid())
        self.assertEqual(len(self.mapping_errors(form)["channel_parameter"]), 1)

    def test_a_new_channel_is_validated_too(self):
        # the create form's channel has no id yet
        form = self.bind(self.mapping(DataParameterFactory(), "latitude"), instance=Wis2BoxUpload())

        self.assertFalse(form.is_valid())
        self.assertIn("channel_parameter", self.mapping_errors(form))

    def test_an_observation_column_is_accepted(self):
        # DataParameterFactory defaults to degC
        [saved] = self.save(self.mapping(DataParameterFactory(), "air_temperature"))

        self.assertEqual(saved.channel_parameter, "air_temperature")


class UnitCompatibilityTests(Wis2BoxMappingFormTestCase):
    def test_a_parameter_whose_unit_cannot_convert_to_the_column_is_rejected(self):
        rainfall = DataParameterFactory(unit=self.unit("Millimetre", "mm"))

        form = self.bind(self.mapping(rainfall, "wind_speed"))

        self.assertFalse(form.is_valid())
        self.assertIn("parameter", self.mapping_errors(form))

    def test_rainfall_in_mm_is_accepted_for_a_kg_per_square_metre_column(self):
        rainfall = DataParameterFactory(unit=self.unit("Millimetre", "mm"))

        [saved] = self.save(self.mapping(rainfall, "total_precipitation_1_hour"))

        self.assertEqual(saved.parameter, rainfall)


class LockedChannelUnitTests(Wis2BoxMappingFormTestCase):
    def test_the_saved_channel_unit_is_the_template_unit_whatever_was_submitted(self):
        hpa = self.unit("Hectopascal", "hPa")
        pascal = self.unit("Pascal", "Pa")
        pressure = DataParameterFactory(unit=hpa)

        [saved] = self.save(self.mapping(pressure, "station_pressure", channel_unit=hpa))

        self.assertEqual(saved.channel_unit, pascal)

    def test_a_blank_channel_unit_is_saved_as_the_template_unit(self):
        kelvin = self.unit("Kelvin", "K")

        [saved] = self.save(self.mapping(DataParameterFactory(), "air_temperature"))

        self.assertEqual(saved.channel_unit, kelvin)

    def test_a_missing_template_unit_is_created(self):
        self.assertFalse(Unit.objects.filter(symbol="m/s").exists())
        wind = DataParameterFactory(unit=self.unit("Kilometres per hour", "km/h"))

        [saved] = self.save(self.mapping(wind, "wind_speed"))

        self.assertEqual(saved.channel_unit.symbol, "m/s")

    def test_an_existing_unit_spelled_differently_is_reused(self):
        # "kg m-2" is the same unit as the template's "kg/m^2"
        kg_per_m2 = self.unit("Kilograms per square metre", "kg m-2")
        rainfall = DataParameterFactory(unit=self.unit("Millimetre", "mm"))
        units_before = Unit.objects.count()

        [saved] = self.save(self.mapping(rainfall, "total_precipitation_1_hour"))

        self.assertEqual(saved.channel_unit, kg_per_m2)
        self.assertEqual(Unit.objects.count(), units_before)

    def test_a_column_without_a_unit_saves_no_channel_unit(self):
        code = DataParameterFactory(unit=self.unit("Code", "dimensionless"))

        [saved] = self.save(self.mapping(code, "ground_state", channel_unit=code.unit))

        self.assertIsNone(saved.channel_unit)
