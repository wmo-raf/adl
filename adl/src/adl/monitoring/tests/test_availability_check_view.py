"""
The availability-check actions and the day view's rendering of stored checks.

The gap service is substituted at its module boundary
(``adl.monitoring.views.availability.gap_service``); its own behaviour is
tested in ``test_gap_service``. What is asserted here is HTTP-level: who may
act, how refusals map to status codes, and what the page shows.
"""

from datetime import datetime, timezone as py_tz
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from adl.core.availability_checks import TIER_FETCH, TIER_LISTING, AvailabilityCheckResult
from adl.core.models import StationLink
from adl.core.source_checks import SourceCheckStatus
from adl.core.tests.factories import (
    DataParameterFactory,
    NetworkConnectionFactory,
    StationLinkFactory,
)
from adl.monitoring import gap_service
from adl.monitoring.models import AvailabilityCheck
from adl.monitoring.tasks import run_availability_check

UTC = py_tz.utc
NOW = datetime(2026, 3, 10, 0, 0, tzinfo=UTC)
GAP = "adl.monitoring.views.availability.gap_service"


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class CheckViewTestCase(TestCase):
    def setUp(self):
        self.connection = NetworkConnectionFactory(stations_timezone="UTC")
        self.link = StationLinkFactory(network_connection=self.connection)
        self.superuser = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="pw")
        self.client.force_login(self.superuser)
        self.url = reverse("availability_check")
        self.payload = {
            "station_link": self.link.id,
            "start": "2026-03-05T06:00:00Z",
            "end": "2026-03-05T09:00:00Z",
        }

    def post(self, **overrides):
        data = {**self.payload, **overrides}
        # the page's JS sends this header; Wagtail answers a denied XHR with 403
        # where it would redirect a plain page request
        return self.client.post(self.url, {k: v for k, v in data.items() if v is not None},
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def plain_user(self, *codenames):
        user = get_user_model().objects.create_user(
            username="operator", email="op@example.com", password="pw")
        user.user_permissions.add(Permission.objects.get(codename="access_admin"))
        for codename in codenames:
            user.user_permissions.add(Permission.objects.get(codename=codename))
        self.client.force_login(user)
        return user


class CheckPermissionTests(CheckViewTestCase):
    def test_a_read_only_monitoring_user_gets_403_and_nothing_runs(self):
        self.plain_user()

        with patch(f"{GAP}.check") as check:
            response = self.post()

        self.assertEqual(response.status_code, 403)
        check.assert_not_called()

    def test_the_status_endpoint_is_gated_the_same_way(self):
        self.plain_user()

        response = self.client.get(
            reverse("availability_check_status", args=["abc"]), {"station_link": self.link.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 403)

    def test_change_permission_on_the_base_connection_passes(self):
        self.plain_user("change_networkconnection")

        with patch(f"{GAP}.check", return_value=gap_service.CheckOutcome(
                tier=TIER_FETCH, task_id="t1")):
            response = self.post()

        self.assertEqual(response.status_code, 200)

    def test_the_gate_is_the_shared_rule_on_the_station_links_connection(self):
        # core.permissions owns the concrete-versus-base rule (and its tests);
        # the view must ask it about this link's connection, and obey it
        user = self.plain_user()

        for allowed, status in ((True, 200), (False, 403)):
            with self.subTest(allowed=allowed), \
                    patch(f"{GAP}.check", return_value=gap_service.CheckOutcome(
                        tier=TIER_FETCH, task_id="t1")), \
                    patch("adl.monitoring.views.availability.can_manage_connection",
                          return_value=allowed) as can_manage:
                response = self.post()

            self.assertEqual(response.status_code, status)
            self.assertEqual(can_manage.call_args.args[0], user)
            self.assertEqual(can_manage.call_args.args[1].id, self.connection.id)

    def test_only_post_is_allowed_on_the_check_endpoint(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class CheckPostTests(CheckViewTestCase):
    def test_a_fetch_tier_answer_returns_a_task_to_poll(self):
        with patch(f"{GAP}.check", return_value=gap_service.CheckOutcome(
                tier=TIER_FETCH, task_id="task-1")) as check:
            response = self.post(parameter=str(DataParameterFactory().id))

        self.assertEqual(response.json(), {"state": "PENDING", "tier": TIER_FETCH,
                                           "task_id": "task-1"})
        args, kwargs = check.call_args
        self.assertEqual(args[0].id, self.link.id)
        self.assertEqual(args[1], utc(2026, 3, 5, 6))
        self.assertEqual(args[2], utc(2026, 3, 5, 9))
        self.assertFalse(kwargs["force_fetch"])

    def test_a_listing_tier_answer_returns_the_stored_check(self):
        stored = AvailabilityCheck.objects.create(
            station_link=self.link, window_start=utc(2026, 3, 5, 6),
            window_end=utc(2026, 3, 5, 9), created_at=NOW, tier=TIER_LISTING,
            status=SourceCheckStatus.OK)

        with patch(f"{GAP}.check", return_value=gap_service.CheckOutcome(
                tier=TIER_LISTING, check=stored)):
            response = self.post(fetch="1")

        self.assertEqual(response.json()["state"], "SUCCESS")
        self.assertEqual(response.json()["check_id"], stored.id)

    def test_fetch_flag_asks_for_the_fetch_tier(self):
        with patch(f"{GAP}.check", return_value=gap_service.CheckOutcome(
                tier=TIER_FETCH, task_id="t")) as check:
            self.post(fetch="1")

        self.assertTrue(check.call_args.kwargs["force_fetch"])

    def test_refusals_map_to_status_codes(self):
        for error, status in (
            (gap_service.CheckInFlight("busy"), 409),
            (gap_service.CheckCoolingDown("wait"), 429),
            (gap_service.InvalidWindow("too long"), 400),
            (gap_service.CheckUnavailable("no source"), 400),
        ):
            with self.subTest(error=type(error).__name__), \
                    patch(f"{GAP}.check", side_effect=error):
                response = self.post()
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"], str(error))

    def test_bad_input_is_a_400_or_404(self):
        with patch(f"{GAP}.check") as check:
            self.assertEqual(self.post(start="garbage").status_code, 400)
            self.assertEqual(self.post(start="2026-03-05T06:00:00").status_code, 400)  # naive
            self.assertEqual(self.post(parameter="x").status_code, 400)
            self.assertEqual(self.post(station_link="999999").status_code, 404)
            self.assertEqual(self.post(station_link=None).status_code, 404)
        check.assert_not_called()


class CheckStatusTests(CheckViewTestCase):
    def status(self, state, result=None, link=None):
        url = reverse("availability_check_status", args=["task-1"])
        with patch("adl.monitoring.views.availability.AsyncResult") as result_class:
            result_class.return_value.state = state
            result_class.return_value.result = result
            return self.client.get(url, {"station_link": (link or self.link).id})

    def stored(self, link=None):
        return AvailabilityCheck.objects.create(
            station_link=link or self.link, window_start=utc(2026, 3, 5, 6),
            window_end=utc(2026, 3, 5, 9), created_at=NOW, tier=TIER_FETCH,
            status=SourceCheckStatus.OK)

    def test_pending_and_started_keep_polling(self):
        for state in ("PENDING", "STARTED"):
            self.assertEqual(self.status(state).json(), {"state": "PENDING"})

    def test_success_names_the_stored_check(self):
        stored = self.stored()

        self.assertEqual(self.status("SUCCESS", stored.id).json(),
                         {"state": "SUCCESS", "check_id": stored.id})

    def test_a_check_of_another_station_link_is_not_revealed(self):
        other = StationLinkFactory(network_connection=self.connection)
        stored = self.stored(link=other)

        self.assertEqual(self.status("SUCCESS", stored.id).status_code, 404)

    def test_failure_does_not_leak_the_task_error(self):
        response = self.status("FAILURE", "boom password=hunter2")

        self.assertEqual(response.json()["state"], "FAILURE")
        self.assertNotIn("hunter2", response.content.decode())


class DayViewRenderingTests(CheckViewTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(StationLink, "get_first_collection_date",
                               lambda self: utc(2026, 3, 1))
        patcher.start()
        self.addCleanup(patcher.stop)
        now = patch("django.utils.timezone.now", return_value=NOW)
        now.start()
        self.addCleanup(now.stop)

    def day(self, **extra):
        return self.client.get(reverse("data_availability"),
                               {"station_link": self.link.id, "day": "2026-03-05", **extra})

    def store(self, **kwargs):
        defaults = dict(
            station_link=self.link, window_start=utc(2026, 3, 5, 6),
            window_end=utc(2026, 3, 5, 9), created_at=NOW, tier=TIER_FETCH,
            status=SourceCheckStatus.OK, ranges=[])
        return AvailabilityCheck.objects.create(**{**defaults, **kwargs})

    def test_managers_get_the_check_bar_and_selectable_missing_hours(self):
        response = self.day()

        self.assertContains(response, 'id="availability-check-bar"')
        self.assertContains(response, "availability-hour--missing availability-hour--selectable")
        self.assertContains(response, "Runs in the background")
        self.assertContains(response, 'data-start="2026-03-05T06:00:00+00:00"')

    def test_listing_support_is_announced_before_the_click(self):
        with patch.object(StationLink, "availability_check_supported", True):
            response = self.day()

        self.assertContains(response, "The answer is instant")

    def test_read_only_users_see_the_day_but_no_check_bar(self):
        self.plain_user()

        response = self.day()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="availability-check-bar"')
        self.assertNotContains(response, "availability-hour--missing availability-hour--selectable")

    def test_a_check_with_data_is_rendered_on_the_hours_it_covers(self):
        self.store(ranges=[{"start": utc(2026, 3, 5, 6).isoformat(),
                            "end": utc(2026, 3, 5, 8).isoformat(), "count": 4, "label": ""}])

        response = self.day()

        self.assertContains(response, "Source has data, not recovered")
        self.assertContains(response, "Covers 2 of 3 missing hours.")
        self.assertContains(response, "checked by fetching and parsing data")
        self.assertContains(response, "availability-hour--source-has_data")
        self.assertContains(response, "availability-hour--source-nothing")

    def test_a_check_with_nothing_is_worded_differently(self):
        self.store()

        response = self.day()

        self.assertContains(response, "Source has nothing")
        self.assertNotContains(response, "Source has data, not recovered</strong>")

    def test_the_listing_tier_is_worded_as_a_file_listing(self):
        self.store(tier=TIER_LISTING)

        self.assertContains(self.day(), "checked by file listing")

    def test_a_failed_check_shows_its_message_and_category(self):
        self.store(status=SourceCheckStatus.FAILED, message="no route to host",
                   category="TCP_TIMEOUT")

        response = self.day()

        self.assertContains(response, "Check did not answer")
        self.assertContains(response, "no route to host")
        self.assertContains(response, "TCP_TIMEOUT")

    def test_a_failed_listing_offers_the_explicit_fetch_action(self):
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.FAILED, message="no route")

        response = self.day()

        self.assertContains(response, "Try by fetching data")
        self.assertContains(response, 'data-start="2026-03-05T06:00:00+00:00"')

    def test_a_failed_fetch_or_an_answered_listing_offers_no_fetch_action(self):
        self.store(tier=TIER_FETCH, status=SourceCheckStatus.FAILED)
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.OK)

        self.assertNotContains(self.day(), "Try by fetching data")

    def test_a_later_check_of_the_same_window_retires_the_fetch_action(self):
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.FAILED,
                   created_at=utc(2026, 3, 9, 10))
        self.store(tier=TIER_FETCH, status=SourceCheckStatus.OK,
                   created_at=utc(2026, 3, 9, 11))

        self.assertNotContains(self.day(), "Try by fetching data")

    def test_a_later_check_of_another_window_leaves_the_fetch_action(self):
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.FAILED,
                   created_at=utc(2026, 3, 9, 10))
        self.store(tier=TIER_FETCH, status=SourceCheckStatus.OK, created_at=utc(2026, 3, 9, 11),
                   window_start=utc(2026, 3, 5, 12), window_end=utc(2026, 3, 5, 14))

        self.assertContains(self.day(), "Try by fetching data")

    def test_the_fetch_action_carries_the_checks_parameter(self):
        parameter = DataParameterFactory()
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.FAILED, parameter=parameter)

        self.assertContains(self.day(), f'data-parameter="{parameter.id}"')

    def test_an_any_parameter_check_carries_no_parameter(self):
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.FAILED)

        self.assertContains(self.day(), 'data-parameter=""')

    def test_a_malformed_listing_stored_message_is_shown_with_the_action(self):
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.MALFORMED,
                   message="The plugin returned str instead of an AvailabilityCheckResult.")

        response = self.day()

        self.assertContains(response, "returned str instead")
        self.assertContains(response, "Try by fetching data")

    def test_per_parameter_breakdown_is_listed(self):
        parameter = DataParameterFactory(name="Air temperature")
        with patch.object(StationLink, "get_variable_mappings",
                          lambda self: [type("M", (), {"adl_parameter": parameter})()]):
            self.store(ranges=[], parameter_coverage={
                str(parameter.id): [utc(2026, 3, 5, 7).isoformat()]})

            response = self.day()

        self.assertContains(response, "Air temperature: 1 hour with data")


