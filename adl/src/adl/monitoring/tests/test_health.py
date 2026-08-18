"""
Seam-1 tests for the ingestion diagnostic evaluator: set up ordinary domain
rows — a connection, station links, a heartbeat, schedule entries, held
locks — then assert the resulting checklist and stored verdict. Broker
interaction is substituted at its one seam (an IngestionQueueHealth value);
no test asserts against a live broker.
"""

from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone as dj_tz
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from adl.core.broker import (
    IngestionQueueHealth,
    RunningIngestionTask,
    UnsupportedSignal,
)
from adl.core.models import NetworkConnectionHeartbeat
from adl.core.tasks import INGESTION_TASK_NAME, ingest_station_lock_key
from adl.core.tests.factories import (
    NetworkConnectionFactory,
    ObservationRecordFactory,
    StationLinkFactory,
)
from adl.monitoring.constants import (
    LAYER_DATA,
    LAYER_LOCKS,
    LAYER_NETWORK,
    LAYER_SCHEDULER,
    LAYER_SOURCE,
    LAYER_WORKER,
    PROVENANCE_INTERNAL,
    PROVENANCE_LOG_CLASSIFICATION,
    PROVENANCE_PROBE,
    CheckState,
)
from adl.monitoring.health import (
    configuration_drift,
    evaluate_connection_health,
    station_link_drifted,
    store_connection_health,
)
from adl.monitoring.models import (
    NetworkConnectionHealth,
    NetworkConnectionHealthTransition,
)

UNKNOWN_BROKER = IngestionQueueHealth(
    queue_depth=None, worker_consuming=None, running_tasks=None
)

HEALTHY_BROKER = IngestionQueueHealth(
    queue_depth=0, worker_consuming=True, running_tasks=()
)


class HealthEvaluatorTestCase(TestCase):
    def setUp(self):
        self.link = StationLinkFactory()
        self.connection = self.link.network_connection

    def make_schedule_entry(self, connection=None, last_run_at=None, enabled=True,
                            every=None, name_suffix=""):
        connection = connection or self.connection
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=every or connection.interval, period=IntervalSchedule.MINUTES
        )
        return PeriodicTask.objects.create(
            name=f"ingest-{connection.id}{name_suffix}",
            task=INGESTION_TASK_NAME,
            args=f"[{connection.id}]",
            interval=schedule,
            enabled=enabled,
            last_run_at=last_run_at,
        )

    def stamp_heartbeat(self, last_run_at=None):
        return NetworkConnectionHeartbeat.objects.create(
            connection=self.connection,
            last_run_at=last_run_at or dj_tz.now(),
        )

    def make_healthy(self):
        """A connection every internal check passes on."""
        self.make_schedule_entry(last_run_at=dj_tz.now())
        self.stamp_heartbeat()

    def evaluate(self, queue_health=HEALTHY_BROKER):
        return evaluate_connection_health(self.connection, queue_health=queue_health)

    def check(self, checklist, check_id):
        matches = [c for c in checklist.checks if c.id == check_id]
        self.assertEqual(len(matches), 1, f"expected exactly one check {check_id!r}")
        return matches[0]


# One evidence slot per external layer
PROBE_CHECK_IDS = ("network_path", "source_check")


class HealthyConnectionTests(HealthEvaluatorTestCase):
    def test_healthy_connection_reports_ok_with_no_failing_layer(self):
        self.make_healthy()

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertIsNone(checklist.first_failing_layer)
        for check in checklist.checks:
            if check.id in PROBE_CHECK_IDS:
                # The stub plugin implements no source-check contract, so the
                # external layers report UNSUPPORTED — never a fault
                self.assertEqual(check.state, CheckState.UNSUPPORTED, check.id)
            else:
                self.assertEqual(check.state, CheckState.OK, check.id)


class DisabledConnectionTests(HealthEvaluatorTestCase):
    def test_disabled_connection_reports_disabled_and_skips_the_ladder(self):
        self.connection.plugin_processing_enabled = False
        self.connection.save()
        self.make_healthy()

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.DISABLED)
        self.assertIsNone(checklist.first_failing_layer)
        self.assertEqual(checklist.precondition[0].state, CheckState.DISABLED)
        for check in checklist.checks:
            self.assertEqual(check.state, CheckState.SKIPPED, check.id)

    def test_disabled_connection_never_dials_the_broker(self):
        self.connection.plugin_processing_enabled = False
        self.connection.save()

        with patch("adl.monitoring.health.get_ingestion_queue_health") as mock_broker:
            evaluate_connection_health(self.connection)

        mock_broker.assert_not_called()


class SchedulerLayerTests(HealthEvaluatorTestCase):
    def test_missing_schedule_entry_fails_scheduler_and_skips_everything_below(self):
        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_SCHEDULER)
        self.assertEqual(checklist.headline_check_id, "schedule_entry")
        below = [c for c in checklist.checks if c.id != "schedule_entry"]
        for check in below:
            self.assertEqual(check.state, CheckState.SKIPPED, check.id)

    def test_scheduler_failure_never_dials_the_broker(self):
        with patch("adl.monitoring.health.get_ingestion_queue_health") as mock_broker:
            evaluate_connection_health(self.connection)

        mock_broker.assert_not_called()

    def test_disabled_schedule_entry_fails_scheduler(self):
        self.make_schedule_entry(enabled=False, last_run_at=dj_tz.now())
        self.stamp_heartbeat()

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_SCHEDULER)
        self.assertEqual(checklist.headline_check_id, "schedule_enabled")

    def test_beat_never_fired_fails_scheduler(self):
        self.make_schedule_entry(last_run_at=None)
        self.stamp_heartbeat()

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_SCHEDULER)
        self.assertEqual(checklist.headline_check_id, "beat_tick")

    def test_beat_stopped_fails_scheduler(self):
        # 3x the 15-minute interval ago is beyond the 2x overdue threshold
        self.make_schedule_entry(last_run_at=dj_tz.now() - timedelta(minutes=45))
        self.stamp_heartbeat()

        checklist = self.evaluate()

        self.assertEqual(checklist.first_failing_layer, LAYER_SCHEDULER)
        self.assertEqual(checklist.headline_check_id, "beat_tick")


