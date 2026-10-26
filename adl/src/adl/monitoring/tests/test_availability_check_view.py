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
from adl.core.tests.helpers import make_mapping
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
            "day": "2026-03-05",
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

        with patch(f"{GAP}.check_whole_day") as check:
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

        with patch(f"{GAP}.check_whole_day", return_value=gap_service.CheckOutcome(
                tier=TIER_FETCH, task_id="t1")):
            response = self.post()

        self.assertEqual(response.status_code, 200)

    def test_the_gate_is_the_shared_rule_on_the_station_links_connection(self):
        # core.permissions owns the concrete-versus-base rule (and its tests);
        # the view must ask it about this link's connection, and obey it
        user = self.plain_user()

        for allowed, status in ((True, 200), (False, 403)):
            with self.subTest(allowed=allowed), \
                    patch(f"{GAP}.check_whole_day", return_value=gap_service.CheckOutcome(
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
    def test_a_day_is_checked_whole_through_the_gap_service(self):
        with patch(f"{GAP}.check_whole_day", return_value=gap_service.CheckOutcome(
                tier=TIER_FETCH, task_id="task-1")) as check_whole_day:
            response = self.post()

        self.assertEqual(response.json(), {"state": "PENDING", "tier": TIER_FETCH,
                                           "task_id": "task-1"})
        args, kwargs = check_whole_day.call_args
        self.assertEqual(args[0].id, self.link.id)
        self.assertEqual(args[1], datetime(2026, 3, 5).date())
        self.assertFalse(kwargs["force_fetch"])

    def test_a_listing_tier_answer_returns_the_stored_check(self):
        stored = AvailabilityCheck.objects.create(
            station_link=self.link, window_start=utc(2026, 3, 5, 6),
            window_end=utc(2026, 3, 5, 9), created_at=NOW, tier=TIER_LISTING,
            status=SourceCheckStatus.OK)

        with patch(f"{GAP}.check_whole_day", return_value=gap_service.CheckOutcome(
                tier=TIER_LISTING, check=stored)):
            response = self.post()

        self.assertEqual(response.json()["state"], "SUCCESS")
        self.assertEqual(response.json()["check_id"], stored.id)

    def test_fetch_flag_asks_for_the_fetch_tier(self):
        with patch(f"{GAP}.check_whole_day", return_value=gap_service.CheckOutcome(
                tier=TIER_FETCH, task_id="t")) as check:
            self.post(fetch="1")

        self.assertTrue(check.call_args.kwargs["force_fetch"])

    def test_refusals_map_to_status_codes(self):
        for error, status in (
            (gap_service.CheckInFlight("busy"), 409),
            (gap_service.CheckCoolingDown("wait"), 429),
            (gap_service.InvalidWindow("nothing"), 400),
            (gap_service.CheckUnavailable("no source"), 400),
        ):
            with self.subTest(error=type(error).__name__), \
                    patch(f"{GAP}.check_whole_day", side_effect=error):
                response = self.post()
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"], str(error))

    def test_bad_input_is_a_400_or_404(self):
        with patch(f"{GAP}.check_whole_day") as check:
            self.assertEqual(self.post(day="5 March").status_code, 400)
            self.assertEqual(self.post(day=None).status_code, 400)
            self.assertEqual(self.post(station_link="999999").status_code, 404)
            self.assertEqual(self.post(station_link=None).status_code, 404)
        check.assert_not_called()

    def test_a_read_only_user_cannot_check_a_day(self):
        self.plain_user()

        with patch(f"{GAP}.check_whole_day") as check_whole_day:
            response = self.post()

        self.assertEqual(response.status_code, 403)
        check_whole_day.assert_not_called()


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

    def with_mapping(self):
        patcher = patch.object(
            StationLink, "get_variable_mappings",
            lambda self: [make_mapping(DataParameterFactory(), None, source_name="t")])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_managers_get_the_status_panel_and_no_row_selection(self):
        self.with_mapping()

        response = self.day()

        self.assertContains(response, 'id="availability-panel"')
        self.assertNotContains(response, "availability-hour--selectable")
        self.assertNotContains(response, "availability-check-bar")

    def month(self, **extra):
        return self.client.get(reverse("data_availability"),
                               {"station_link": self.link.id, "month": "2026-03", **extra})

    def test_the_month_calendar_offers_no_actions(self):
        response = self.month()

        self.assertNotContains(response, 'id="availability-check-bar"')
        self.assertNotContains(response, "data-day=")
        self.assertNotContains(response, "Check whole day")

    def test_an_unchecked_gap_offers_the_whole_day_check_labelled_with_its_span(self):
        self.with_mapping()

        response = self.day()

        self.assertContains(response, 'data-day="2026-03-05"')
        self.assertContains(response, "Check source")
        self.assertContains(response, "00:00&ndash;00:00, 24 h")  # a fully empty day
        self.assertNotContains(response, 'data-check="')

    def test_a_day_without_a_mapped_gap_explains_instead_of_offering(self):
        with patch.object(StationLink, "get_variable_mappings", lambda self: []):
            response = self.day()

        self.assertNotContains(response, "Check source")
        self.assertContains(response, "nothing to check")

    def test_a_check_that_found_data_offers_recovery_of_its_window(self):
        self.with_mapping()
        stored = self.store(window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0),
                            ranges=[{"start": utc(2026, 3, 5, 6).isoformat(),
                                     "end": utc(2026, 3, 5, 8).isoformat(), "count": 4,
                                     "label": ""}])

        response = self.day()

        self.assertContains(response, 'data-check="')
        self.assertContains(response, f'data-check="{stored.id}"')
        self.assertContains(response, "Recover missing data")

    def test_a_check_that_found_nothing_offers_only_a_new_check(self):
        self.with_mapping()
        self.store(window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0))

        response = self.day()

        self.assertContains(response, "The source has nothing for this gap.")
        self.assertContains(response, "Check source again")
        self.assertNotContains(response, 'data-check="')

    def test_a_recovery_reports_its_counts_and_offers_a_new_check(self):
        self.with_mapping()
        self.store(window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0),
                   ranges=[{"start": utc(2026, 3, 5, 6).isoformat(),
                            "end": utc(2026, 3, 5, 8).isoformat(), "count": 4, "label": ""}],
                   recovered=True, recovery_fetched=12, recovery_saved=6)

        response = self.day()

        self.assertContains(response, "Recovery fetched 12 and saved 6 record(s).")
        self.assertContains(response, "Check source again")
        self.assertNotContains(response, 'data-check="')

    def test_a_recovery_that_saved_nothing_is_not_offered_again(self):
        self.with_mapping()
        self.store(window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0),
                   ranges=[{"start": utc(2026, 3, 5, 6).isoformat(),
                            "end": utc(2026, 3, 5, 8).isoformat(), "count": 4, "label": ""}],
                   recovery_fetched=3, recovery_saved=0)

        response = self.day()

        self.assertNotContains(response, 'data-check="')

    def test_a_run_in_flight_shows_the_panel_running_and_disables_the_action(self):
        self.with_mapping()
        cache.set(gap_service.inflight_key(self.link.id),
                  "recover|2026-03-10T10:42:00+00:00", timeout=60)

        response = self.day()

        self.assertContains(response, "Recovering")
        self.assertContains(response, "since 10:42")
        self.assertContains(response, 'data-running="1"')
        self.assertNotContains(response, 'data-check="')
        self.assertNotContains(response, "Check source again")

    def test_an_idle_panel_does_not_watch_for_a_run(self):
        self.with_mapping()

        self.assertNotContains(self.day(), 'data-running="1"')

    def test_read_only_users_get_no_panel_and_no_recovery(self):
        self.plain_user()
        self.store(ranges=[{"start": utc(2026, 3, 5, 6).isoformat(),
                            "end": utc(2026, 3, 5, 8).isoformat(), "count": 4, "label": ""}])

        response = self.day()

        self.assertNotContains(response, 'id="availability-panel"')
        self.assertNotContains(response, 'data-check="')

    def test_the_checked_glyph_appears_once_every_gap_of_the_day_has_a_result(self):
        self.assertNotContains(self.month(), 'class="availability-checked"')

        self.store(window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0))
        response = self.month()

        self.assertContains(response, 'class="availability-checked"')
        self.assertEqual(response.content.decode().count('class="availability-checked"'), 1)

    def test_the_glyph_is_on_the_connection_grid_too(self):
        self.store(window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0))

        response = self.client.get(reverse("data_availability"),
                                   {"connection": self.connection.id, "month": "2026-03"})

        self.assertContains(response, 'class="availability-checked"', count=1)

    def test_listing_support_is_announced_before_the_click(self):
        self.with_mapping()
        with patch.object(StationLink, "availability_check_supported", True):
            response = self.day()

        self.assertContains(response, "The check is instant")

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
        self.with_mapping()
        self.store(window_start=utc(2026, 3, 5, 0), window_end=utc(2026, 3, 6, 0),
                   tier=TIER_LISTING, status=SourceCheckStatus.FAILED, message="no route")

        response = self.day()

        self.assertContains(response, "The check did not answer.")
        self.assertContains(response, "Try by fetching data")
        self.assertContains(response, 'data-fetch="1"')

    def test_a_failed_fetch_or_an_answered_listing_offers_no_fetch_action(self):
        self.with_mapping()
        self.store(tier=TIER_FETCH, status=SourceCheckStatus.FAILED)
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.OK)

        self.assertNotContains(self.day(), "Try by fetching data")

    def test_a_later_check_of_the_same_window_retires_the_fetch_action(self):
        self.with_mapping()
        self.store(tier=TIER_LISTING, status=SourceCheckStatus.FAILED,
                   created_at=utc(2026, 3, 9, 10))
        self.store(tier=TIER_FETCH, status=SourceCheckStatus.OK,
                   created_at=utc(2026, 3, 9, 11))

        self.assertNotContains(self.day(), "Try by fetching data")

    def test_the_history_carries_no_actions_and_shows_recovery_counts(self):
        self.with_mapping()
        self.store(recovered=True, recovery_fetched=5, recovery_saved=4,
                   ranges=[{"start": utc(2026, 3, 5, 6).isoformat(),
                            "end": utc(2026, 3, 5, 8).isoformat(), "count": 4, "label": ""}])

        response = self.day()

        self.assertContains(response, "Recovery fetched 5, saved 4.")
        self.assertNotContains(response, "availability-recover")
        self.assertNotContains(response, "availability-fetch-instead")

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
            patch.object(StationLink, "get_variable_mappings",
                         lambda self: [make_mapping(DataParameterFactory(), None, source_name="t")]),
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