class CheckThroughTheRealServiceTests(CheckViewTestCase):
    """POSTs that go through the real gap service; only the plugin is stubbed."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.listing = [AvailabilityCheckResult(status=SourceCheckStatus.OK)]
        patchers = (
            patch.object(StationLink, "get_first_collection_date", lambda self: utc(2026, 3, 1)),
            patch.object(StationLink, "get_variable_mappings", lambda self: []),
            patch.object(StationLink, "availability_check_supported", True),
            patch.object(StationLink, "check_availability",
                         lambda link, start, end: self.listing[0]),
            patch("django.utils.timezone.now", return_value=NOW),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_supported_link_is_answered_in_the_request_and_nothing_is_queued(self):
        with patch.object(run_availability_check, "delay") as delay:
            body = self.post().json()

        delay.assert_not_called()
        self.assertEqual((body["state"], body["tier"]), ("SUCCESS", TIER_LISTING))

    def test_an_unsupported_answer_falls_through_to_the_background_check(self):
        self.listing[0] = AvailabilityCheckResult(status=SourceCheckStatus.UNSUPPORTED)

        with patch.object(run_availability_check, "delay") as delay:
            delay.return_value.id = "task-9"
            body = self.post().json()

        self.assertEqual(body, {"state": "PENDING", "tier": TIER_FETCH, "task_id": "task-9"})

    def test_a_second_press_inside_the_cooldown_is_a_429(self):
        self.post()

        response = self.post()

        self.assertEqual(response.status_code, 429)

    def test_a_failed_listing_is_stored_and_the_explicit_fetch_then_queues(self):
        self.listing[0] = AvailabilityCheckResult(status=SourceCheckStatus.FAILED, message="down")

        with patch.object(run_availability_check, "delay") as delay:
            delay.return_value.id = "task-2"
            first = self.post().json()
            delay.assert_not_called()
            second = self.post(fetch="1").json()

        self.assertEqual(first["state"], "SUCCESS")
        self.assertEqual(AvailabilityCheck.objects.get(id=first["check_id"]).status,
                         SourceCheckStatus.FAILED)
        self.assertEqual((second["state"], second["tier"]), ("PENDING", TIER_FETCH))

    def test_a_malformed_listing_is_stored_redacted_and_not_queued(self):
        self.listing[0] = "token=abc123secret"

        with patch.object(run_availability_check, "delay") as delay:
            body = self.post().json()

        delay.assert_not_called()
        stored = AvailabilityCheck.objects.get(id=body["check_id"])
        self.assertEqual(stored.status, SourceCheckStatus.MALFORMED)
        self.assertEqual(stored.tier, TIER_LISTING)
