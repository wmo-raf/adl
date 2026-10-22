"""
Seam tests for the parameter matching panel on the WIS2BOX Upload edit form.

The panel is rendered through the real edit handler, and POSTs are built
from what it renders — every named input and select on the page, with the
test changing only the rows it cares about — so the markup and the save path
are held to the same contract the browser uses.
"""

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
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


class UnrecognisedMappingCleanupTests(MatchingPanelTestCase):
    """
    The form refuses to save while a mapping fills no column, and offers
    reassigning it to a column that fits, or removing it.
    """

    def unrecognised_row(self, soup, name):
        return soup.select_one(f'tr[data-unrecognised="{name}"]')

    def reassign(self, soup, data, name, column):
        select = self.unrecognised_row(soup, name).select_one("select[data-role=reassign]")
        data.setlist(select["name"], [column])

    def test_a_form_with_an_unrecognised_mapping_is_refused_with_a_message(self):
        self.map(self.temperature, "air_temp")

        form = self.submit()

        self.assertFalse(form.is_valid())
        errors = form.formsets["parameter_mappings"].non_form_errors()
        self.assertIn("Remove or reassign the mappings listed under the table", " ".join(errors))
        self.assertIn("Remove or reassign", self.render(form).select_one(".help-critical").get_text())

    def test_a_station_column_name_is_unrecognised_too(self):
        self.map(self.temperature, "latitude")

        self.assertIsNotNone(self.unrecognised_row(self.render(), "latitude"))
        self.assertFalse(self.submit().is_valid())

    def test_reassigning_saves_a_normal_mapping_with_the_template_unit(self):
        legacy = self.map(self.temperature, "air_temp")
        soup = self.render()
        data = self.post_data(soup)
        self.reassign(soup, data, "air_temp", "air_temperature")

        form = self.form_class(data, instance=self.channel)
        self.assertTrue(form.is_valid(), str(form.formsets["parameter_mappings"].errors))
        form.save()

        mapping = DispatchChannelParameterMapping.objects.get(pk=legacy.pk)
        self.assertEqual(mapping.channel_parameter, "air_temperature")
        self.assertEqual(mapping.channel_unit, self.kelvin)
        row = self.row(self.render(), "air_temperature")
        self.assertEqual(row.select_one("select[data-role=parameter] option[selected]")["value"],
                         str(self.temperature.pk))
        self.assertIsNone(self.unrecognised_row(self.render(), "air_temp"))

    def test_removing_still_deletes_the_row(self):
        legacy = self.map(self.temperature, "air_temp")
        soup = self.render()
        data = self.post_data(soup)
        data.setlist(self.unrecognised_row(soup, "air_temp").select_one("input[data-role=delete]")["name"], ["on"])

        form = self.form_class(data, instance=self.channel)
        self.assertTrue(form.is_valid())
        form.save()

        self.assertFalse(DispatchChannelParameterMapping.objects.filter(pk=legacy.pk).exists())

    def test_only_free_columns_that_fit_are_offered(self):
        self.map(self.dewpoint, "air_temperature")
        self.map(self.temperature, "air_temp")

        select = self.unrecognised_row(self.render(), "air_temp").select_one("select[data-role=reassign]")

        offered = [option["value"] for option in select.find_all("option")]
        self.assertEqual(offered[0], "air_temp")
        self.assertIn("dewpoint_temperature", offered)
        self.assertNotIn("air_temperature", offered)  # already holds a mapping
        self.assertNotIn("wind_speed", offered)  # Kelvin does not convert to m/s

    def test_reassigning_to_a_column_that_already_has_a_mapping_is_refused(self):
        self.map(self.dewpoint, "air_temperature")
        self.map(self.temperature, "air_temp")
        soup = self.render()
        data = self.post_data(soup)
        self.reassign(soup, data, "air_temp", "air_temperature")

        form = self.form_class(data, instance=self.channel)

        self.assertFalse(form.is_valid())
        self.assertIsNotNone(self.unrecognised_row(self.render(form), "air_temperature"))

    def test_reassigning_to_a_column_the_parameter_does_not_fit_is_refused(self):
        self.map(self.temperature, "air_temp")
        soup = self.render()
        data = self.post_data(soup)
        self.reassign(soup, data, "air_temp", "wind_speed")

        self.assertFalse(self.form_class(data, instance=self.channel).is_valid())

    def test_a_reassignment_survives_a_re_render_after_another_error(self):
        self.map(self.temperature, "air_temp")
        soup = self.render()
        data = self.post_data(soup)
        self.reassign(soup, data, "air_temp", "air_temperature")
        # the same parameter in a second row is rejected on the page
        data.setlist(self.row(soup, "dewpoint_temperature").select_one("select[data-role=parameter]")["name"],
                     [str(self.temperature.pk)])

        form = self.form_class(data, instance=self.channel)

        self.assertFalse(form.is_valid())
        row = self.row(self.render(form), "air_temperature")
        self.assertEqual(row.select_one("select[data-role=parameter] option[selected]")["value"],
                         str(self.temperature.pk))

    def test_a_duplicate_for_a_column_can_be_reassigned_to_a_free_one(self):
        self.map(self.temperature, "air_temperature")
        self.map(self.dewpoint, "air_temperature")
        soup = self.render()
        [duplicate] = soup.select("tr[data-unrecognised]")
        data = self.post_data(soup)
        select = duplicate.select_one("select[data-role=reassign]")
        data.setlist(select["name"], ["dewpoint_temperature"])

        form = self.form_class(data, instance=self.channel)
        self.assertTrue(form.is_valid(), str(form.formsets["parameter_mappings"].errors))
        form.save()

        self.assertEqual(set(self.saved_mappings()), {"air_temperature", "dewpoint_temperature"})


