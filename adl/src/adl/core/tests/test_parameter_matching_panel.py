"""
Seam tests for the parameter matching panel on the WIS2BOX Upload edit form.

The panel is rendered through the real edit handler, and POSTs are built
from what it renders — every named input and select on the page, with the
test changing only the rows it cares about — so the markup and the save path
are held to the same contract the browser uses.
"""

from bs4 import BeautifulSoup
from django.test import RequestFactory, TestCase
from django.utils.datastructures import MultiValueDict
from wagtail.admin.panels import ObjectList, get_edit_handler

from adl.core.models import DispatchChannel, DispatchChannelParameterMapping, Wis2BoxUpload
from .factories import (
    DataParameterFactory,
    KelvinUnitFactory,
    NetworkConnectionFactory,
    UnitFactory,
    Wis2BoxUploadFactory,
)

# grouped by section, sections in the order the template first reaches them;
# precipitation_intensity joins the precipitation totals
AWS_OBSERVATION_COLUMNS = [
    "station_pressure", "msl_pressure", "geopotential_height",
    "air_temperature", "dewpoint_temperature", "relative_humidity",
    "ground_state", "snow_depth",
    "precipitation_intensity", "total_precipitation_1_hour", "total_precipitation_3_hours",
    "total_precipitation_6_hours", "total_precipitation_12_hours", "total_precipitation_24_hours",
    "wind_direction", "wind_speed",
    "maximum_wind_gust_direction_10_minutes", "maximum_wind_gust_speed_10_minutes",
    "maximum_wind_gust_direction_1_hour", "maximum_wind_gust_speed_1_hour",
    "maximum_wind_gust_direction_3_hours", "maximum_wind_gust_speed_3_hours",
]


class MatchingPanelTestCase(TestCase):
    model = Wis2BoxUpload

    def setUp(self):
        self.request = RequestFactory().get("/")
        self.connection = NetworkConnectionFactory()
        self.channel = self.make_channel()
        self.channel.network_connections.add(self.connection)
        self.edit_handler = get_edit_handler(self.model)
        self.form_class = self.edit_handler.get_form_class()

        self.kelvin = KelvinUnitFactory()
        self.mm = UnitFactory(name="Millimetre", symbol="mm")
        self.temperature = DataParameterFactory(name="Temperature")  # degC
        self.dewpoint = DataParameterFactory(name="Dew point")  # degC
        self.rainfall = DataParameterFactory(name="Rainfall", unit=self.mm)

    def make_channel(self, **kwargs):
        return Wis2BoxUploadFactory(**kwargs)

    def map(self, parameter, column, aggregation_measure="avg_value"):
        return DispatchChannelParameterMapping.objects.create(
            dispatch_channel=self.channel, parameter=parameter, channel_parameter=column,
            aggregation_measure=aggregation_measure,
        )

    def render(self, form=None):
        form = form or self.form_class(instance=self.channel)
        bound = self.edit_handler.get_bound_panel(instance=self.channel, request=self.request, form=form)
        return BeautifulSoup(bound.render_html(), "html.parser")

    def row(self, soup, column):
        return soup.select_one(f'tr[data-column="{column}"]')

    def options(self, row):
        select = row.select_one("select[data-role=parameter]")
        return {option.get_text(strip=True): option for option in select.find_all("option") if option.get("value")}

    def post_data(self, soup, parameters=None, aggregations=None):
        """Every named field the page renders, with chosen rows changed."""
        data = MultiValueDict()
        for element in soup.find_all(["input", "select", "textarea"]):
            name = element.get("name")
            if not name or element.has_attr("disabled"):
                continue
            if element.name == "select":
                values = [o.get("value", "") for o in element.find_all("option") if o.has_attr("selected")]
                data.setlist(name, values)
            elif element.get("type") in ("checkbox", "radio"):
                if element.has_attr("checked"):
                    data.appendlist(name, element.get("value", "on"))
            else:
                data.appendlist(name, element.get("value", ""))

        for column, parameter in (parameters or {}).items():
            select = self.row(soup, column).select_one("select[data-role=parameter]")
            data.setlist(select["name"], [str(parameter.pk) if parameter else ""])
        for column, measure in (aggregations or {}).items():
            select = self.row(soup, column).select_one("select[data-role=aggregation]")
            data.setlist(select["name"], [measure])
        return data

    def submit(self, parameters=None, aggregations=None):
        data = self.post_data(self.render(), parameters, aggregations)
        return self.form_class(data, instance=self.channel)

    def saved_mappings(self):
        return {
            m.channel_parameter: m
            for m in DispatchChannelParameterMapping.objects.filter(dispatch_channel=self.channel)
        }


