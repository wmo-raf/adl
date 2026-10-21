"""
Seam tests for switching a WIS2BOX Upload channel's csv2bufr template on the
channel edit form, using a test-only second template next to AWS.

POSTs are built from the rendered page, changing only the template.
"""

import json

from adl.core.dispatchers.csv2bufr_templates import (
    Csv2BufrTemplate,
    csv2bufr_template_registry,
    observation_column,
    station_column,
    TEMPERATURE_HUMIDITY,
    WIND,
)
from adl.core.models import DispatchChannelParameterMapping
from .factories import DataParameterFactory, UnitFactory
from .test_parameter_matching_panel import MatchingPanelTestCase


class MiniTemplate(Csv2BufrTemplate):
    """Shares air_temperature with AWS, in a different unit; has a column of its own; lacks the rest."""

    type = "mini"
    label = "Mini"
    columns = (
        station_column("latitude", "decimal", "degree"),
        observation_column("air_temperature", "decimal", "degC", TEMPERATURE_HUMIDITY),
        observation_column("mini_wind", "decimal", "m/s", WIND),
    )


class TemplateSwitchingTestCase(MatchingPanelTestCase):
    def setUp(self):
        super().setUp()
        template = MiniTemplate()
        csv2bufr_template_registry.register(template)
        self.addCleanup(csv2bufr_template_registry.unregister, "mini")
        self.pressure = self.make_parameter("Pressure", "Pa")

    def make_parameter(self, name, symbol):
        return DataParameterFactory(name=name, unit=UnitFactory(name=name, symbol=symbol))

    def switch(self, template="mini"):
        soup = self.render()
        data = self.post_data(soup)
        data.setlist("template", [template])
        return self.form_class(data, instance=self.channel)

    def save_switch(self, template="mini"):
        form = self.switch(template)
        self.assertTrue(form.is_valid(), str(form.formsets["parameter_mappings"].errors)
                        + str(form.formsets["parameter_mappings"].non_form_errors()) + str(form.errors))
        form.save()
        return {m.channel_parameter: m for m in DispatchChannelParameterMapping.objects.filter(
            dispatch_channel=self.channel)}


class SwitchingSaveTests(TemplateSwitchingTestCase):
    def test_mappings_whose_column_exists_in_both_templates_are_kept(self):
        self.map(self.temperature, "air_temperature")

        saved = self.save_switch()

        self.assertEqual(set(saved), {"air_temperature"})
        self.assertEqual(saved["air_temperature"].parameter, self.temperature)

    def test_mappings_without_a_column_in_the_new_template_are_dropped(self):
        self.map(self.temperature, "air_temperature")
        self.map(self.pressure, "msl_pressure")

        saved = self.save_switch()

        self.assertEqual(set(saved), {"air_temperature"})

    def test_a_kept_mapping_gets_the_new_templates_unit(self):
        mapping = self.map(self.temperature, "air_temperature")
        mapping.save()  # as saved from the form: the AWS unit, Kelvin
        self.assertEqual(DispatchChannelParameterMapping.objects.get(pk=mapping.pk).channel_unit.symbol, "K")

        saved = self.save_switch()

        self.assertEqual(saved["air_temperature"].channel_unit.symbol, "degC")

    def test_the_channel_template_is_saved(self):
        self.map(self.temperature, "air_temperature")

        self.save_switch()

        self.channel.refresh_from_db()
        self.assertEqual(self.channel.template, "mini")

    def test_saving_without_switching_changes_nothing(self):
        self.map(self.temperature, "air_temperature")
        self.map(self.pressure, "msl_pressure")

        form = self.submit()

        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual(set(self.saved_mappings()), {"air_temperature", "msl_pressure"})

    def test_a_mapping_that_was_never_a_column_still_blocks_the_save(self):
        self.map(self.temperature, "air_temp")

        form = self.switch()

        self.assertFalse(form.is_valid())

    def test_a_kept_mapping_whose_parameter_does_not_fit_the_new_unit_is_refused(self):
        # millimetres do not convert to degrees Celsius
        self.map(self.rainfall, "air_temperature")

        self.assertFalse(self.switch().is_valid())


