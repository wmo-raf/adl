"""
Bring a seeded demo connection into the state the documentation screenshots
need — by making the real things happen, not by writing verdicts.

``--ingest`` waits for the beat scheduler to fire the connection's own
schedule entry (a real tick, consumed by a real worker), falling back to a
manual run — the same enqueue as the diagnostic page's *Run ingestion now*
button — only when no scheduled run arrives in time. ``--probe`` and
``--station-check`` run the on-demand source checks exactly as the buttons
do and persist their results the same way, so the captured screens show
what an operator pressing those buttons would see.

``--present-interval`` exists because the two things the capture needs pull
the connection's interval in opposite directions. Waiting for a real beat
tick wants it as short as possible; every freshness threshold in the
monitoring UI is a multiple of it (a station's data is "fresh" for
``interval x 4``), so a 1-minute interval marks any real AWS source stale
minutes after a successful run. So: collect on a fast interval, then set the
interval an operator would actually configure before the verdict is stored
and the screens are captured. Nothing about the state is faked — the data
really was collected and the verdict really is recomputed against the
interval the screenshots show.
"""

import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_timezone

from adl.core.models import NetworkConnection, ObservationRecord
from adl.core.source_checks import run_source_probe, run_station_source_check
from adl.core.tasks import INGESTION_QUEUE_NAME, run_network_plugin
from adl.monitoring.constants import PROBE_LAYER_IDS
from adl.monitoring.health import evaluate_and_store_connection_health
from adl.monitoring.models import SourceProbeResult, StationLinkActivityLog

TERMINAL = (
    StationLinkActivityLog.ActivityStatus.COMPLETED,
    StationLinkActivityLog.ActivityStatus.FAILED,
    StationLinkActivityLog.ActivityStatus.SKIPPED,
)