class MatchingPanelRenderTests(MatchingPanelTestCase):
    def test_one_row_per_observation_column_grouped_by_section(self):
        soup = self.render()

        columns = [row["data-column"] for row in soup.select("tr[data-column]")]

        self.assertEqual(columns, AWS_OBSERVATION_COLUMNS)

    def test_rows_are_grouped_under_section_headings(self):
        soup = self.render()

        headings = [h.get_text(strip=True) for h in soup.select("[data-role=section-heading]")]

        self.assertEqual(headings, ["Pressure", "Temperature and humidity", "Ground and snow",
                                    "Precipitation", "Wind", "Wind gusts"])

    def test_each_row_shows_its_locked_unit(self):
        soup = self.render()

        self.assertEqual(self.row(soup, "air_temperature").select_one("[data-role=unit]").get_text(strip=True), "K")
        self.assertEqual(self.row(soup, "station_pressure").select_one("[data-role=unit]").get_text(strip=True), "Pa")

    def test_multi_hour_columns_carry_the_window_hint(self):
        soup = self.render()

        hint = self.row(soup, "total_precipitation_24_hours").select_one("[data-role=hint]")
        self.assertIn("24 hours", hint.get_text())
        self.assertIsNone(self.row(soup, "total_precipitation_1_hour").select_one("[data-role=hint]"))

    def test_dropdowns_only_offer_unit_compatible_parameters(self):
        soup = self.render()

        temperature_options = self.options(self.row(soup, "air_temperature"))
        rainfall_options = self.options(self.row(soup, "total_precipitation_1_hour"))

        self.assertIn("Temperature", temperature_options)
        self.assertNotIn("Rainfall", temperature_options)
        self.assertIn("Rainfall", rainfall_options)
        self.assertNotIn("Temperature", rainfall_options)

    def test_a_mapped_parameter_is_selected_in_its_row(self):
        self.map(self.temperature, "air_temperature")

        soup = self.render()

        option = self.options(self.row(soup, "air_temperature"))["Temperature"]
        self.assertTrue(option.has_attr("selected"))

    def test_a_parameter_used_in_another_row_is_disabled_and_says_where(self):
        self.map(self.temperature, "air_temperature")

        soup = self.render()

        dewpoint_options = {o.get_text(strip=True): o for o in
                            self.row(soup, "dewpoint_temperature").select("select[data-role=parameter] option")}
        used = dewpoint_options["Temperature (used in air_temperature)"]
        self.assertTrue(used.has_attr("disabled"))

    def test_new_rows_preselect_the_template_default_aggregation(self):
        soup = self.render()

        def selected(column):
            select = self.row(soup, column).select_one("select[data-role=aggregation]")
            return select.find("option", selected=True)["value"]

        self.assertEqual(selected("total_precipitation_1_hour"), "sum_value")
        self.assertEqual(selected("maximum_wind_gust_speed_1_hour"), "max_value")
        self.assertEqual(selected("air_temperature"), "avg_value")

    def test_an_overridden_aggregation_is_noted(self):
        self.channel.send_aggregated_data = True
        self.channel.save()
        self.map(self.rainfall, "total_precipitation_1_hour", aggregation_measure="max_value")

        soup = self.render()

        def note_shown(column):
            note = self.row(soup, column).select_one("[data-role=override-note]")
            return "parameter-matching__override--hidden" not in note.get("class", [])

        note = self.row(soup, "total_precipitation_1_hour").select_one("[data-role=override-note]")
        self.assertTrue(note_shown("total_precipitation_1_hour"))
        self.assertIn("Sum", note.get_text())
        self.assertFalse(note_shown("air_temperature"))

    def test_aggregation_is_disabled_when_the_channel_does_not_aggregate(self):
        soup = self.render()

        select = self.row(soup, "air_temperature").select_one("select[data-role=aggregation]")
        self.assertTrue(select.has_attr("disabled"))

    def test_aggregation_is_enabled_when_the_channel_aggregates(self):
        self.channel.send_aggregated_data = True
        self.channel.save()

        soup = self.render()

        select = self.row(soup, "air_temperature").select_one("select[data-role=aggregation]")
        self.assertFalse(select.has_attr("disabled"))