class AdvisoryFindingTests(HealthEvaluatorTestCase):
    def test_schedule_interval_drift_warns_but_never_seizes_the_headline(self):
        self.make_schedule_entry(last_run_at=dj_tz.now(), every=99)
        self.stamp_heartbeat()

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertIsNone(checklist.first_failing_layer)
        self.assertEqual(self.check(checklist, "schedule_interval").state, CheckState.WARNING)

    def test_duplicate_schedule_entries_warn_but_never_seize_the_headline(self):
        self.make_schedule_entry(last_run_at=dj_tz.now())
        self.make_schedule_entry(last_run_at=dj_tz.now(), name_suffix="-dup")
        self.stamp_heartbeat()

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertEqual(self.check(checklist, "schedule_duplicated").state, CheckState.WARNING)


class WorkerLayerTests(HealthEvaluatorTestCase):
    def test_beat_recent_and_heartbeat_stale_hands_the_failure_to_the_worker_layer(self):
        self.make_schedule_entry(last_run_at=dj_tz.now())
        # No heartbeat at all: beat says yes, the worker said nothing

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_WORKER)
        self.assertEqual(checklist.headline_check_id, "tick_consumed")
        # The scheduler layer is not blamed
        for check in checklist.checks_for_layer(LAYER_SCHEDULER):
            self.assertNotEqual(check.state, CheckState.FAILED, check.id)

    def test_stale_heartbeat_behind_a_recent_beat_also_lands_on_the_worker_layer(self):
        self.make_schedule_entry(last_run_at=dj_tz.now())
        self.stamp_heartbeat(last_run_at=dj_tz.now() - timedelta(minutes=45))

        checklist = self.evaluate()

        self.assertEqual(checklist.first_failing_layer, LAYER_WORKER)
        self.assertEqual(checklist.headline_check_id, "tick_consumed")

    def test_no_worker_consuming_fails_the_worker_layer(self):
        self.make_healthy()
        queue_health = IngestionQueueHealth(
            queue_depth=3, worker_consuming=False, running_tasks=()
        )

        checklist = self.evaluate(queue_health)

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_WORKER)
        self.assertEqual(checklist.headline_check_id, "worker_consuming")
        self.assertEqual(self.check(checklist, "tick_consumed").state, CheckState.SKIPPED)

    def test_unanswering_broker_reports_unknown_not_down(self):
        self.make_healthy()

        checklist = self.evaluate(UNKNOWN_BROKER)

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertIsNone(checklist.first_failing_layer)
        for check_id in ("worker_consuming", "queue_depth", "running_tasks"):
            check = self.check(checklist, check_id)
            self.assertEqual(check.state, CheckState.WARNING, check_id)
            self.assertFalse(check.blocking, check_id)

    def test_stuck_ingestion_task_fails_the_worker_layer(self):
        self.make_healthy()
        stuck = RunningIngestionTask(
            task_id="abc",
            name="adl.core.tasks.process_station_link_batch",
            args=(self.connection.id, (self.link.id,)),
            # over 3x the 15-minute interval
            age_seconds=50 * 60,
        )
        queue_health = IngestionQueueHealth(
            queue_depth=0, worker_consuming=True, running_tasks=(stuck,)
        )

        checklist = self.evaluate(queue_health)

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_WORKER)
        self.assertEqual(checklist.headline_check_id, "running_tasks")

    def test_another_connections_running_task_is_not_ours(self):
        self.make_healthy()
        other = RunningIngestionTask(
            task_id="abc",
            name="adl.core.tasks.process_station_link_batch",
            args=(self.connection.id + 1000, (999,)),
            age_seconds=50 * 60,
        )
        queue_health = IngestionQueueHealth(
            queue_depth=0, worker_consuming=True, running_tasks=(other,)
        )

        checklist = self.evaluate(queue_health)

        self.assertEqual(checklist.status, CheckState.OK)


class LocksLayerTests(HealthEvaluatorTestCase):
    def hold_lock(self, station_link):
        key = ingest_station_lock_key(station_link.id)
        cache.set(key, "locked", timeout=300)
        self.addCleanup(cache.delete, key)

    def test_stale_lock_on_some_stations_warns_with_locks_as_the_failing_layer(self):
        StationLinkFactory(network_connection=self.connection)
        self.make_healthy()
        self.hold_lock(self.link)

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.WARNING)
        self.assertEqual(checklist.first_failing_layer, LAYER_LOCKS)
        self.assertIn("1 of 2", checklist.headline_message)

    def test_stale_locks_on_all_stations_fail_the_locks_layer(self):
        self.make_healthy()
        self.hold_lock(self.link)

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_LOCKS)

    def test_lock_backed_by_a_running_batch_is_healthy(self):
        self.make_healthy()
        self.hold_lock(self.link)
        running = RunningIngestionTask(
            task_id="abc",
            name="adl.core.tasks.process_station_link_batch",
            args=(self.connection.id, (self.link.id,)),
            age_seconds=30,
        )
        queue_health = IngestionQueueHealth(
            queue_depth=0, worker_consuming=True, running_tasks=(running,)
        )

        checklist = self.evaluate(queue_health)

        self.assertEqual(checklist.status, CheckState.OK)

    def test_held_lock_with_unanswering_broker_is_unknown_not_stale(self):
        self.make_healthy()
        self.hold_lock(self.link)

        checklist = self.evaluate(UNKNOWN_BROKER)

        self.assertEqual(checklist.status, CheckState.OK)
        check = self.check(checklist, "station_locks")
        self.assertEqual(check.state, CheckState.WARNING)
        self.assertFalse(check.blocking)


