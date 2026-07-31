"""
The per-connection ingestion diagnostic: a checklist with a headline verdict
naming the first failing layer, computed on read from rows the system already
holds. Core records what happened (heartbeat, schedule, locks, activity
logs); this module decides what it means.

:func:`evaluate_connection_health` returns the full checklist for the
precondition band and the internal layers: 1-3 (scheduler, worker, locks)
and 6 (data freshness, rolled up per station).
:func:`store_connection_health` persists only change — one overwritten
headline row per connection plus an append-only transitions log.

Two rules govern the checklist shape:

- The first failing *blocking* check sets the headline; every check below it
  reports ``SKIPPED``, not ``FAILED`` — the diagnostic never claims to know
  something it could not have observed.
- Advisory findings (schedule drift, an unanswering broker) are shown but
  never seize the headline.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _
from django_celery_beat.models import IntervalSchedule

from adl.core.broker import (
    get_ingestion_queue_health,
    running_task_stuck_after_seconds,
    running_task_warn_after_seconds,
)
from adl.core.models import (
    NetworkConnection,
    heartbeat_last_run_at,
    is_coordinator_overdue,
)
from adl.core.tasks import find_connection_schedule_entries, ingest_station_lock_key

from .constants import (
    LAYER_DATA,
    LAYER_LOCKS,
    LAYER_SCHEDULER,
    LAYER_WORKER,
    CheckState,
)
from .models import NetworkConnectionHealth, NetworkConnectionHealthTransition
from .status import (
    ERROR as STATION_DATA_ERROR,
    WARNING as STATION_DATA_WARNING,
    annotate_station_pull_activity,
    compute_station_status,
    connection_thresholds,
)

logger = logging.getLogger(__name__)

# The evaluated ladder. Layers 4-5 (network, source) join as their evidence
# sources land; inserting there must not renumber anything, which is why
# layers are identifiers and never ordinals.
EVALUATED_LAYERS = (LAYER_SCHEDULER, LAYER_WORKER, LAYER_LOCKS, LAYER_DATA)


@dataclass(frozen=True)
class CheckLink:
    """A link rendered after a check's message (e.g. the data layer links
    through to the per-station monitoring page)."""

    url: str
    label: str


@dataclass(frozen=True)
class HealthCheck:
    """One row of the checklist. ``layer`` is ``None`` for the precondition band."""

    id: str
    layer: Optional[str]
    label: str
    state: str
    message: str
    # Advisory checks are shown but never seize the headline
    blocking: bool = True
    link: Optional[CheckLink] = None

    @property
    def coloured(self):
        """Colour carries the verdict axis only; epistemic states render grey."""
        return self.state in (CheckState.OK, CheckState.WARNING, CheckState.FAILED)


@dataclass(frozen=True)
class ConnectionHealthChecklist:
    status: str
    first_failing_layer: Optional[str]
    headline_check_id: Optional[str]
    headline_message: str
    precondition: Tuple[HealthCheck, ...]
    checks: Tuple[HealthCheck, ...]

    def checks_for_layer(self, layer):
        return tuple(check for check in self.checks if check.layer == layer)


def evaluate_connection_health(connection, queue_health=None, queue_health_provider=None, now=None):
    """
    Compute the full checklist for one connection.

    ``queue_health`` is the broker observation from
    :func:`adl.core.broker.get_ingestion_queue_health`; the fleet sweep
    shares one bounded call across every connection via
    ``queue_health_provider``. When neither is supplied the observation is
    fetched lazily, and only if the ladder actually reaches the worker
    layer — a scheduler-level failure never dials the broker just to report
    ``SKIPPED``.
    """
    now = now or dj_timezone.now()

    if not connection.enabled:
        precondition = (HealthCheck(
            id="connection_enabled",
            layer=None,
            label=_("Connection enabled"),
            state=CheckState.DISABLED,
            message=_("Ingestion for this connection is switched off. "
                      "Nothing below is evaluated."),
        ),)
        return ConnectionHealthChecklist(
            status=CheckState.DISABLED,
            first_failing_layer=None,
            headline_check_id="connection_enabled",
            headline_message=_("This connection is disabled."),
            precondition=precondition,
            checks=_all_skipped(_ladder_plan(), _("The connection is disabled.")),
        )

    precondition = (HealthCheck(
        id="connection_enabled",
        layer=None,
        label=_("Connection enabled"),
        state=CheckState.OK,
        message=_("The connection is enabled and scheduled every %(interval)s minutes.")
                % {"interval": connection.interval},
    ),)

    if queue_health is not None:
        provider = lambda: queue_health  # noqa: E731
    else:
        provider = queue_health_provider or get_ingestion_queue_health

    builder = _ChecklistBuilder(connection, provider, now)
    checks = builder.run()

    status, layer, headline_check = _headline(checks)
    if headline_check is None:
        headline_message = _("All checks passed.")
        headline_check_id = None
    else:
        headline_message = headline_check.message
        headline_check_id = headline_check.id

    return ConnectionHealthChecklist(
        status=status,
        first_failing_layer=layer,
        headline_check_id=headline_check_id,
        headline_message=headline_message,
        precondition=precondition,
        checks=checks,
    )


def _headline(checks):
    """The first failing blocking check leads; blocking warnings lead only
    when nothing failed; advisory findings never lead."""
    for check in checks:
        if check.blocking and check.state == CheckState.FAILED:
            return CheckState.FAILED, check.layer, check
    for check in checks:
        if check.blocking and check.state == CheckState.WARNING:
            return CheckState.WARNING, check.layer, check
    return CheckState.OK, None, None


def _ladder_plan():
    """(id, layer, label) of every ladder check, in causal order."""
    return (
        ("schedule_entry", LAYER_SCHEDULER, _("Schedule entry")),
        ("schedule_enabled", LAYER_SCHEDULER, _("Schedule entry enabled")),
        ("schedule_duplicated", LAYER_SCHEDULER, _("Single schedule entry")),
        ("schedule_interval", LAYER_SCHEDULER, _("Schedule interval")),
        ("beat_tick", LAYER_SCHEDULER, _("Beat delivered a tick")),
        ("worker_consuming", LAYER_WORKER, _("Worker consuming the ingestion queue")),
        ("queue_depth", LAYER_WORKER, _("Ingestion queue depth")),
        ("running_tasks", LAYER_WORKER, _("Running ingestion tasks")),
        ("tick_consumed", LAYER_WORKER, _("Tick reached a worker")),
        ("station_locks", LAYER_LOCKS, _("Station locks")),
        ("data_freshness", LAYER_DATA, _("Data freshness")),
    )


def _all_skipped(plan, reason):
    message = _("Not evaluated — %(reason)s") % {"reason": reason}
    return tuple(
        HealthCheck(id=check_id, layer=layer, label=label,
                    state=CheckState.SKIPPED, message=message)
        for check_id, layer, label in plan
    )


class _ChecklistBuilder:
    """
    Walks the ladder plan in order, emitting one :class:`HealthCheck` per
    entry. After the first blocking ``FAILED``, every remaining check is
    emitted as ``SKIPPED`` — and side effects that would only serve skipped
    checks (the broker call) never happen.
    """

    def __init__(self, connection, queue_health_provider, now):
        self.connection = connection
        self._queue_health_provider = queue_health_provider
        self._queue_health = None
        self.now = now
        self.failed = False
        self.schedule_entries = find_connection_schedule_entries(connection)

    @property
    def queue_health(self):
        if self._queue_health is None:
            self._queue_health = self._queue_health_provider()
        return self._queue_health

    def run(self):
        checks = []
        for check_id, layer, label in _ladder_plan():
            if self.failed:
                check = HealthCheck(
                    id=check_id, layer=layer, label=label,
                    state=CheckState.SKIPPED,
                    message=_("Not evaluated — a failure above makes this "
                              "check meaningless."),
                )
            else:
                # A check returns (state, message, blocking) with an optional
                # trailing CheckLink
                result = getattr(self, f"_check_{check_id}")()
                state, message, blocking = result[:3]
                link = result[3] if len(result) > 3 else None
                check = HealthCheck(id=check_id, layer=layer, label=label,
                                    state=state, message=message, blocking=blocking,
                                    link=link)
                if check.blocking and check.state == CheckState.FAILED:
                    self.failed = True
            checks.append(check)
        return tuple(checks)

    # -- Layer 1: scheduler — five pure-DB checks over the heartbeat and the
    # periodic task, resolved by what it runs (task + args), never by name

    def _check_schedule_entry(self):
        if self.schedule_entries.missing:
            return (CheckState.FAILED,
                    _("No beat schedule entry runs ingestion for this connection. "
                      "Re-saving the connection recreates it."),
                    True)
        return (CheckState.OK,
                _("A beat schedule entry runs ingestion for this connection."),
                True)

    def _check_schedule_enabled(self):
        entry = self.schedule_entries.entry
        if not entry.enabled:
            return (CheckState.FAILED,
                    _("The schedule entry is disabled while the connection is "
                      "enabled, so beat never fires it. Re-saving the connection "
                      "re-enables it."),
                    True)
        return CheckState.OK, _("The schedule entry is enabled."), True

    def _check_schedule_duplicated(self):
        if self.schedule_entries.duplicated:
            return (CheckState.WARNING,
                    _("%(count)d schedule entries run this connection; which one "
                      "beat fires is undefined. Delete the extras.")
                    % {"count": len(self.schedule_entries.entries)},
                    False)
        return CheckState.OK, _("Exactly one schedule entry exists."), False

    def _check_schedule_interval(self):
        entry = self.schedule_entries.entry
        interval = entry.interval
        matches = (
            interval is not None
            and interval.period == IntervalSchedule.MINUTES
            and interval.every == self.connection.interval
        )
        if not matches:
            return (CheckState.WARNING,
                    _("The schedule entry does not fire every %(interval)s minutes "
                      "as the connection is configured to. Re-saving the connection "
                      "corrects it.")
                    % {"interval": self.connection.interval},
                    False)
        return (CheckState.OK,
                _("The schedule fires every %(interval)s minutes, as configured.")
                % {"interval": self.connection.interval},
                False)

    def _check_beat_tick(self):
        entry = self.schedule_entries.entry
        # DatabaseScheduler writes PeriodicTask.last_run_at, so this is
        # "did beat deliver a tick", judged at 2x the connection's own interval
        if entry.last_run_at is None:
            return (CheckState.FAILED,
                    _("Beat has never fired this schedule entry. The beat "
                      "scheduler is not running, or was never started."),
                    True)
        if is_coordinator_overdue(True, self.connection.interval, entry.last_run_at, self.now):
            return (CheckState.FAILED,
                    _("Beat last fired this entry at %(last)s — more than twice "
                      "the %(interval)s-minute interval ago. The beat scheduler "
                      "has stopped.")
                    % {"last": entry.last_run_at, "interval": self.connection.interval},
                    True)
        return (CheckState.OK,
                _("Beat fired this entry at %(last)s.") % {"last": entry.last_run_at},
                True)

    # -- Layer 2: worker and queue — one bounded broker observation, where
    # None always means unknown, never down

    def _check_worker_consuming(self):
        consuming = self.queue_health.worker_consuming
        if consuming is None:
            # Unknown, not down: an unanswering broker must not manufacture a
            # false outage, so this finding is advisory
            return (CheckState.WARNING,
                    _("The broker did not answer, so whether a worker is "
                      "consuming the ingestion queue is unknown."),
                    False)
        if not consuming:
            return (CheckState.FAILED,
                    _("Workers replied, but none is consuming the ingestion "
                      "queue. The ingestion worker is down or misrouted."),
                    True)
        return CheckState.OK, _("A worker is consuming the ingestion queue."), True

    def _check_queue_depth(self):
        depth = self.queue_health.queue_depth
        if depth is None:
            return (CheckState.WARNING,
                    _("The broker did not answer, so the ingestion queue depth "
                      "is unknown."),
                    False)
        # Depth is reported as depth, never as "work outstanding" — prefetched
        # and executing tasks are invisible here, so it is a lower bound
        return (CheckState.OK,
                _("%(depth)d message(s) visible on the ingestion queue "
                  "(a lower bound; running and prefetched tasks are not counted).")
                % {"depth": depth},
                False)

    def _check_running_tasks(self):
        tasks = self.queue_health.running_tasks
        if tasks is None:
            return (CheckState.WARNING,
                    _("The broker did not answer, so running ingestion tasks "
                      "are unknown."),
                    False)

        mine = [task for task in tasks if task.args and task.args[0] == self.connection.id]
        if not mine:
            return CheckState.OK, _("No ingestion task for this connection is currently running."), True

        ages = [task.age_seconds for task in mine if task.age_seconds is not None]
        stuck_after = running_task_stuck_after_seconds(self.connection)
        warn_after = running_task_warn_after_seconds(self.connection)
        oldest = max(ages) if ages else None

        if oldest is not None and oldest > stuck_after:
            return (CheckState.FAILED,
                    _("An ingestion task for this connection has been running "
                      "for %(minutes)d minutes — more than three times the "
                      "connection's interval. It is stuck, not slow.")
                    % {"minutes": int(oldest // 60)},
                    True)
        if oldest is not None and oldest > warn_after:
            return (CheckState.WARNING,
                    _("An ingestion task for this connection has been running "
                      "for %(minutes)d minutes — longer than the connection's "
                      "own %(interval)s-minute interval.")
                    % {"minutes": int(oldest // 60), "interval": self.connection.interval},
                    False)
        return (CheckState.OK,
                _("%(count)d ingestion task(s) for this connection are running "
                  "within their time budget.") % {"count": len(mine)},
                True)

    def _check_tick_consumed(self):
        # The load-bearing boundary check: beat said yes (or this row would be
        # SKIPPED behind a beat_tick failure), so a stale heartbeat means the
        # tick never reached a worker — layer 1's failure lands here, on
        # layer 2, rather than claiming the scheduler is dead.
        last_run_at = heartbeat_last_run_at(self.connection)
        if is_coordinator_overdue(True, self.connection.interval, last_run_at, self.now):
            if last_run_at is None:
                message = _("Beat is delivering ticks, but the ingestion "
                            "coordinator has never run — the ticks are not "
                            "reaching a worker.")
            else:
                message = _("Beat is delivering ticks, but the ingestion "
                            "coordinator last ran at %(last)s — the ticks have "
                            "stopped reaching a worker.") % {"last": last_run_at}
            return CheckState.FAILED, message, True
        return (CheckState.OK,
                _("The ingestion coordinator last ran at %(last)s.")
                % {"last": last_run_at},
                True)

    # -- Layer 3: held station locks and their staleness

    def _check_station_locks(self):
        enabled_link_ids = list(
            self.connection.station_links.filter(enabled=True).values_list("id", flat=True)
        )
        held = [link_id for link_id in enabled_link_ids
                if cache.get(ingest_station_lock_key(link_id)) is not None]

        if not held:
            return CheckState.OK, _("No station locks are held."), True

        running_tasks = self.queue_health.running_tasks
        if running_tasks is None:
            return (CheckState.WARNING,
                    _("%(held)d station lock(s) are held, but the broker did not "
                      "answer, so whether a task is behind them is unknown. "
                      "Locks expire on their own TTL.") % {"held": len(held)},
                    False)

        running_station_ids = set()
        for task in running_tasks:
            if (task.name == "adl.core.tasks.process_station_link_batch"
                    and len(task.args) >= 2 and task.args[0] == self.connection.id):
                running_station_ids.update(task.args[1])

        stale = [link_id for link_id in held if link_id not in running_station_ids]
        if not stale:
            return (CheckState.OK,
                    _("%(held)d station lock(s) are held by running ingestion "
                      "tasks.") % {"held": len(held)},
                    True)

        counts = {"stale": len(stale), "total": len(enabled_link_ids)}
        if len(stale) == len(enabled_link_ids):
            return (CheckState.FAILED,
                    _("All %(total)d enabled stations hold stale locks with no "
                      "task behind them — a worker died mid-run. They expire on "
                      "their own TTL.") % counts,
                    True)
        return (CheckState.WARNING,
                _("%(stale)d of %(total)d enabled stations hold stale locks with "
                  "no task behind them — a worker died mid-run. They expire on "
                  "their own TTL.") % counts,
                True)

    # -- Layer 6: data freshness, rolled up per station from the shared
    # status helper. All stations affected -> FAILED, some -> WARNING,
    # none -> OK — one misconfigured station cannot turn a healthy
    # connection red.

    def _check_data_freshness(self):
        links = annotate_station_pull_activity(
            self.connection.station_links.filter(enabled=True)
        )
        thresholds = connection_thresholds(self.connection)

        total = 0
        stale = 0
        aging = 0
        for link in links:
            total += 1
            status = compute_station_status(
                last_check=link.last_check,
                last_check_success=link.last_log_success,
                last_data_time=link.last_collected,
                thresholds=thresholds,
                now=self.now,
            )
            if status.data_status == STATION_DATA_ERROR:
                stale += 1
            elif status.data_status == STATION_DATA_WARNING:
                aging += 1

        if not total:
            return (CheckState.OK,
                    _("This connection has no enabled station links."),
                    True)

        link = CheckLink(
            url=reverse("network_connection_monitoring", args=(self.connection.id,)),
            label=_("View stations"),
        )
        counts = {"stale": stale, "aging": aging, "total": total}
        if not stale:
            # The verdict rolls up stale stations only, but the message must
            # not claim more than the shared helper reports — aging stations
            # render amber on the monitoring panel and are named here too
            if aging:
                message = _("No station has stale data, but %(aging)d of "
                            "%(total)d enabled station(s) have no fresh "
                            "observations within the warning window.") % counts
            else:
                message = _("Data is current on all %(total)d enabled "
                            "station(s).") % counts
            return CheckState.OK, message, True, link
        if stale == total:
            return (CheckState.FAILED,
                    _("All %(total)d enabled station(s) have stale data — no "
                      "recent observations within the connection's freshness "
                      "limit.") % counts,
                    True, link)
        return (CheckState.WARNING,
                _("%(stale)d of %(total)d enabled stations have stale data — "
                  "no recent observations within the connection's freshness "
                  "limit.") % counts,
                True, link)


def store_connection_health(connection, checklist, now=None):
    """
    Persist the headline of a computed checklist — only change moves anything.

    ``since`` moves, and a transition row is appended, only when
    ``(status, first_failing_layer)`` changes. A category-only change (same
    verdict, different underlying check or message) rewrites the headline
    columns but touches neither.
    """
    now = now or dj_timezone.now()

    health, created = NetworkConnectionHealth.objects.get_or_create(
        connection=connection,
        defaults={
            "status": checklist.status,
            "first_failing_layer": checklist.first_failing_layer,
            "headline_check_id": checklist.headline_check_id,
            "headline_message": checklist.headline_message,
            "since": now,
            "evaluated_at": now,
        },
    )

    if created:
        NetworkConnectionHealthTransition.objects.create(
            connection=connection,
            at=now,
            from_status=None,
            from_first_failing_layer=None,
            to_status=checklist.status,
            to_first_failing_layer=checklist.first_failing_layer,
        )
        return health

    changed = ((health.status, health.first_failing_layer)
               != (checklist.status, checklist.first_failing_layer))
    if changed:
        NetworkConnectionHealthTransition.objects.create(
            connection=connection,
            at=now,
            from_status=health.status,
            from_first_failing_layer=health.first_failing_layer,
            to_status=checklist.status,
            to_first_failing_layer=checklist.first_failing_layer,
        )
        health.since = now

    health.status = checklist.status
    health.first_failing_layer = checklist.first_failing_layer
    health.headline_check_id = checklist.headline_check_id
    health.headline_message = checklist.headline_message
    health.evaluated_at = now
    health.save()
    return health


def evaluate_and_store_connection_health(connection, queue_health=None,
                                         queue_health_provider=None, now=None):
    checklist = evaluate_connection_health(
        connection, queue_health=queue_health,
        queue_health_provider=queue_health_provider, now=now,
    )
    health = store_connection_health(connection, checklist, now=now)
    return checklist, health


def evaluate_all_connections(now=None):
    """
    Evaluate and persist every connection's verdict — the sweep task's
    entry point. One bounded broker observation is shared lazily across the
    fleet (made at most once, and not at all when every connection
    short-circuits before the worker layer), and one connection's evaluator
    crash cannot blind the rest.
    """
    shared = {}

    def shared_queue_health():
        if "observation" not in shared:
            shared["observation"] = get_ingestion_queue_health()
        return shared["observation"]

    for connection in NetworkConnection.objects.all():
        try:
            evaluate_and_store_connection_health(
                connection, queue_health_provider=shared_queue_health, now=now
            )
        except Exception:
            logger.exception("[HEALTH] Could not evaluate connection %s", connection.id)
