"""
Seam tests for the wis2box station export admin view, driven through the
test client.

The two outbound calls are patched where ADL makes them — ``requests.get``
for wis2box and ``OSCARClient`` for OSCAR — since those are the system
boundary; everything inside ADL runs for real.
"""

from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from wagtail.models import Site
from wagtail.users.models import UserProfile

from adl.core.models import AdlSettings
from adl.core.tests.factories import StationFactory
from adl.wis2box.models import Wis2BoxSettings
from adl.wis2box.utils import CACHE_KEY

WIS2BOX_URL = "https://wis2box.example.org"
TOPIC = "origin/a/wis2/mw-mw_met_centre/data/core/weather/surface-based-observations/synop"


def make_user(username, *codenames):
    """An admin-access user holding exactly ``codenames`` and nothing else."""
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", password="test-pass"
    )
    user.user_permissions.add(
        Permission.objects.get(codename="access_admin"),
        *[Permission.objects.get(codename=c) for c in codenames],
    )
    return user


def oscar_record(wigos_id, name="BALAKA", elevation=618):
    return {
        "name": name,
        "region": "Africa",
        "territory": "Malawi",
        "latitude": -14.983333,
        "longitude": 34.966666,
        "elevation": elevation,
        "stationTypeName": "Land (fixed)",
        "wigosId": wigos_id,
        "wigosStationIdentifiers": [{"wigosStationIdentifier": wigos_id, "primary": True}],
    }


def json_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class ExportViewTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        site = Site.objects.get(is_default_site=True)
        adl_settings = AdlSettings.for_site(site)
        adl_settings.country = "MW"
        adl_settings.save()
        wis2box_settings = Wis2BoxSettings.for_site(site)
        wis2box_settings.wis2box_url = WIS2BOX_URL
        wis2box_settings.save()

        self.url = reverse("export_wis2box_stations")
        self.wis2box_stations = []
        self.oscar_records = []

        requests_patch = patch("adl.wis2box.utils.requests.get", side_effect=self._fake_wis2box_get)
        self.wis2box_get = requests_patch.start()
        self.addCleanup(requests_patch.stop)

        oscar_patch = patch("adl.wis2box.utils.OSCARClient")
        oscar_client = oscar_patch.start()
        self.addCleanup(oscar_patch.stop)
        oscar_client.return_value.get_stations.side_effect = lambda **kwargs: {
            "stationSearchResults": self.oscar_records
        }
        self.oscar_client = oscar_client

    def _fake_wis2box_get(self, url, **kwargs):
        if "collections/stations" in url:
            return json_response({"features": [
                {"id": wigos_id, "properties": {"wigos_station_identifier": wigos_id}}
                for wigos_id in self.wis2box_stations
            ]})
        if "collections/discovery-metadata" in url:
            return json_response({"features": [{"properties": {"wmo:topicHierarchy": TOPIC}}]})
        raise AssertionError(f"unexpected wis2box call {url}")

    def login(self, *codenames):
        self.client.force_login(make_user("operator", *codenames))


class ExportBlockedTests(ExportViewTestCase):
    def test_unreachable_wis2box_blocks_the_export_even_with_stale_cache(self):
        StationFactory(station_id="0-454-2-AWSBALAKA")
        self.oscar_records = [oscar_record("0-454-2-AWSBALAKA")]
        cache.set(CACHE_KEY, [], timeout=600)  # stale list that would make every station look ADL-only
        self.wis2box_get.side_effect = requests.ConnectionError("wis2box down")
        self.login()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "wis2box down")
        self.assertNotContains(response, "0-454-2-AWSBALAKA")

    def test_unreachable_oscar_blocks_the_export(self):
        StationFactory(station_id="0-454-2-AWSBALAKA")
        self.oscar_client.return_value.get_stations.side_effect = requests.Timeout("oscar timed out")
        self.login()

        response = self.client.get(self.url)

        self.assertContains(response, "oscar timed out")
        self.assertNotContains(response, "0-454-2-AWSBALAKA")