class ExternalLayerTestCase(HealthEvaluatorTestCase):
    """Shared fixtures for the external layers 4-5: stored probe rows and
    terminal activity-log rows, the two producers their evidence slots
    resolve between."""

    def probe_row(self, check_id, status, age=None, layer="network",
                  station_link=None, message="probe message", category=None):
        from adl.monitoring.models import SourceProbeResult

        return SourceProbeResult.objects.create(
            connection=self.connection,
            station_link=station_link,
            check_id=check_id,
            layer=layer,
            status=status,
            category=category,
            message=message,
            at=dj_tz.now() - (age or timedelta(0)),
        )

    def log_row(self, age=None, station_link=None, status=None, success=True,
                message="", sources_count=None, error_category=None,
                error_layer=None):
        from adl.monitoring.models import StationLinkActivityLog

        if status is None:
            status = (StationLinkActivityLog.ActivityStatus.COMPLETED
                      if success else StationLinkActivityLog.ActivityStatus.FAILED)
        return StationLinkActivityLog.objects.create(
            station_link=station_link or self.link,
            direction="pull",
            status=status,
            success=success,
            message=message,
            sources_count=sources_count,
            error_category=error_category,
            error_layer=error_layer,
            time=dj_tz.now() - (age or timedelta(0)),
        )

    def with_supported_contract(self):
        """A connection whose plugin implements the whole contract, without
        needing a polymorphic subclass: the endpoint via an instance
        attribute (the evaluator calls it), check_source via its no-I/O
        implemented-ness seam."""
        self.connection.get_source_endpoint = lambda: ("ftp.example.org", 21)
        patcher = patch(
            "adl.monitoring.health.connection_implements_check_source",
            return_value=True,
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class SourceProbeLayerTests(ExternalLayerTestCase):
    """The on-demand probe as slot evidence: the evaluator only ever reads
    stored probe rows, rests at STALE (or UNSUPPORTED where the plugin has
    no contract), and STALE never reaches the headline."""

    def test_unsupported_contract_reports_unsupported_never_stale(self):
        self.make_healthy()

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            check = self.check(checklist, check_id)
            self.assertEqual(check.state, CheckState.UNSUPPORTED, check_id)
            self.assertFalse(check.blocking, check_id)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_supported_but_never_probed_rests_at_stale_excluded_from_headline(self):
        self.make_healthy()
        self.with_supported_contract()

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            self.assertEqual(self.check(checklist, check_id).state,
                             CheckState.STALE, check_id)
        self.assertEqual(checklist.status, CheckState.OK)
        self.assertIsNone(checklist.first_failing_layer)

    def test_result_older_than_fifteen_minutes_is_stale(self):
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "FAILED", age=timedelta(minutes=16))

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "network_path").state, CheckState.STALE)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_result_inside_fifteen_minutes_is_fresh(self):
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "OK", age=timedelta(minutes=14))

        checklist = self.evaluate()

        check = self.check(checklist, "network_path")
        self.assertEqual(check.state, CheckState.OK)
        # The rendered message carries the result's age and origin
        self.assertIn("on-demand probe", check.message)
        self.assertEqual(check.provenance, PROVENANCE_PROBE)

    def test_fresh_failed_dns_leads_the_headline_and_skips_below(self):
        from adl.monitoring.constants import LAYER_NETWORK

        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "FAILED", age=timedelta(minutes=1),
                       category="DNS_FAILURE")

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_NETWORK)
        self.assertEqual(checklist.headline_check_id, "network_path")
        for check_id in ("source_check", "data_freshness"):
            self.assertEqual(self.check(checklist, check_id).state,
                             CheckState.SKIPPED, check_id)

    def test_fresh_failed_source_check_leads_with_the_source_layer(self):
        from adl.monitoring.constants import LAYER_SOURCE

        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "OK", age=timedelta(minutes=1))
        self.probe_row("tcp_connect", "OK", age=timedelta(minutes=1))
        self.probe_row("source_check", "FAILED", age=timedelta(minutes=1),
                       layer="source", category="AUTH_FAILED")

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_SOURCE)
        self.assertEqual(checklist.headline_check_id, "source_check")

    def test_station_scope_rows_are_excluded_by_construction(self):
        # An operator-chosen station sample must never move the connection's
        # verdict — the fresh FAILED row below carries a station link and is
        # invisible to the evaluator
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "FAILED", age=timedelta(minutes=1),
                       station_link=self.link)

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "network_path").state, CheckState.STALE)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_station_scope_source_check_cannot_move_the_connection_verdict(self):
        # The on-demand station check persists against the same model with
        # its station-link FK set; a fresh FAILED station row must leave
        # layer 5 at its resting STALE state, not seize the headline
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("station_source_check", "FAILED", age=timedelta(minutes=1),
                       layer="source", category="AUTH_FAILED",
                       station_link=self.link)

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "source_check").state, CheckState.STALE)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_malformed_probe_row_reports_unsupported_not_a_verdict(self):
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("source_check", "MALFORMED", age=timedelta(minutes=1),
                       layer="source")

        checklist = self.evaluate()

        check = self.check(checklist, "source_check")
        self.assertEqual(check.state, CheckState.UNSUPPORTED)
        self.assertFalse(check.blocking)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_probe_layers_are_skipped_below_an_internal_failure(self):
        self.with_supported_contract()
        # No schedule entry: the scheduler fails first
        checklist = self.evaluate()

        self.assertEqual(checklist.first_failing_layer, LAYER_SCHEDULER)
        for check_id in PROBE_CHECK_IDS:
            self.assertEqual(self.check(checklist, check_id).state,
                             CheckState.SKIPPED, check_id)


