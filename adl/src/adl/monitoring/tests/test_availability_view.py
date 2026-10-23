"""The Data availability page: URL-param parsing, rendering, and access."""

from datetime import datetime, timezone as py_tz

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from adl.core.tests.factories import (
    NetworkConnectionFactory,
    ObservationRecordFactory,
    StationLinkFactory,
)


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

    def test_connection_alone_lists_only_its_station_links(self):
        other = StationLinkFactory()

        response = self.get(connection=self.connection.id)

        self.assertEqual(response.context["station_links"], [self.link])
        self.assertNotIn(other, response.context["station_links"])
        self.assertContains(response, "Choose a station link")

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


def availability_tz(link):
    from zoneinfo import ZoneInfo

    return ZoneInfo(str(link.timezone))


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