class GroundClearanceTests(ExportViewTestCase):
    def test_clearance_input_starts_from_the_wis2box_setting(self):
        StationFactory(station_id="0-454-2-AWSBALAKA")
        self.oscar_records = [oscar_record("0-454-2-AWSBALAKA")]
        settings = Wis2BoxSettings.for_site(Site.objects.get(is_default_site=True))
        settings.barometer_ground_clearance = 1.25
        settings.save()
        self.login()

        response = self.client.get(self.url)

        self.assertRegex(response.content.decode(), r'id="wis2box-ground-clearance"[^>]*value="1\.25"')

    def test_clearance_prefill_survives_a_comma_decimal_admin_language(self):
        # A type=number input drops "1,25", which French formatting would render,
        # and the Apply button would parse "1146,5" as 1146
        StationFactory(station_id="0-454-2-AWSBALAKA", barometer_height_above_msl=619.25)
        self.oscar_records = [oscar_record("0-454-2-AWSBALAKA", elevation=1146.5)]
        settings = Wis2BoxSettings.for_site(Site.objects.get(is_default_site=True))
        settings.barometer_ground_clearance = 1.25
        settings.save()
        user = make_user("francophone")
        profile = UserProfile.get_for_user(user)
        profile.preferred_language = "fr"
        profile.save()
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertRegex(response.content.decode(), r'id="wis2box-ground-clearance"[^>]*value="1\.25"')
        self.assertContains(response, 'value="619.25"')
        self.assertContains(response, 'data-elevation="1146.5"')


class GenerateCsvTests(ExportViewTestCase):
    def setUp(self):
        super().setUp()
        self.station = StationFactory(station_id="0-454-2-AWSBALAKA", barometer_height_above_msl=None)
        self.oscar_records = [oscar_record("0-454-2-AWSBALAKA")]

    def post(self, barometer="619.25", **extra):
        data = {
            "selected": ["0-454-2-AWSBALAKA"],
            "barometer_height__0-454-2-AWSBALAKA": barometer,
            "topic": TOPIC,
            **extra,
        }
        return self.client.post(self.url, data)

    def test_selected_station_without_barometer_height_gets_no_csv(self):
        self.login()

        response = self.post(barometer="")

        self.assertContains(response, "Barometer height is required")
        self.assertNotContains(response, "station_name,wigos_station_identifier")

    def test_valid_selection_previews_the_csv_from_oscar_values(self):
        self.login()

        response = self.post()

        self.assertContains(
            response,
            "BALAKA,0-454-2-AWSBALAKA,,landFixed,-14.983333,34.966666,618,619.25,MWI,africa",
        )

    def test_barometer_heights_are_saved_for_a_user_who_can_change_stations(self):
        self.login("change_station")

        self.post(save_barometer_heights="on")

        self.station.refresh_from_db()
        self.assertEqual(self.station.barometer_height_above_msl, 619.25)

    def test_barometer_heights_are_not_saved_without_change_station(self):
        self.login()

        response = self.post(save_barometer_heights="on")

        self.station.refresh_from_db()
        self.assertIsNone(self.station.barometer_height_above_msl)
        self.assertContains(response, "619.25,MWI,africa")

    def test_generate_rechecks_wis2box_rather_than_trusting_the_cached_list(self):
        self.login()
        self.client.get(self.url)  # primes the wis2box cache
        self.wis2box_get.side_effect = requests.ConnectionError("wis2box down")

        response = self.post()

        self.assertContains(response, "wis2box down")
        self.assertNotContains(response, "station_name,wigos_station_identifier")

    def test_selected_station_that_is_no_longer_exportable_is_reported(self):
        self.login()
        self.client.get(self.url)
        self.oscar_records = []  # OSCAR no longer lists the station by the time of Generate
        cache.clear()

        response = self.post()

        self.assertContains(response, "no longer exportable")
        self.assertNotContains(response, "station_name,wigos_station_identifier")