class LogEvidenceTests(ExternalLayerTestCase):
    """What already happened counts as evidence about layers 4-5: successes
    are OK evidence, write-time-stamped failures are trusted, unstamped
    failures fall back to the read-time text rules — and rows that merely
    look like evidence (SKIPPED, drifted links) are excluded."""

    def test_successful_run_contributes_ok_evidence_to_both_external_layers(self):
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), sources_count=3)

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            check = self.check(checklist, check_id)
            self.assertEqual(check.state, CheckState.OK, check_id)
            self.assertEqual(check.provenance, PROVENANCE_INTERNAL, check_id)

    def test_log_evidence_needs_no_probe_contract(self):
        # The stub plugin implements no source-check contract, yet a real
        # run is still evidence — the ratchet can go green after a fix
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), sources_count=3)

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "network_path").state, CheckState.OK)

    def test_zero_sources_success_is_layer_four_ok_but_no_layer_five_ok(self):
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), sources_count=0)

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "network_path").state, CheckState.OK)
        # The one thing the run did not do is transfer bytes
        self.assertNotEqual(self.check(checklist, "source_check").state, CheckState.OK)

    def test_skipped_rows_are_not_evidence(self):
        # A lock collision must not manufacture fake layer-4 OK evidence
        from adl.monitoring.models import StationLinkActivityLog

        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), success=False,
                     status=StationLinkActivityLog.ActivityStatus.SKIPPED)

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            self.assertNotEqual(self.check(checklist, check_id).state,
                                CheckState.OK, check_id)

    def test_write_time_stamped_failure_is_trusted_and_renders_normalised_text(self):
        self.make_healthy()
        raw = "530 Login incorrect: password 'hunter2'"
        self.log_row(age=timedelta(minutes=5), success=False, message=raw,
                     error_category="AUTH_FAILED", error_layer=5)

        checklist = self.evaluate()

        check = self.check(checklist, "source_check")
        self.assertEqual(check.state, CheckState.FAILED)
        self.assertEqual(check.provenance, PROVENANCE_INTERNAL)
        self.assertNotIn("hunter2", check.message)
        self.assertEqual(checklist.first_failing_layer, LAYER_SOURCE)

    def test_unstamped_failure_falls_back_to_read_time_classification(self):
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), success=False,
                     message="[Errno -2] Name or service not known")

        checklist = self.evaluate()

        check = self.check(checklist, "network_path")
        self.assertEqual(check.state, CheckState.FAILED)
        self.assertEqual(check.provenance, PROVENANCE_LOG_CLASSIFICATION)
        self.assertNotIn("Errno", check.message)
        self.assertEqual(checklist.first_failing_layer, LAYER_NETWORK)

    def test_ambiguous_failure_text_yields_no_classification(self):
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), success=False,
                     message="Something went wrong")

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            self.assertEqual(self.check(checklist, check_id).state,
                             CheckState.UNSUPPORTED, check_id)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_rule_without_a_layer_creates_no_external_slot(self):
        # "timed out" cannot tell a connect timeout from a read timeout;
        # the rule claims the category but declines the layer, so the row
        # stays layer-6 detail
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), success=False,
                     message="Connection timed out")

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            self.assertNotEqual(self.check(checklist, check_id).state,
                                CheckState.FAILED, check_id)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_log_older_than_twice_the_interval_is_not_evidence(self):
        # Interval is 15 minutes, so the log freshness window is 30
        self.make_healthy()
        self.log_row(age=timedelta(minutes=35), sources_count=3)

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            self.assertNotEqual(self.check(checklist, check_id).state,
                                CheckState.OK, check_id)

    def test_drifted_station_link_is_excluded_from_layer_five_evidence_only(self):
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), success=False,
                     message="530 Login incorrect",
                     error_category="AUTH_FAILED", error_layer=5)

        with patch("adl.monitoring.health.station_link_drifted", return_value=True):
            checklist = self.evaluate()

        # Our own configuration fault is not attributed to the partner
        self.assertNotEqual(self.check(checklist, "source_check").state,
                            CheckState.FAILED)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_drifted_station_link_success_still_feeds_layer_four(self):
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), sources_count=3)

        with patch("adl.monitoring.health.station_link_drifted", return_value=True):
            checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "network_path").state, CheckState.OK)
        self.assertNotEqual(self.check(checklist, "source_check").state, CheckState.OK)


class NoExternalSourceTests(ExternalLayerTestCase):
    """A connection whose plugin declares no upstream source: layers 4-5
    have no subject, so they report NOT_APPLICABLE before any evidence is
    gathered — never a green verdict manufactured from a run that touched
    no network — and the ladder descends to layer 6."""

    def setUp(self):
        super().setUp()
        # The declaration a plugin makes on its NetworkConnection subclass
        self.connection.has_external_source = False

    def observe(self, station_link, age):
        return ObservationRecordFactory(
            station=station_link.station,
            connection=self.connection,
            time=dj_tz.now() - age,
        )

    def test_both_external_layers_report_not_applicable(self):
        self.make_healthy()

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            check = self.check(checklist, check_id)
            self.assertEqual(check.state, CheckState.NOT_APPLICABLE, check_id)
            self.assertFalse(check.blocking, check_id)
            self.assertIn("submitted to ADL directly", str(check.message))

    def test_a_successful_run_no_longer_fabricates_a_green_verdict(self):
        # The bug: every successful run of an internal-source plugin minted
        # a layer-4 and a layer-5 OK, each asserting a hop that never happened
        self.make_healthy()
        self.log_row(age=timedelta(minutes=5), sources_count=3)

        checklist = self.evaluate()

        for check_id in PROBE_CHECK_IDS:
            check = self.check(checklist, check_id)
            self.assertEqual(check.state, CheckState.NOT_APPLICABLE, check_id)
            self.assertIsNone(check.provenance, check_id)

    def test_a_fresh_probe_row_is_not_gathered_either(self):
        # Nothing is collected before the declaration is consulted, so even
        # a stored probe row cannot resurrect the layer
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "OK", age=timedelta(minutes=1))

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "network_path").state,
                         CheckState.NOT_APPLICABLE)

    def test_not_applicable_never_seizes_the_headline(self):
        self.make_healthy()
        self.observe(self.link, timedelta(minutes=10))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertIsNone(checklist.first_failing_layer)

    def test_the_ladder_descends_to_the_data_layer(self):
        # The consequence that mattered: layers 4-5 were blocking, so an
        # operator was never walked down to where the real fault lives
        self.make_healthy()
        self.observe(self.link, timedelta(hours=6))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)
        self.assertEqual(checklist.headline_check_id, "data_freshness")

    def test_not_applicable_renders_grey(self):
        self.make_healthy()

        checklist = self.evaluate()

        self.assertFalse(self.check(checklist, "network_path").coloured)

    def test_the_probe_buttons_disappear(self):
        # Withdrawn even from a plugin that happens to implement the whole
        # contract: there is no host to dial, so nothing may offer to
        with patch("adl.core.source_checks.connection_implements_check_source",
                   return_value=True), \
             patch("adl.core.source_checks."
                   "station_link_implements_check_station_source",
                   return_value=True):
            self.assertFalse(self.connection.source_probe_supported)
            self.assertFalse(self.link.station_source_check_supported)

            # The same plugin with an external source keeps both buttons —
            # the declaration is what withdrew them, not the patches
            self.connection.has_external_source = True
            self.assertTrue(self.connection.source_probe_supported)
            self.assertTrue(self.link.station_source_check_supported)