class MatchingPanelSaveTests(MatchingPanelTestCase):
    def test_choosing_a_parameter_creates_a_mapping_with_the_template_unit(self):
        form = self.submit(parameters={"air_temperature": self.temperature})

        self.assertTrue(form.is_valid(), form.errors.as_json() + str(form.formsets["parameter_mappings"].errors))
        form.save()

        mapping = self.saved_mappings()["air_temperature"]
        self.assertEqual(mapping.parameter, self.temperature)
        self.assertEqual(mapping.channel_unit, self.kelvin)

    def test_empty_rows_create_no_mappings(self):
        form = self.submit(parameters={"air_temperature": self.temperature})
        self.assertTrue(form.is_valid())
        form.save()

        self.assertEqual(list(self.saved_mappings()), ["air_temperature"])

    def test_a_new_row_saves_the_template_default_aggregation(self):
        form = self.submit(parameters={"total_precipitation_1_hour": self.rainfall})
        self.assertTrue(form.is_valid())
        form.save()

        self.assertEqual(self.saved_mappings()["total_precipitation_1_hour"].aggregation_measure, "sum_value")

    def test_an_overridden_aggregation_is_saved(self):
        self.channel.send_aggregated_data = True
        self.channel.save()

        form = self.submit(parameters={"total_precipitation_1_hour": self.rainfall},
                           aggregations={"total_precipitation_1_hour": "max_value"})
        self.assertTrue(form.is_valid())
        form.save()

        self.assertEqual(self.saved_mappings()["total_precipitation_1_hour"].aggregation_measure, "max_value")

    def test_saving_without_changes_keeps_existing_mappings(self):
        self.map(self.temperature, "air_temperature")

        form = self.submit()
        self.assertTrue(form.is_valid(), str(form.formsets["parameter_mappings"].errors))
        form.save()

        self.assertEqual(self.saved_mappings()["air_temperature"].parameter, self.temperature)

    def test_clearing_a_row_deletes_its_mapping(self):
        self.map(self.temperature, "air_temperature")
        self.map(self.dewpoint, "dewpoint_temperature")

        form = self.submit(parameters={"air_temperature": None})
        self.assertTrue(form.is_valid(), str(form.formsets["parameter_mappings"].errors))
        form.save()

        self.assertEqual(list(self.saved_mappings()), ["dewpoint_temperature"])

    def test_the_same_parameter_in_two_rows_is_rejected_on_the_page(self):
        form = self.submit(parameters={"air_temperature": self.temperature,
                                       "dewpoint_temperature": self.temperature})

        self.assertFalse(form.is_valid())
        soup = self.render(form)
        self.assertTrue(soup.select("[data-parameter-matching] .error-message"))

    def test_rows_are_saved_in_table_order(self):
        form = self.submit(parameters={"total_precipitation_1_hour": self.rainfall,
                                       "air_temperature": self.temperature})
        self.assertTrue(form.is_valid())
        form.save()

        ordered = list(DispatchChannelParameterMapping.objects.filter(dispatch_channel=self.channel)
                       .order_by("sort_order").values_list("channel_parameter", flat=True))
        self.assertEqual(ordered, ["air_temperature", "total_precipitation_1_hour"])

    def test_an_invalid_submission_re_renders_every_row(self):
        form = self.submit(parameters={"air_temperature": self.temperature,
                                       "dewpoint_temperature": self.temperature})
        self.assertFalse(form.is_valid())

        soup = self.render(form)

        columns = [row["data-column"] for row in soup.select("tr[data-column]")]
        self.assertEqual(columns, AWS_OBSERVATION_COLUMNS)
        selected = self.options(self.row(soup, "dewpoint_temperature"))["Temperature"]
        self.assertTrue(selected.has_attr("selected"))