class NewChannelPanelTests(MatchingPanelTestCase):
    def test_the_create_form_renders_without_unrecognised_mappings(self):
        new_channel = Wis2BoxUpload()
        form = self.form_class(instance=new_channel)
        bound = self.edit_handler.get_bound_panel(instance=new_channel, request=self.request, form=form)
        soup = BeautifulSoup(bound.render_html(), "html.parser")

        self.assertEqual(len(soup.select("tr[data-column]")), len(AWS_OBSERVATION_COLUMNS))
        self.assertIsNone(soup.select_one("tr[data-unrecognised]"))


class UnmatchedMappingsFlagTests(MatchingPanelTestCase):
    """Channels with unrecognised mappings are flagged on the channel listing."""

    def setUp(self):
        super().setUp()
        user = get_user_model().objects.create_superuser(username="admin", email="a@example.com", password="x")
        self.client.force_login(user)

    def listing(self):
        response = self.client.get(reverse("dispatch_channels_list"))
        self.assertEqual(response.status_code, 200)
        return BeautifulSoup(response.content, "html.parser")

    def test_a_channel_with_unrecognised_mappings_is_flagged_with_their_count(self):
        self.map(self.temperature, "air_temp")
        self.map(self.dewpoint, "latitude")
        self.map(self.rainfall, "total_precipitation_1_hour")

        badge = self.listing().select_one(".status-badge--warning")

        self.assertIn("2 unmatched mappings", badge.get_text())
        self.assertEqual(badge.find_parent("a")["href"], self.channel.edit_url)

    def test_a_channel_without_unrecognised_mappings_is_not_flagged(self):
        self.map(self.temperature, "air_temperature")

        self.assertIsNone(self.listing().select_one(".status-badge--warning"))

    def test_saved_mappings_are_counted_without_the_form(self):
        self.map(self.temperature, "air_temp")
        self.map(self.dewpoint, "air_temperature")
        self.map(self.rainfall, "air_temperature")

        reasons = [reason for _mapping, reason in self.channel.get_unmatched_parameter_mappings()]

        self.assertEqual(len(reasons), 2)

    def test_a_channel_without_a_spec_has_no_unmatched_mappings(self):
        channel = DispatchChannel.objects.create(name="Plain")
        DispatchChannelParameterMapping.objects.create(
            dispatch_channel=channel, parameter=self.temperature, channel_parameter="anything",
        )

        self.assertEqual(channel.get_unmatched_parameter_mappings(), [])


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