class RecoverViewTests(CheckViewTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("availability_recover")
        self.payload = {"station_link": self.link.id, "check": "7"}

    def test_a_read_only_user_gets_403_and_nothing_runs(self):
        self.plain_user()

        with patch(f"{GAP}.recover") as recover:
            response = self.post()

        self.assertEqual(response.status_code, 403)
        recover.assert_not_called()

    def test_the_status_endpoint_is_gated_the_same_way(self):
        self.plain_user()

        response = self.client.get(
            reverse("availability_recover_status", args=["abc"]), {"station_link": self.link.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 403)

    def test_enqueues_the_checks_recovery_and_returns_the_task_id(self):
        with patch(f"{GAP}.recover", return_value="t1") as recover:
            response = self.post()

        self.assertEqual(response.json(), {"state": "PENDING", "task_id": "t1"})
        args, _ = recover.call_args
        self.assertEqual((args[0], args[1]), (self.link, 7))

    def test_refusals_map_to_status_codes(self):
        for error, status in ((gap_service.CheckInFlight("x"), 409),
                              (gap_service.InvalidWindow("x"), 400),
                              (gap_service.CheckUnavailable("x"), 400)):
            with self.subTest(error=type(error).__name__), \
                    patch(f"{GAP}.recover", side_effect=error):
                self.assertEqual(self.post().status_code, status)

    def test_a_missing_or_malformed_check_is_a_400(self):
        self.assertEqual(self.post(check="nope").status_code, 400)
        self.assertEqual(self.post(check=None).status_code, 400)

    def status(self, result):
        with patch("adl.monitoring.views.availability.AsyncResult") as async_result:
            async_result.return_value.state = "SUCCESS"
            async_result.return_value.result = result
            return self.client.get(
                reverse("availability_recover_status", args=["t1"]),
                {"station_link": self.link.id}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_status_reports_the_counts(self):
        response = self.status({"station_link": self.link.id, "busy": False,
                                "fetched": 5, "saved": 4})

        self.assertEqual(response.json(), {"state": "SUCCESS", "fetched": 5, "saved": 4})

    def test_status_reports_busy(self):
        response = self.status({"station_link": self.link.id, "busy": True,
                                "fetched": 0, "saved": 0})

        self.assertEqual(response.json()["state"], "BUSY")

    def test_status_of_another_station_links_task_is_unknown(self):
        response = self.status({"station_link": self.link.id + 1, "busy": False,
                                "fetched": 5, "saved": 4})

        self.assertEqual(response.status_code, 404)


class RunningStatusTests(CheckViewTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.url = reverse("availability_running")

    def get(self, **params):
        return self.client.get(self.url, {"station_link": self.link.id, **params},
                               HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_idle(self):
        self.assertEqual(self.get().json(), {"running": False})

    def test_reports_the_kind_and_start_of_the_claim(self):
        gap_service.claim(self.link, gap_service.CLAIM_CHECK, utc(2026, 3, 5, 6))

        body = self.get().json()

        self.assertEqual((body["running"], body["kind"]), (True, "check"))
        self.assertIsNotNone(body["since"])

    def test_a_claim_in_the_old_bare_format_still_reads_as_running(self):
        cache.set(gap_service.inflight_key(self.link.id), "check", timeout=60)

        body = self.get().json()

        self.assertEqual((body["running"], body["kind"], body["since"]), (True, "check", None))

    def test_it_names_the_local_day_being_asked_about(self):
        gap_service.claim(self.link, gap_service.CLAIM_CHECK, utc(2026, 3, 5, 6))

        self.assertEqual(self.get().json()["day"], "2026-03-05")

    def test_a_read_only_user_may_read_it(self):
        self.plain_user()
        gap_service.claim(self.link, gap_service.CLAIM_CHECK, utc(2026, 3, 5, 6))

        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["running"])

    def test_an_unknown_station_link_is_a_404(self):
        self.assertEqual(self.get(station_link="999999").status_code, 404)


class RunningIndicatorTests(CheckViewTestCase):
    """The spinner on the day being checked, on the month calendar and the grid."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        gap_service.claim(self.link, gap_service.CLAIM_CHECK, utc(2026, 3, 5, 6))
        self.month = {"station_link": self.link.id, "month": "2026-03"}
        self.grid = {"connection": self.connection.id, "month": "2026-03"}

    def get(self, params, user=None):
        if user:
            self.plain_user()
        return self.client.get(reverse("data_availability"), params)

    def test_the_month_calendar_marks_only_the_day_being_checked_and_watches_it(self):
        response = self.get(self.month)

        self.assertContains(response, 'class="availability-running"', count=1)
        self.assertContains(response, 'id="availability-running-watch"')

    def test_another_month_shows_no_indicator_and_no_watch(self):
        response = self.get({**self.month, "month": "2026-04"})

        self.assertNotContains(response, 'class="availability-running"')
        self.assertNotContains(response, 'id="availability-running-watch"')

    def test_a_read_only_viewer_sees_it_too(self):
        response = self.get(self.month, user=True)

        self.assertContains(response, 'class="availability-running"', count=1)

    def test_the_connection_grid_marks_the_day_in_the_links_row_without_a_watch(self):
        response = self.get(self.grid)

        self.assertContains(response, 'class="availability-running"', count=1)
        self.assertNotContains(response, 'id="availability-running-watch"')

    def test_an_idle_link_shows_nothing(self):
        cache.clear()

        self.assertNotContains(self.get(self.month), 'class="availability-running"')
        self.assertNotContains(self.get(self.grid), 'class="availability-running"')