class MappingThatNoLongerFitsTests(MatchingPanelTestCase):
    """
    A mapping whose parameter no longer fits its column (its unit was changed,
    or a legacy row was saved before the check) must stay visible and fail
    validation, not be dropped from the dropdown and deleted on the next save.
    """

    def setUp(self):
        super().setUp()
        self.mapping = DispatchChannelParameterMapping.objects.create(
            dispatch_channel=self.channel, parameter=self.temperature, channel_parameter="air_temperature",
        )
        # the parameter is now in mm, which cannot become Kelvin
        type(self.temperature).objects.filter(pk=self.temperature.pk).update(unit=self.mm)

    def test_its_parameter_is_still_selected_in_its_row(self):
        soup = self.render()

        options = self.row(soup, "air_temperature").select("select[data-role=parameter] option[selected]")
        self.assertEqual([o["value"] for o in options], [str(self.temperature.pk)])

    def test_saving_unchanged_is_refused_and_keeps_the_mapping(self):
        form = self.submit()

        self.assertFalse(form.is_valid())
        self.assertTrue(DispatchChannelParameterMapping.objects.filter(pk=self.mapping.pk).exists())
        soup = self.render(form)
        self.assertTrue(self.row(soup, "air_temperature").select(".error-message"))


class DimensionlessColumnTests(MatchingPanelTestCase):
    def test_a_column_without_a_unit_only_offers_dimensionless_parameters(self):
        code = DataParameterFactory(name="Ground state code", unit=UnitFactory(name="Code", symbol="dimensionless"))

        soup = self.render()

        options = self.options(self.row(soup, "ground_state"))
        self.assertIn(code.name, options)
        self.assertNotIn("Temperature", options)
        self.assertNotIn("Rainfall", options)


class UnrecognisedMappingVisibilityTests(MatchingPanelTestCase):
    """
    A legacy mapping that matches no observation column fails validation, so
    it must be on the page with its error — not silently carried in hidden
    fields where the form could refuse to save for a reason nobody can see.
    """

    def test_an_unrecognised_mapping_is_shown(self):
        self.map(self.temperature, "air_temp")

        soup = self.render()

        row = soup.select_one('tr[data-unrecognised="air_temp"]')
        self.assertIsNotNone(row)
        self.assertIn("Temperature", row.get_text())

    def test_removing_an_unrecognised_mapping_lets_the_channel_save(self):
        legacy = self.map(self.temperature, "air_temp")
        soup = self.render()
        data = self.post_data(soup)
        delete = soup.select_one('tr[data-unrecognised="air_temp"] input[data-role=delete]')
        data.setlist(delete["name"], ["on"])

        form = self.form_class(data, instance=self.channel)
        self.assertTrue(form.is_valid(), str(form.formsets["parameter_mappings"].errors))
        form.save()

        self.assertFalse(DispatchChannelParameterMapping.objects.filter(pk=legacy.pk).exists())


class PlainChannelPanelTests(TestCase):
    """Channels without a mapping spec keep Wagtail's inline panel."""

    def test_a_channel_without_a_spec_renders_the_inline_panel(self):
        # panels as the S3 and FTP plugin channels compose them
        edit_handler = ObjectList(
            DispatchChannel.base_panels + DispatchChannel.parameter_panels
        ).bind_to_model(DispatchChannel)
        channel = DispatchChannel.objects.create(name="Plain")
        form = edit_handler.get_form_class()(instance=channel)

        html = edit_handler.get_bound_panel(instance=channel, request=RequestFactory().get("/"),
                                            form=form).render_html()

        self.assertIn("parameter_mappings-__prefix__", html)
        self.assertNotIn("data-parameter-matching", html)
