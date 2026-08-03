"""
The backfill migration must actually clear secrets from rows already stored.

Exercised against the live app registry rather than through the migration
executor: what is being proven is the sweep — its candidate filter runs as
real SQL, and rows with nothing to redact are left untouched.
"""

from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.utils import timezone as dj_timezone

from adl.core.tests.factories import StationLinkFactory
from adl.monitoring.models import SourceProbeResult, StationLinkActivityLog

migration = import_module("adl.monitoring.migrations.0010_redact_stored_secrets")

LEAKY = ("401 Client Error: Unauthorized for url: "
         "https://api.example.org/data?token=s3cr3t-value&station=42")
CLEAN = "Processed 12 records."


class SecretBackfillTests(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection

    def make_log(self, message):
        return StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=self.link,
            direction="pull",
            message=message,
        )

    def test_leaked_activity_log_message_is_redacted(self):
        log = self.make_log(LEAKY)

        migration.redact_stored_secrets(apps, None)

        log.refresh_from_db()
        self.assertNotIn("s3cr3t-value", log.message)
        self.assertIn("token=***", log.message)

    def test_clean_rows_are_left_exactly_as_they_were(self):
        log = self.make_log(CLEAN)

        migration.redact_stored_secrets(apps, None)

        log.refresh_from_db()
        self.assertEqual(log.message, CLEAN)

    def test_null_message_survives_the_sweep(self):
        log = self.make_log(None)

        migration.redact_stored_secrets(apps, None)

        log.refresh_from_db()
        self.assertIsNone(log.message)

    def test_probe_results_are_swept_too(self):
        probe = SourceProbeResult.objects.create(
            connection=self.connection,
            check_id="source_check",
            layer="source",
            status="FAILED",
            message=LEAKY,
            at=dj_timezone.now(),
        )

        migration.redact_stored_secrets(apps, None)

        probe.refresh_from_db()
        self.assertNotIn("s3cr3t-value", probe.message)

    def test_running_the_sweep_twice_is_a_no_op_the_second_time(self):
        log = self.make_log(LEAKY)

        migration.redact_stored_secrets(apps, None)
        log.refresh_from_db()
        once = log.message

        migration.redact_stored_secrets(apps, None)
        log.refresh_from_db()
        self.assertEqual(log.message, once)


class CandidateFilterTests(TestCase):
    """
    The SQL pre-filter must not be narrower than the redactor.

    Anything the redactor would change has to survive the filter, or the
    backfill silently skips rows the forward fix would have caught — the
    drift that a hand-retyped word list invites.
    """

    def setUp(self):
        self.link = StationLinkFactory()

    def assert_swept(self, message):
        log = StationLinkActivityLog.objects.create(
            time=dj_timezone.now(),
            station_link=self.link,
            direction="pull",
            message=message,
        )

        migration.redact_stored_secrets(apps, None)

        log.refresh_from_db()
        self.assertNotEqual(log.message, message, f"not swept: {message!r}")

    def test_every_leak_shape_the_redactor_handles_is_a_candidate(self):
        shapes = [
            "?token=abc123",
            "?tokens=abc123",
            "?api_key=abc123",
            "?API_KEY=abc123",
            "?client_secret=abc123",
            "?credentials=abc123",
            'password: "hunter2"',
            "Authorization: Bearer abcdef123456",
            "sent Token abcdef123456 upstream",
            "sent Digest abcdef123456 upstream",
            "ftp://alice:hunter2@ftp.example.org/in/",
        ]

        for shape in shapes:
            with self.subTest(shape=shape):
                self.assert_swept(shape)
