"""
Reading a run's log from the admin: the lines endpoint behind the
station-link monitoring page's "Show log" toggle, and the batch log page.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_timezone

from adl.core.tests.factories import StationLinkFactory
from adl.monitoring.models import IngestionBatchLog, StationLinkActivityLog

LINE = {"t": "2026-11-10T07:23:01+00:00", "level": "WARNING", "logger": "x", "msg": "decoding file"}


class RunLogViewTestCase(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="pw"
        )
        self.client.force_login(user)
        self.link = StationLinkFactory()

    def activity(self, **kwargs):
        kwargs.setdefault("time", dj_timezone.now())
        kwargs.setdefault("direction", "pull")
        return StationLinkActivityLog.objects.create(station_link=self.link, **kwargs)

    def lines(self, activity):
        return self.client.get(reverse("activity_log_lines", args=[activity.id])).json()


class ActivityLogLinesTests(RunLogViewTestCase):
    def test_a_finished_run_returns_its_lines_and_no_live_channel(self):
        run = self.activity(status="COMPLETED", success=True, log_lines=[LINE])
        data = self.lines(run)
        self.assertEqual(data["lines"], [LINE])
        self.assertTrue(data["captured"])
        self.assertFalse(data["running"])
        self.assertIsNone(data["channel"])

    def test_a_run_in_progress_gets_its_live_channel(self):
        run = self.activity(status="STARTED", log_lines=[LINE])
        data = self.lines(run)
        self.assertTrue(data["running"])
        self.assertEqual(data["channel"], f"activity-{run.id}")

    def test_a_run_from_before_capture_says_so(self):
        run = self.activity(status="FAILED", message="Ingestion worker died mid-run (no completion recorded)")
        data = self.lines(run)
        self.assertEqual(data["lines"], [])
        self.assertFalse(data["captured"])

    def test_a_run_links_to_its_batch_log_when_there_is_one(self):
        IngestionBatchLog.objects.create(task_id="t-1", time=dj_timezone.now(), log_lines=[LINE])
        run = self.activity(status="COMPLETED", task_id="t-1", log_lines=[])
        self.assertEqual(self.lines(run)["batch_url"], reverse("batch_log", args=["t-1"]))

    def test_no_batch_link_without_a_batch_log(self):
        run = self.activity(status="COMPLETED", task_id="dispatch-task", log_lines=[])
        self.assertIsNone(self.lines(run)["batch_url"])

    def test_requires_admin_login(self):
        run = self.activity(status="COMPLETED", log_lines=[LINE])
        self.client.logout()
        response = self.client.get(reverse("activity_log_lines", args=[run.id]))
        self.assertEqual(response.status_code, 302)


class MonitoringPageTests(RunLogViewTestCase):
    def test_runs_get_a_log_toggle_and_skips_do_not(self):
        run = self.activity(status="COMPLETED", success=True, log_lines=[LINE])
        self.activity(status="SKIPPED", success=True)

        response = self.client.get(reverse("station_link_monitoring", args=[self.link.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("activity_log_lines", args=[run.id]))
        self.assertContains(response, "button-secondary run-log-toggle", count=1)
        # The listing does not carry the lines themselves
        self.assertNotContains(response, "decoding file")


class BatchLogPageTests(RunLogViewTestCase):
    def test_renders_the_batch_lines_and_its_station_runs(self):
        IngestionBatchLog.objects.create(
            task_id="t-1", time=dj_timezone.now(),
            network_connection=self.link.network_connection, log_lines=[LINE],
        )
        self.activity(status="COMPLETED", success=True, task_id="t-1", message="Processed 6 records.")

        response = self.client.get(reverse("batch_log", args=["t-1"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "decoding file")  # in the json_script payload
        self.assertContains(response, "Processed 6 records.")
        self.assertContains(response, reverse("station_link_monitoring", args=[self.link.id]))

    def test_unknown_task_id_is_404(self):
        response = self.client.get(reverse("batch_log", args=["nope"]))
        self.assertEqual(response.status_code, 404)