class SlotResolutionTests(ExternalLayerTestCase):
    """One slot per external layer: freshest observation wins, ties go to
    the probe, and the superseded observation is retained with its
    provenance."""

    def test_fresher_log_beats_an_older_probe_and_retains_it(self):
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "FAILED", age=timedelta(minutes=10),
                       category="DNS_FAILURE")
        self.log_row(age=timedelta(minutes=2), sources_count=3)

        checklist = self.evaluate()

        check = self.check(checklist, "network_path")
        self.assertEqual(check.state, CheckState.OK)
        self.assertEqual(check.provenance, PROVENANCE_INTERNAL)
        self.assertIsNotNone(check.superseded)
        self.assertEqual(check.superseded.provenance, PROVENANCE_PROBE)
        self.assertEqual(check.superseded.state, CheckState.FAILED)
        self.assertIsNotNone(check.superseded_message)

    def test_fresher_probe_beats_an_older_log(self):
        self.make_healthy()
        self.with_supported_contract()
        self.log_row(age=timedelta(minutes=10), success=False,
                     message="[Errno 111] Connection refused")
        self.probe_row("dns_resolution", "OK", age=timedelta(minutes=2))
        self.probe_row("tcp_connect", "OK", age=timedelta(minutes=2))

        checklist = self.evaluate()

        check = self.check(checklist, "network_path")
        self.assertEqual(check.state, CheckState.OK)
        self.assertEqual(check.provenance, PROVENANCE_PROBE)
        self.assertEqual(check.superseded.provenance, PROVENANCE_LOG_CLASSIFICATION)

    def test_a_tie_resolves_to_the_probe(self):
        self.make_healthy()
        self.with_supported_contract()
        at = dj_tz.now() - timedelta(minutes=5)
        row = self.probe_row("dns_resolution", "OK")
        row.at = at
        row.save()
        log = self.log_row(success=False, message="Connection refused")
        log.time = at
        log.save()

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "network_path").provenance, PROVENANCE_PROBE)


class SourcesCountTests(ExternalLayerTestCase):
    """The sources count qualifies layer 5 only when layer 6 is already
    red — no standalone alarm, and silence (NULL) is never read as fault.
    The window is layer 6's own freshness-error limit (12x the 15-minute
    interval = 180 minutes)."""

    def stale_data(self):
        ObservationRecordFactory(
            station=self.link.station,
            connection=self.connection,
            time=dj_tz.now() - timedelta(hours=6),
        )

    def test_data_stale_and_every_terminal_log_at_zero_fails_layer_five(self):
        self.make_healthy()
        self.stale_data()
        # Old enough to be outside the 30-minute plain-evidence window, so
        # only the sources-count rule speaks for layer 5
        self.log_row(age=timedelta(minutes=100), sources_count=0)
        self.log_row(age=timedelta(minutes=60), sources_count=0)

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_SOURCE)
        check = self.check(checklist, "source_check")
        self.assertEqual(check.state, CheckState.FAILED)
        self.assertEqual(check.provenance, PROVENANCE_INTERNAL)

    def test_layer_six_still_reports_its_observed_verdict_below_the_sources_verdict(self):
        self.make_healthy()
        self.stale_data()
        self.log_row(age=timedelta(minutes=60), sources_count=0)

        checklist = self.evaluate()

        # The data row triggered the layer-5 verdict; hiding it as SKIPPED
        # would misreport a genuinely observed fact
        self.assertEqual(self.check(checklist, "data_freshness").state,
                         CheckState.FAILED)

    def test_any_non_zero_count_reports_layer_five_ok_and_anchors_to_data(self):
        self.make_healthy()
        self.stale_data()
        self.log_row(age=timedelta(minutes=100), sources_count=0)
        self.log_row(age=timedelta(minutes=60), sources_count=4)

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "source_check").state, CheckState.OK)
        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)

    def test_with_data_green_the_sources_count_changes_nothing(self):
        # The date-rollover false alarm, dissolved: zero sources on a
        # healthy connection raises no alarm
        self.make_healthy()
        ObservationRecordFactory(
            station=self.link.station, connection=self.connection,
            time=dj_tz.now() - timedelta(minutes=10),
        )
        self.log_row(age=timedelta(minutes=60), sources_count=0)

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertNotEqual(self.check(checklist, "source_check").state,
                            CheckState.FAILED)

    def test_partial_staleness_is_not_red_so_the_count_stays_silent(self):
        # One of two stations stale rolls layer 6 up to WARNING, not
        # FAILED — the count qualifies layer 5 only when layer 6 is red
        fresh_link = StationLinkFactory(network_connection=self.connection)
        self.make_healthy()
        self.stale_data()
        ObservationRecordFactory(
            station=fresh_link.station, connection=self.connection,
            time=dj_tz.now() - timedelta(minutes=10),
        )
        self.log_row(age=timedelta(minutes=60), sources_count=0)
        self.log_row(age=timedelta(minutes=60), station_link=fresh_link,
                     sources_count=0)

        checklist = self.evaluate()

        self.assertNotEqual(self.check(checklist, "source_check").state,
                            CheckState.FAILED)
        self.assertEqual(checklist.status, CheckState.WARNING)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)

    def test_a_null_count_disqualifies_the_zero_sources_claim(self):
        # NULL means "did not look" — not every terminal log is at 0, so
        # the diagnostic declines rather than reading silence as fault
        self.make_healthy()
        self.stale_data()
        self.log_row(age=timedelta(minutes=100), sources_count=0)
        self.log_row(age=timedelta(minutes=60), sources_count=None)

        checklist = self.evaluate()

        self.assertNotEqual(self.check(checklist, "source_check").state,
                            CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)

    def test_drifted_links_are_excluded_from_the_sources_count(self):
        # The only zero-sources logs belong to a drifted link; a fault in
        # our configuration must not indict the partner's server
        self.make_healthy()
        self.stale_data()
        self.log_row(age=timedelta(minutes=60), sources_count=0)

        with patch("adl.monitoring.health.station_link_drifted", return_value=True):
            checklist = self.evaluate()

        self.assertNotEqual(self.check(checklist, "source_check").state,
                            CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)