class SwitchingPageTests(TemplateSwitchingTestCase):
    def test_every_registered_template_is_embedded_in_the_page(self):
        soup = self.render()

        data = json.loads(soup.select_one("script#parameter-matching-specs").string)

        self.assertEqual(set(data["templates"]), {"aws", "mini"})
        mini = [column["name"] for column in data["templates"]["mini"]["columns"]]
        self.assertEqual(mini, ["air_temperature", "mini_wind"])

    def test_the_embedded_spec_lists_the_parameters_that_fit_each_column(self):
        soup = self.render()

        data = json.loads(soup.select_one("script#parameter-matching-specs").string)

        fits = data["fits"]["mini"]["air_temperature"]
        self.assertIn(self.temperature.pk, fits)
        self.assertNotIn(self.rainfall.pk, fits)

    def test_a_posted_switch_lists_the_mappings_it_will_drop(self):
        self.map(self.temperature, "air_temperature")
        self.map(self.pressure, "msl_pressure")
        form = self.switch()
        form.is_valid()

        soup = self.render(form)

        dropped = [item.get_text(strip=True) for item in soup.select("[data-role=dropped] li")]
        self.assertEqual(dropped, ["msl_pressure"])
        self.assertIsNone(soup.select_one("tr[data-unrecognised]"))
        self.assertEqual([row["data-column"] for row in soup.select("table.parameter-matching__table tr[data-column]")],
                         ["air_temperature", "mini_wind"])

    def test_a_saved_channel_lists_nothing_to_drop(self):
        self.map(self.temperature, "air_temperature")

        soup = self.render()

        self.assertEqual(soup.select("[data-role=dropped] li"), [])


class SwitchingEdgeCaseTests(TemplateSwitchingTestCase):
    def test_a_parameter_freed_by_a_dropped_mapping_can_be_chosen_for_a_new_column(self):
        speed = self.make_parameter("Speed", "m/s")
        self.map(speed, "wind_speed")
        soup = self.render()
        data = self.post_data(soup)
        data.setlist("template", ["mini"])
        index = int(data["parameter_mappings-TOTAL_FORMS"])
        data["parameter_mappings-TOTAL_FORMS"] = str(index + 1)
        prefix = f"parameter_mappings-{index}-"
        for field, value in {"channel_parameter": "mini_wind", "parameter": str(speed.pk),
                             "aggregation_measure": "avg_value", "ORDER": "2", "id": "", "DELETE": ""}.items():
            data[prefix + field] = value

        form = self.form_class(data, instance=self.channel)
        self.assertTrue(form.is_valid(), str(form.formsets["parameter_mappings"].errors))
        form.save()

        saved = {m.channel_parameter: m.parameter for m in DispatchChannelParameterMapping.objects.filter(
            dispatch_channel=self.channel)}
        self.assertEqual(saved, {"mini_wind": speed})

    def test_a_columns_fit_follows_its_own_templates_unit(self):
        # air_temperature is Kelvin in AWS and degC in Mini; a Kelvin parameter fits both, a
        # Fahrenheit one fits both too, whichever template is worked out first
        data = json.loads(self.render().select_one("script#parameter-matching-specs").string)

        self.assertIn(self.temperature.pk, data["fits"]["aws"]["air_temperature"])
        self.assertIn(self.temperature.pk, data["fits"]["mini"]["air_temperature"])

    def test_columns_are_embedded_grouped_by_section_as_the_server_renders_them(self):
        data = json.loads(self.render().select_one("script#parameter-matching-specs").string)

        sections = [column["section"] for column in data["templates"]["aws"]["columns"]]
        collapsed = [s for i, s in enumerate(sections) if i == 0 or s != sections[i - 1]]
        self.assertEqual(len(collapsed), len(set(collapsed)))

    def test_a_page_with_only_one_template_embeds_no_specs(self):
        csv2bufr_template_registry.unregister("mini")
        # cleanups run last-in first: put Mini back for setUp's own cleanup to remove
        self.addCleanup(csv2bufr_template_registry.register, MiniTemplate())

        self.assertIsNone(self.render().select_one("script#parameter-matching-specs"))
