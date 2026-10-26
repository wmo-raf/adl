"""The Data availability page: URL-param parsing, rendering, and access."""

from datetime import date, datetime, timezone as py_tz
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection as db_connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from adl.core.models import StationLink
from adl.core.tests.factories import (
    DataParameterFactory,
    NetworkConnectionFactory,
    ObservationRecordFactory,
    StationFactory,
    StationLinkFactory,
)
from adl.core.tests.helpers import make_mapping


class DataAvailabilityViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="monitor", email="monitor@example.com", password="pw"
        )
        self.client.force_login(user)
        self.url = reverse("data_availability")
        self.connection = NetworkConnectionFactory(stations_timezone="Africa/Nairobi")
        self.link = StationLinkFactory(network_connection=self.connection)

    def get(self, **params):
        return self.client.get(self.url, params)

    def test_without_params_shows_selectors_and_a_prompt(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("availability", response.context)
        self.assertContains(response, "Choose a connection")
        self.assertContains(response, self.connection.name)
        self.assertNotIn("grid", response.context)

    def test_connection_alone_lists_only_its_station_links(self):
        other = StationLinkFactory()

        response = self.get(connection=self.connection.id)

        self.assertEqual(response.context["station_links"], [self.link])
        self.assertNotIn(other, response.context["station_links"])
        self.assertIn("grid", response.context)

    def test_station_link_alone_derives_the_connection(self):
        response = self.get(station_link=self.link.id, month="2026-03")

        self.assertEqual(response.context["connection_id"], self.connection.id)
        self.assertEqual(response.context["station_links"], [self.link])

    def test_station_link_wins_over_a_mismatched_connection(self):
        other = NetworkConnectionFactory()

        response = self.get(connection=other.id, station_link=self.link.id)

        self.assertEqual(response.context["connection_id"], self.connection.id)

    def test_renders_month_cells_with_counts_and_names_the_timezone(self):
        ObservationRecordFactory(
            station=self.link.station,
            connection=self.connection,
            time=datetime(2026, 3, 5, 6, 30, tzinfo=py_tz.utc),
        )

        response = self.get(station_link=self.link.id, month="2026-03")

        self.assertContains(response, "March 2026")
        self.assertContains(response, "Africa/Nairobi")
        self.assertContains(response, "availability-cell--complete")
        self.assertContains(response, "availability-cell--empty")
        self.assertContains(response, "1/15")  # floor is 09:00 local on 5 Mar

    def test_prev_and_next_links_move_the_month_param(self):
        response = self.get(station_link=self.link.id, month="2026-01")

        self.assertEqual(
            response.context["prev_url"], f"{self.url}?station_link={self.link.id}&month=2025-12"
        )
        self.assertEqual(
            response.context["next_url"], f"{self.url}?station_link={self.link.id}&month=2026-02"
        )

    def test_default_month_is_the_current_local_month(self):
        response = self.get(station_link=self.link.id)

        availability = response.context["availability"]
        from django.utils import timezone

        now = timezone.localtime(timezone.now(), availability_tz(self.link))
        self.assertEqual((availability.year, availability.month), (now.year, now.month))

    def test_invalid_params_are_ignored(self):
        for params in (
            {"station_link": "abc"},
            {"station_link": "-4"},
            {"station_link": "999999"},
            {"connection": "x"},
            {"connection": "999999"},
            {"station_link": self.link.id, "month": "2026-13"},
            {"station_link": self.link.id, "month": "garbage"},
            {"station_link": self.link.id, "month": "0000-01"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 200)

    def test_unknown_connection_shows_the_connection_prompt(self):
        response = self.get(connection=999999)
        self.assertIsNone(response.context["connection_id"])
        self.assertContains(response, "Choose a connection")

    def test_unknown_station_link_shows_the_prompt(self):
        response = self.get(station_link=999999)
        self.assertNotIn("availability", response.context)

    def test_invalid_month_falls_back_to_the_current_month(self):
        response = self.get(station_link=self.link.id, month="2026-13")
        self.assertIn("availability", response.context)


class ConnectionGridViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="monitor", email="monitor@example.com", password="pw"
        )
        self.client.force_login(user)
        self.url = reverse("data_availability")
        self.connection = NetworkConnectionFactory(stations_timezone="Africa/Nairobi")
        self.link = StationLinkFactory(network_connection=self.connection)

    def get(self, **params):
        return self.client.get(self.url, params)

    def make_link(self, name, enabled=True):
        link = StationLinkFactory(
            network_connection=self.connection, station=StationFactory(name=name), enabled=enabled
        )
        return link

    def test_connection_alone_renders_the_grid_with_summaries(self):
        ObservationRecordFactory(
            station=self.link.station,
            connection=self.connection,
            time=datetime(2026, 3, 5, 6, 30, tzinfo=py_tz.utc),
        )

        response = self.get(connection=self.connection.id, month="2026-03")

        self.assertContains(response, "March 2026")
        self.assertContains(response, self.link.station.name)
        self.assertContains(response, "availability-grid")
        self.assertContains(response, "1/15")  # day cell: floor is 09:00 local on 5 Mar
        summary = response.context["grid_rows"][0]["summary"]
        self.assertEqual(summary.present_hours, 1)
        self.assertContains(response, f"1/{summary.expected_hours} h (")
        self.assertEqual([r["summary"].station_link for r in response.context["grid_rows"]], [self.link])

    def test_cells_and_labels_link_to_day_and_month_views(self):
        response = self.get(connection=self.connection.id, month="2026-03")

        self.assertContains(response, f"{self.url}?station_link={self.link.id}&amp;day=2026-03-07")
        row = response.context["grid_rows"][0]
        self.assertEqual(row["month_url"], f"{self.url}?station_link={self.link.id}&month=2026-03")
        self.assertContains(response, f'href="{row["month_url"].replace("&", "&amp;")}"')
        self.assertEqual(len(row["cells"]), 31)

    def test_sort_name_is_linkable_and_alphabetical(self):
        zulu = self.make_link("Zulu")
        alpha = self.make_link("Alpha")
        ObservationRecordFactory(
            station=alpha.station,
            connection=self.connection,
            time=datetime(2026, 3, 1, 0, 30, tzinfo=py_tz.utc),
        )

        by_name = self.get(connection=self.connection.id, month="2026-03", sort="name")
        worst_first = self.get(connection=self.connection.id, month="2026-03")

        names = lambda r: [row["summary"].name for row in r.context["grid_rows"]]
        self.assertEqual(names(by_name), sorted(names(by_name), key=str.lower))
        # only Alpha has a floor, so only it has expected (and missing) hours
        self.assertEqual(names(worst_first)[0], "Alpha")
        self.assertIn("sort=name", by_name.context["next_url"])
        self.assertIn("sort=name", worst_first.context["sort_name_url"])
        self.assertNotIn("sort=name", worst_first.context["next_url"])

    def test_disabled_links_sit_in_a_collapsed_group(self):
        self.make_link("Dormant", enabled=False)

        response = self.get(connection=self.connection.id, month="2026-03")

        self.assertContains(response, "Disabled (1)")
        self.assertContains(response, "<details")
        self.assertNotIn("Dormant", [r["summary"].name for r in response.context["grid_rows"]])
        self.assertEqual(
            [r["summary"].name for r in response.context["grid_disabled_rows"]], ["Dormant"]
        )

    def test_unknown_sort_falls_back_to_worst_first(self):
        response = self.get(connection=self.connection.id, sort="zzz")
        self.assertEqual(response.context["grid_sort"], "missing")

    def test_renders_for_a_connection_with_many_station_links_in_bounded_queries(self):
        with CaptureQueriesContext(db_connection) as one:
            self.get(connection=self.connection.id, month="2026-03")

        for number in range(40):
            self.make_link(f"Many {number}")
        with CaptureQueriesContext(db_connection) as many:
            response = self.get(connection=self.connection.id, month="2026-03")

        self.assertEqual(len(response.context["grid_rows"]), 41)
        self.assertEqual(len(many), len(one))


def availability_tz(link):
    from zoneinfo import ZoneInfo

    return ZoneInfo(str(link.timezone))


class DayViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="monitor", email="monitor@example.com", password="pw"
        )
        self.client.force_login(user)
        self.url = reverse("data_availability")
        self.connection = NetworkConnectionFactory(stations_timezone="Africa/Nairobi")
        self.link = StationLinkFactory(network_connection=self.connection)
        self.temp, self.wind = DataParameterFactory(), DataParameterFactory()
        self.patch_mappings(self.temp)

    def patch_mappings(self, *parameters):
        mappings = [make_mapping(p, p.unit, source_name=p.name) for p in parameters]
        patcher = mock.patch.object(
            StationLink, "get_variable_mappings", lambda self: mappings
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self, parameter, hour):
        ObservationRecordFactory(
            station=self.link.station,
            connection=self.connection,
            parameter=parameter,
            time=datetime(2026, 3, 5, hour, 30, tzinfo=py_tz.utc),
        )

    def get(self, **params):
        params.setdefault("station_link", self.link.id)
        return self.client.get(self.url, params)

    def test_day_param_renders_the_matrix_directly(self):
        self.record(self.temp, 6)
        self.record(self.wind, 6)

        response = self.get(month="2026-03", day="2026-03-05")

        self.assertEqual(response.status_code, 200)
        detail = response.context["day_detail"]
        self.assertEqual(detail.date, date(2026, 3, 5))
        self.assertContains(response, "5 March 2026")
        self.assertContains(response, "Any parameter")
        self.assertContains(response, self.temp.name)
        self.assertContains(response, self.wind.name)
        self.assertContains(response, "not currently mapped")
        self.assertContains(response, "availability-hour--present")
        self.assertContains(response, "2 records")  # tooltip of the any row
        # the count is printed in the cell itself, not only in the tooltip
        self.assertContains(response, '">2</td>')  # the any row's hour
        self.assertContains(response, '">1</td>')  # each parameter row's hour

    def test_breadcrumb_links_back_to_the_month(self):
        response = self.get(day="2026-03-05")

        month_url = f"{self.url}?station_link={self.link.id}&month=2026-03"
        self.assertEqual(response.context["month_url"], month_url)
        self.assertContains(response, month_url.replace("&", "&amp;"))

    def test_day_page_has_no_month_pager(self):
        self.assertContains(self.get(month="2026-03"), "availability-nav\"")
        self.assertNotContains(self.get(day="2026-03-05"), "availability-nav\"")

    def test_month_page_has_no_day_matrix(self):
        response = self.get(month="2026-03")

        self.assertNotIn("day_detail", response.context)

    def test_calendar_cells_link_to_their_day(self):
        response = self.get(month="2026-03")

        self.assertContains(
            response, f"{self.url}?station_link={self.link.id}&amp;day=2026-03-05"
        )

    def test_corner_marker_on_a_day_missing_a_mapped_parameter(self):
        self.record(self.wind, 6)  # temp is mapped but has no data on the 5th

        response = self.get(month="2026-03")

        self.assertContains(response, " availability-cell--gap\"")

    def test_no_corner_marker_without_a_parameter_gap(self):
        self.patch_mappings()

        response = self.get(month="2026-03")

        self.assertNotContains(response, " availability-cell--gap\"")

    def test_invalid_day_falls_back_to_the_month(self):
        for day in ("2026-02-30", "garbage", "2026-3-5", "0000-01-01", ""):
            with self.subTest(day=day):
                response = self.get(day=day, month="2026-03")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("day_detail", response.context)
                self.assertIn("availability", response.context)

    def test_day_alone_shows_that_days_month_calendar_context(self):
        response = self.get(day="2026-03-05")

        self.assertEqual(response.context["availability"].month, 3)


class DataAvailabilityAccessTests(TestCase):
    def test_read_only_monitoring_user_can_view_the_page(self):
        user = get_user_model().objects.create_user(
            username="viewer", email="viewer@example.com", password="pw"
        )
        user.user_permissions.add(Permission.objects.get(codename="access_admin"))
        self.client.force_login(user)

        response = self.client.get(reverse("data_availability"))

        self.assertEqual(response.status_code, 200)

    def test_anonymous_users_are_redirected_to_login(self):
        response = self.client.get(reverse("data_availability"))
        self.assertEqual(response.status_code, 302)


class EntryPointTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="monitor", email="monitor@example.com", password="pw"
        )
        self.client.force_login(user)
        self.link = StationLinkFactory()

    def test_monitoring_menu_offers_the_page(self):
        response = self.client.get(reverse("wagtailadmin_home"))
        # the sidebar menu is serialised into the page for the JS sidebar
        self.assertContains(response, "Monitoring")
        self.assertContains(response, reverse("data_availability"))

    def test_station_link_monitoring_page_links_to_it(self):
        response = self.client.get(reverse("station_link_monitoring", args=[self.link.id]))
        self.assertContains(response, f"{reverse('data_availability')}?station_link={self.link.id}")