class StationLinkDriftedTests(TestCase):
    """The drift predicate is full_clean() and nothing more; only
    ValidationError means drift — a crash in a validator is not evidence
    the configuration is wrong."""

    def test_a_valid_stored_link_is_not_drifted(self):
        self.assertFalse(station_link_drifted(StationLinkFactory()))

    def test_a_link_failing_validation_is_drifted(self):
        from adl.core.models import StationLink

        # Required fields missing: full_clean raises ValidationError
        self.assertTrue(station_link_drifted(StationLink()))

    def test_a_crashing_validator_makes_no_drift_claim(self):
        class ExplodingLink:
            id = 99

            def full_clean(self, validate_unique=True):
                raise RuntimeError("boom")

        self.assertFalse(station_link_drifted(ExplodingLink()))

    def test_drift_names_the_offending_fields_from_message_dict(self):
        from adl.core.models import StationLink

        drift = configuration_drift(StationLink())

        self.assertTrue(drift.drifted)
        self.assertTrue(drift.evaluated)
        self.assertIn("station", drift.fields)
        self.assertTrue(any("station" in message for message in drift.messages))


class ConnectionConfigurationDriftTests(HealthEvaluatorTestCase):
    """Connection-scope drift: full_clean(validate_unique=False) and nothing
    more. A drifted connection is MISCONFIGURED in the precondition band and
    short-circuits every layer below; DISABLED still outranks it; a plugin
    with no clean() override reports UNSUPPORTED, never clean."""

    def configuration_check(self, checklist):
        matches = [c for c in checklist.precondition if c.id == "configuration_valid"]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_misconfigured_connection_short_circuits_the_ladder(self):
        self.make_healthy()
        # A stored value the admin form would now reject: below the
        # MinValueValidator(1) bound on the interval
        self.connection.plugin_processing_interval = 0

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.MISCONFIGURED)
        self.assertIsNone(checklist.first_failing_layer)
        self.assertEqual(checklist.headline_check_id, "configuration_valid")
        self.assertIn("plugin_processing_interval", checklist.headline_message)
        for check in checklist.checks:
            self.assertEqual(check.state, CheckState.SKIPPED, check.id)

    def test_misconfigured_row_names_the_field_in_the_precondition_band(self):
        self.make_healthy()
        self.connection.plugin_processing_interval = 0

        check = self.configuration_check(self.evaluate())

        self.assertEqual(check.state, CheckState.MISCONFIGURED)
        self.assertIn("plugin_processing_interval", check.message)

    def test_misconfigured_connection_never_dials_the_broker(self):
        self.make_healthy()
        self.connection.plugin_processing_interval = 0

        with patch("adl.monitoring.health.get_ingestion_queue_health") as mock_broker:
            evaluate_connection_health(self.connection)

        mock_broker.assert_not_called()

    def test_disabled_outranks_misconfigured(self):
        self.connection.plugin_processing_enabled = False
        self.connection.plugin_processing_interval = 0

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.DISABLED)
        self.assertEqual(len(checklist.precondition), 1)

    def test_plugin_without_clean_override_reports_unsupported_not_clean(self):
        self.make_healthy()

        checklist = self.evaluate()

        check = self.configuration_check(checklist)
        # Silence must not read as validation — but it is advisory, so the
        # connection's verdict is untouched
        self.assertEqual(check.state, CheckState.UNSUPPORTED)
        self.assertFalse(check.blocking)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_plugin_with_a_passing_clean_override_reports_ok(self):
        self.make_healthy()

        with patch("adl.monitoring.health.connection_declares_validation_rules",
                   return_value=True):
            check = self.configuration_check(self.evaluate())

        self.assertEqual(check.state, CheckState.OK)

    def test_a_crashing_validator_makes_no_drift_claim(self):
        from adl.core.models import NetworkConnection

        self.make_healthy()

        with patch.object(NetworkConnection, "full_clean",
                          side_effect=RuntimeError("boom")):
            checklist = self.evaluate()

        check = self.configuration_check(checklist)
        self.assertEqual(check.state, CheckState.UNSUPPORTED)
        self.assertFalse(check.blocking)
        # Not evidence of drift: the ladder is still evaluated and the
        # connection's verdict is whatever the ladder says
        self.assertEqual(checklist.status, CheckState.OK)

    def test_every_offending_field_is_named(self):
        # Ordinary field validation catches drift with no clean() override
        # needed — and a multi-field drift names each field
        self.make_healthy()
        self.connection.plugin_processing_interval = 0
        self.connection.ingest_timeout_seconds = 5

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.MISCONFIGURED)
        self.assertIn("plugin_processing_interval", checklist.headline_message)
        self.assertIn("ingest_timeout_seconds", checklist.headline_message)

    def test_one_drifted_station_link_does_not_turn_a_healthy_connection_red(self):
        self.make_healthy()

        with patch("adl.monitoring.health.station_link_drifted", return_value=True):
            checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertNotEqual(checklist.status, CheckState.MISCONFIGURED)

    def test_misconfigured_verdict_is_stored_with_null_layer(self):
        self.make_healthy()
        self.connection.plugin_processing_interval = 0

        checklist = self.evaluate()
        health = store_connection_health(self.connection, checklist)

        self.assertEqual(health.status, CheckState.MISCONFIGURED)
        self.assertIsNone(health.first_failing_layer)
        transition = NetworkConnectionHealthTransition.objects.get()
        self.assertEqual(transition.to_status, CheckState.MISCONFIGURED)