class Command(BaseCommand):
    help = "Run a real collection cycle and the on-demand source checks for a seeded connection."

    def add_arguments(self, parser):
        parser.add_argument("--connection", required=True, help="Connection name.")
        parser.add_argument("--ingest", action="store_true",
                            help="Wait for a scheduled run; enqueue a manual run if none arrives.")
        parser.add_argument("--wait", type=int, default=180,
                            help="Seconds to wait for the scheduled tick, then for the run to finish.")
        parser.add_argument("--probe", action="store_true", help="Run the connection-scope source probe.")
        parser.add_argument("--station-check", action="append", default=[], metavar="STATION_ID",
                            help="Run the station-scope check for this station (repeatable).")
        parser.add_argument("--present-interval", type=int,
                            help="Set the connection's processing interval (minutes) after "
                                 "collecting, so the captured screens show realistic freshness "
                                 "thresholds. See this command's docstring.")
        parser.add_argument("--evaluate", action="store_true",
                            help="Evaluate and store the connection's health verdict now, as the "
                                 "5-minute housekeeping sweep would.")

    def handle(self, *args, **options):
        try:
            connection = NetworkConnection.objects.get(name=options["connection"])
        except NetworkConnection.DoesNotExist:
            raise CommandError(f"No connection named {options['connection']!r}.")

        if options["ingest"]:
            self.ingest(connection, options["wait"])
        if options["probe"]:
            self.probe(connection)
        for station_id in options["station_check"]:
            self.station_check(connection, station_id)
        if options["present_interval"]:
            self.present_interval(connection, options["present_interval"])
        if options["evaluate"]:
            checklist, _ = evaluate_and_store_connection_health(connection)
            self.stdout.write(f"  verdict: {checklist.status} — {checklist.headline_message}")

    # -- collection cycle ------------------------------------------------------

    def ingest(self, connection, wait):
        links = list(connection.station_links.filter(enabled=True))
        since = dj_timezone.now()
        deadline = time.monotonic() + wait

        self.stdout.write(f"Waiting up to {wait}s for beat to fire the schedule entry of "
                          f"'{connection.name}' (interval {connection.interval} min)...")
        if not self._wait_for_runs(links, since, deadline):
            self.stdout.write(self.style.WARNING(
                "No scheduled run arrived in time — enqueueing a manual run instead "
                "(the scheduler layer of the diagnostic will not be green)."))
            since = dj_timezone.now()
            run_network_plugin.apply_async(args=[connection.id], kwargs={"manual": True},
                                           queue=INGESTION_QUEUE_NAME)
            if not self._wait_for_runs(links, since, time.monotonic() + wait):
                raise CommandError("The collection run did not finish in time.")

        # The beat scheduler writes the entry's last_run_at to the database only
        # on its periodic sync (every ~3 minutes), and the scheduler layer of the
        # diagnostic reads it from there — so wait for the sync, or the verdict
        # would say beat never fired for a run beat just fired.
        self._wait_for_beat_sync(connection, deadline)

        count = ObservationRecord.objects.filter(connection=connection).count()
        for log in StationLinkActivityLog.objects.filter(
                station_link__in=links, direction="pull", time__gte=since,
                status__in=TERMINAL).order_by("station_link_id", "-time").distinct("station_link_id"):
            self.stdout.write(f"  {log.station_link}: {log.status} — {log.message or ''} "
                              f"({log.records_count} records)")
        self.stdout.write(self.style.SUCCESS(
            f"Collection cycle done: {count} observation record(s) stored for '{connection.name}'."))

    def _wait_for_beat_sync(self, connection, deadline):
        from adl.core.tasks import find_connection_schedule_entries
        while time.monotonic() < deadline:
            entries = list(find_connection_schedule_entries(connection).entries)
            if entries and all(e.last_run_at for e in entries):
                return True
            time.sleep(5)
        self.stdout.write(self.style.WARNING(
            "Beat has not yet recorded its tick for this connection; the scheduler layer "
            "of the diagnostic may still show it as never fired."))
        return False

    def _wait_for_runs(self, links, since, deadline):
        """True once every enabled station link has a terminal pull log newer than ``since``."""
        while time.monotonic() < deadline:
            done = StationLinkActivityLog.objects.filter(
                station_link__in=links, direction="pull", time__gte=since, status__in=TERMINAL,
            ).values_list("station_link_id", flat=True).distinct()
            if len(set(done)) >= len(links):
                return True
            time.sleep(3)
        return False

    def present_interval(self, connection, minutes):
        """Re-point the connection at a realistic interval, schedule entry and
        all. The entry is keyed on the connection, not on the interval, so
        beat's recorded last tick survives the change and the scheduler layer
        stays green."""
        connection.plugin_processing_interval = minutes
        connection.save()
        self.stdout.write(f"  presented interval: every {minutes} minute(s) "
                          f"(data stays fresh for {minutes * 4} minutes)")

    # -- on-demand checks, persisted exactly as the buttons persist them ----------

    def probe(self, connection):
        if not connection.source_probe_supported:
            self.stdout.write(self.style.WARNING("This plugin does not implement the source probe."))
            return
        now = dj_timezone.now()
        for step in run_source_probe(connection):
            SourceProbeResult.objects.create(
                connection=connection, station_link=None, check_id=step.check_id,
                layer=PROBE_LAYER_IDS[step.layer], status=step.result.status,
                category=step.result.category, message=step.result.message,
                latency_ms=step.result.latency_ms, at=now,
            )
            self.stdout.write(f"  probe {step.check_id}: {step.result.status} — {step.result.message}")

    def station_check(self, connection, station_id):
        link = connection.station_links.filter(station__station_id=station_id).first()
        if link is None:
            raise CommandError(f"No station link for station {station_id!r} on '{connection.name}'.")
        if not link.station_source_check_supported:
            self.stdout.write(self.style.WARNING("This plugin does not implement the station source check."))
            return
        now = dj_timezone.now()
        step = run_station_source_check(link)
        SourceProbeResult.objects.create(
            connection=connection, station_link=link, check_id=step.check_id,
            layer=PROBE_LAYER_IDS[step.layer], status=step.result.status,
            category=step.result.category, message=step.result.message,
            latency_ms=step.result.latency_ms, at=now,
        )
        self.stdout.write(f"  station check {station_id}: {step.result.status} — {step.result.message}")
