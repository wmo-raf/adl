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

from adl.core.broker import IngestionQueueHealth, RunningIngestionTask
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
    LAYER_SCHEDULER,
    LAYER_WORKER,
    CheckState,
)
from adl.monitoring.health import (
    evaluate_connection_health,
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


PROBE_CHECK_IDS = ("dns_resolution", "tcp_connect", "source_check")


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


class SourceProbeLayerTests(HealthEvaluatorTestCase):
    """Layers 4-5 are external and on-demand: the evaluator only ever reads
    stored probe rows, rests at STALE (or UNSUPPORTED where the plugin has
    no contract), and STALE never reaches the headline."""

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

        self.assertEqual(self.check(checklist, "dns_resolution").state, CheckState.STALE)
        self.assertEqual(checklist.status, CheckState.OK)

    def test_result_inside_fifteen_minutes_is_fresh(self):
        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "OK", age=timedelta(minutes=14))

        checklist = self.evaluate()

        check = self.check(checklist, "dns_resolution")
        self.assertEqual(check.state, CheckState.OK)
        # The rendered message carries the result's age and origin
        self.assertIn("on-demand probe", check.message)

    def test_fresh_failed_dns_leads_the_headline_and_skips_below(self):
        from adl.monitoring.constants import LAYER_NETWORK

        self.make_healthy()
        self.with_supported_contract()
        self.probe_row("dns_resolution", "FAILED", age=timedelta(minutes=1),
                       category="DNS_FAILURE")

        checklist = self.evaluate()

        self.assertEqual(checklist.status, CheckState.FAILED)
        self.assertEqual(checklist.first_failing_layer, LAYER_NETWORK)
        self.assertEqual(checklist.headline_check_id, "dns_resolution")
        for check_id in ("tcp_connect", "source_check", "data_freshness"):
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

        self.assertEqual(self.check(checklist, "dns_resolution").state, CheckState.STALE)
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