class StoredVerdictTests(HealthEvaluatorTestCase):
    def store(self, queue_health=HEALTHY_BROKER, now=None):
        checklist = evaluate_connection_health(
            self.connection, queue_health=queue_health, now=now
        )
        return store_connection_health(self.connection, checklist, now=now)

    def test_first_evaluation_creates_one_row_and_a_birth_transition(self):
        self.make_healthy()

        health = self.store()

        self.assertEqual(NetworkConnectionHealth.objects.count(), 1)
        self.assertEqual(health.status, CheckState.OK)
        self.assertIsNone(health.first_failing_layer)
        transition = NetworkConnectionHealthTransition.objects.get()
        self.assertIsNone(transition.from_status)
        self.assertEqual(transition.to_status, CheckState.OK)

    def test_disabled_connection_stores_disabled_with_null_layer(self):
        self.connection.plugin_processing_enabled = False
        self.connection.save()

        health = self.store()

        self.assertEqual(health.status, CheckState.DISABLED)
        self.assertIsNone(health.first_failing_layer)

    def test_unchanged_verdict_moves_neither_since_nor_the_transition_log(self):
        self.make_healthy()
        first = dj_tz.now() - timedelta(minutes=30)

        self.store(now=first)
        health = self.store(now=dj_tz.now())

        self.assertEqual(health.since, first)
        self.assertGreater(health.evaluated_at, first)
        self.assertEqual(NetworkConnectionHealthTransition.objects.count(), 1)

    def test_status_change_appends_a_transition_and_moves_since(self):
        self.make_healthy()
        first = dj_tz.now() - timedelta(minutes=30)
        self.store(now=first)

        # The worker fleet drops off
        broken = IngestionQueueHealth(queue_depth=0, worker_consuming=False, running_tasks=())
        later = dj_tz.now()
        health = self.store(queue_health=broken, now=later)

        self.assertEqual(health.status, CheckState.FAILED)
        self.assertEqual(health.first_failing_layer, LAYER_WORKER)
        self.assertEqual(health.since, later)
        self.assertEqual(NetworkConnectionHealthTransition.objects.count(), 2)
        latest = NetworkConnectionHealthTransition.objects.order_by("-at").first()
        self.assertEqual(latest.from_status, CheckState.OK)
        self.assertEqual(latest.to_status, CheckState.FAILED)
        self.assertEqual(latest.to_first_failing_layer, LAYER_WORKER)

    def test_category_only_change_updates_headline_but_not_since(self):
        # Two different scheduler faults: same (status, first_failing_layer),
        # different underlying check — since must not move, no row appended
        entry = self.make_schedule_entry(last_run_at=None)
        self.stamp_heartbeat()
        first = dj_tz.now() - timedelta(minutes=30)
        self.store(now=first)  # beat_tick FAILED

        entry.delete()
        health = self.store(now=dj_tz.now())  # schedule_entry FAILED

        self.assertEqual(health.status, CheckState.FAILED)
        self.assertEqual(health.first_failing_layer, LAYER_SCHEDULER)
        self.assertEqual(health.headline_check_id, "schedule_entry")
        self.assertEqual(health.since, first)
        self.assertEqual(NetworkConnectionHealthTransition.objects.count(), 1)


class DataLayerTests(HealthEvaluatorTestCase):
    """Layer 6 rolls up per-station data freshness: all stations affected
    FAILED, some WARNING, none OK — driven by the shared per-station
    status helper, never a second implementation."""

    def observe(self, station_link, age):
        return ObservationRecordFactory(
            station=station_link.station,
            connection=self.connection,
            time=dj_tz.now() - age,
        )

    def test_fresh_data_on_every_station_reports_ok(self):
        self.make_healthy()
        self.observe(self.link, timedelta(minutes=10))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertEqual(self.check(checklist, "data_freshness").state, CheckState.OK)

    def test_stale_data_on_all_stations_fails_the_data_layer(self):
        self.make_healthy()
        # Well past the error limit of 12x the 15-minute interval
        self.observe(self.link, timedelta(hours=6))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)
        self.assertEqual(checklist.headline_check_id, "data_freshness")

    def test_one_stale_station_of_two_warns_not_fails(self):
        fresh_link = StationLinkFactory(network_connection=self.connection)
        self.make_healthy()
        self.observe(self.link, timedelta(hours=6))
        self.observe(fresh_link, timedelta(minutes=10))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.WARNING)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)
        check = self.check(checklist, "data_freshness")
        self.assertEqual(check.state, CheckState.WARNING)

    def test_rendered_content_is_the_counts_with_a_station_link(self):
        StationLinkFactory(network_connection=self.connection)
        self.make_healthy()
        self.observe(self.link, timedelta(hours=6))

        checklist = self.evaluate()

        check = self.check(checklist, "data_freshness")
        self.assertIn("1 of 2", check.message)
        self.assertIsNotNone(check.link)

    def test_headline_anchors_to_data_when_layers_one_to_three_are_green(self):
        self.make_healthy()
        self.observe(self.link, timedelta(hours=6))

        checklist = self.evaluate()

        for check in checklist.checks:
            if check.layer != LAYER_DATA:
                self.assertNotEqual(check.state, CheckState.FAILED, check.id)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)

    def test_station_that_never_produced_data_is_not_reported_stale(self):
        # The day-one state on every deployment: no observations at all
        self.make_healthy()

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertEqual(self.check(checklist, "data_freshness").state, CheckState.OK)

    def test_disabled_station_links_are_excluded_from_the_roll_up(self):
        stale_link = StationLinkFactory(network_connection=self.connection, enabled=False)
        self.make_healthy()
        self.observe(self.link, timedelta(minutes=10))
        self.observe(stale_link, timedelta(hours=6))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)

    def test_data_just_inside_the_error_limit_is_not_stale(self):
        # Error limit is 12x the 15-minute interval = 180 minutes
        self.make_healthy()
        self.observe(self.link, timedelta(minutes=170))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.OK)
        self.assertEqual(self.check(checklist, "data_freshness").state, CheckState.OK)

    def test_data_just_past_the_error_limit_is_stale(self):
        self.make_healthy()
        self.observe(self.link, timedelta(minutes=190))

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)

    def test_aging_stations_are_named_in_an_ok_message(self):
        # An amber station on the monitoring panel must not read as
        # "data is current" here — the two surfaces cannot disagree
        self.make_healthy()
        self.observe(self.link, timedelta(minutes=100))  # past warning, before error

        checklist = self.evaluate()

        check = self.check(checklist, "data_freshness")
        self.assertEqual(check.state, CheckState.OK)
        self.assertIn("1 of 1", check.message)
        self.assertNotIn("current", check.message)

    def test_data_check_is_skipped_below_an_upper_failure(self):
        # No schedule entry: the scheduler fails first
        self.observe(self.link, timedelta(hours=6))

        checklist = self.evaluate()

        self.assertEqual(checklist.first_failing_layer, LAYER_SCHEDULER)
        self.assertEqual(self.check(checklist, "data_freshness").state, CheckState.SKIPPED)


def _unsupported_broker(signal, message="not the tested broker stack"):
    """A broker observation with one signal degraded by its version guard."""
    return IngestionQueueHealth(
        queue_depth=0, worker_consuming=True, running_tasks=(),
        unsupported=(UnsupportedSignal(signal, message),),
    )


class VersionGuardEvaluatorTests(HealthEvaluatorTestCase):
    """
    UNSUPPORTED from a version guard is advisory for every signal except
    worker-consuming — the signal layer 2 exists for — which reaches the
    headline as information, and pointedly does not short-circuit the
    layers below to SKIPPED.
    """

    def fresh_data(self):
        ObservationRecordFactory(
            station=self.link.station, connection=self.connection,
            time=dj_tz.now() - timedelta(minutes=10),
        )

    def test_unsupported_worker_consuming_reaches_the_headline_as_information(self):
        self.make_healthy()
        self.fresh_data()

        checklist = self.evaluate(
            queue_health=IngestionQueueHealth(
                queue_depth=0, worker_consuming=None, running_tasks=(),
                unsupported=(UnsupportedSignal(
                    "worker_consuming", "not the tested broker stack"),),
            )
        )

        self.assertEqual(checklist.status, CheckState.UNSUPPORTED)
        self.assertEqual(checklist.first_failing_layer, LAYER_WORKER)
        self.assertEqual(checklist.headline_check_id, "worker_consuming")
        check = self.check(checklist, "worker_consuming")
        self.assertEqual(check.state, CheckState.UNSUPPORTED)
        self.assertIn("not the tested broker stack", check.message)

    def test_unsupported_worker_consuming_does_not_short_circuit_layers_below(self):
        self.make_healthy()
        self.fresh_data()

        checklist = self.evaluate(
            queue_health=_unsupported_broker("worker_consuming")
        )

        # Unlike FAILED or DISABLED, information leaves everything below
        # evaluated on its own evidence
        self.assertEqual(self.check(checklist, "station_locks").state, CheckState.OK)
        self.assertEqual(self.check(checklist, "data_freshness").state, CheckState.OK)

    def test_a_real_failure_outranks_unsupported_information(self):
        self.make_healthy()
        ObservationRecordFactory(
            station=self.link.station, connection=self.connection,
            time=dj_tz.now() - timedelta(hours=6),
        )

        checklist = self.evaluate(
            queue_health=_unsupported_broker("worker_consuming")
        )

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_DATA)
        # The information stays visible on its own row
        self.assertEqual(self.check(checklist, "worker_consuming").state,
                         CheckState.UNSUPPORTED)

    def test_unsupported_queue_depth_is_advisory_and_never_leads(self):
        self.make_healthy()
        self.fresh_data()

        checklist = self.evaluate(queue_health=_unsupported_broker("queue_depth"))

        self.assertEqual(checklist.status, CheckState.OK)
        check = self.check(checklist, "queue_depth")
        self.assertEqual(check.state, CheckState.UNSUPPORTED)
        self.assertFalse(check.blocking)

    def test_out_of_range_worker_stack_degrades_running_tasks_to_unsupported(self):
        # Task ages come from time_start, which the worker stamps — so the
        # guard judges the worker's cached stack, not this process's
        self.make_schedule_entry(last_run_at=dj_tz.now())
        NetworkConnectionHeartbeat.objects.create(
            connection=self.connection, last_run_at=dj_tz.now(),
            worker_versions={"celery": "9.9.9", "kombu": "5.6.2", "redis": "8.0.1"},
        )
        self.fresh_data()

        checklist = self.evaluate()

        check = self.check(checklist, "running_tasks")
        self.assertEqual(check.state, CheckState.UNSUPPORTED)
        self.assertFalse(check.blocking)
        self.assertIn("celery 9.9.9", check.message)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_unreported_worker_stack_leaves_running_tasks_evaluated(self):
        # A heartbeat that never reported versions is "never asked", not
        # evidence of drift — the stuck-task signal must keep working
        self.make_healthy()
        self.fresh_data()

        checklist = self.evaluate()

        self.assertEqual(self.check(checklist, "running_tasks").state, CheckState.OK)

    def test_unsupported_verdict_is_persistable(self):
        self.make_healthy()
        self.fresh_data()

        checklist = evaluate_connection_health(
            self.connection,
            queue_health=IngestionQueueHealth(
                queue_depth=0, worker_consuming=None, running_tasks=(),
                unsupported=(UnsupportedSignal(
                    "worker_consuming", "not the tested broker stack"),),
            ),
        )
        health = store_connection_health(self.connection, checklist)

        self.assertEqual(health.status, CheckState.UNSUPPORTED)
        self.assertEqual(health.first_failing_layer, LAYER_WORKER)
