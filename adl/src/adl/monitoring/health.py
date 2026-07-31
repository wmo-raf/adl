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
from datetime import datetime, timedelta
from typing import Optional, Tuple

from django.core.cache import cache
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db.models import Count, Max, Q
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _
from django_celery_beat.models import IntervalSchedule

from adl.core.broker import (
    get_ingestion_queue_health,
    running_task_stuck_after_seconds,
    running_task_warn_after_seconds,
    worker_stack_guard_message,
)
from adl.core.models import (
    NetworkConnection,
    heartbeat_last_run_at,
    heartbeat_worker_versions,
    is_coordinator_overdue,
)
from adl.core.source_checks import (
    CHECK_DNS,
    CHECK_SOURCE,
    CHECK_TCP,
    SourceCheckStatus,
    connection_implements_check_source,
)
from adl.core.tasks import find_connection_schedule_entries, ingest_station_lock_key

from .classification import category_message, classify_failure_text
from .constants import (
    LAYER_DATA,
    LAYER_LOCKS,
    LAYER_NETWORK,
    LAYER_SCHEDULER,
    LAYER_SOURCE,
    LAYER_WORKER,
    PROVENANCE_INTERNAL,
    PROVENANCE_LABELS,
    PROVENANCE_LOG_CLASSIFICATION,
    PROVENANCE_PROBE,
    CheckState,
)
from .models import (
    NetworkConnectionHealth,
    NetworkConnectionHealthTransition,
    SourceProbeResult,
    StationLinkActivityLog,
)
from .status import (
    ERROR as STATION_DATA_ERROR,
    WARNING as STATION_DATA_WARNING,
    annotate_station_pull_activity,
    compute_station_status,
    connection_thresholds,
)

logger = logging.getLogger(__name__)

# Sentinel: "endpoint not looked up yet" — None is a legitimate resolution
_UNRESOLVED = object()

# The evaluated ladder, in the order a failure propagates. Layers 4-5 are
# external: their evidence comes from on-demand probes only, so their
# resting state is STALE, never FAILED.
EVALUATED_LAYERS = (LAYER_SCHEDULER, LAYER_WORKER, LAYER_LOCKS,
                    LAYER_NETWORK, LAYER_SOURCE, LAYER_DATA)

# A probe result older than this is STALE — "not recently checked", excluded
# from the headline. Deliberately different from the probe view's 60-second
# cooldown: freshness asks "can I still trust this", cooldown asks "may I
# ask again yet".
PROBE_FRESHNESS_SECONDS = 15 * 60

# Evidence read from activity logs is fresh within 2x the connection's own
# interval — reusing the heartbeat's overdue margin rather than the
# probe-shaped 15 minutes, so a daily and a 5-minutely connection are both
# judged fairly
LOG_EVIDENCE_INTERVAL_MULTIPLIER = 2

# The terminal activity states that constitute evidence. SKIPPED is
# deliberately absent: a lock collision merely looks like a run, and
# counting it would manufacture fake layer-4 OK evidence exactly when the
# system is busiest.
_TERMINAL_LOG_STATUSES = (
    StationLinkActivityLog.ActivityStatus.COMPLETED,
    StationLinkActivityLog.ActivityStatus.FAILED,
)


@dataclass(frozen=True)
class Evidence:
    """One observation feeding an external layer's evidence slot.

    ``message`` is always normalised text (a probe step's own message, a
    classification rule's wording, or core's run summary) — never a raw
    exception message, which can embed credentials.
    """

    provenance: str  # PROVENANCE_INTERNAL / PROVENANCE_PROBE / PROVENANCE_LOG_CLASSIFICATION
    state: str       # CheckState.OK or CheckState.FAILED
    message: str
    at: datetime


@dataclass(frozen=True)
class ConfigurationDrift:
    """
    Outcome of re-running a stored row's own validation.

    ``drifted`` is the claim; ``evaluated`` is whether the claim could be
    made at all — a crashed validator leaves ``evaluated`` False and
    ``drifted`` False, because a crash is not evidence the configuration
    is wrong. ``fields`` and ``messages`` come straight from
    ``ValidationError.message_dict``: the field name is what the operator
    needs to go and fix.
    """

    drifted: bool
    evaluated: bool
    fields: Tuple[str, ...] = ()
    messages: Tuple[str, ...] = ()


def configuration_drift(instance) -> ConfigurationDrift:
    """
    Whether a stored row no longer passes its own validation rules —
    ``full_clean(validate_unique=False)`` and nothing more, so every rule a
    plugin adds to ``clean()`` improves this check retroactively, and a
    uniqueness collision (which cannot exist in a stored row) is never
    re-litigated.

    Only ``ValidationError`` means drift. Any other exception is caught and
    makes no drift claim: a crash in a validator is not evidence the
    configuration is wrong, and unhandled it would blind the diagnostic
    from one bad plugin.
    """
    try:
        instance.full_clean(validate_unique=False)
    except ValidationError as error:
        message_dict = getattr(error, "message_dict", {NON_FIELD_ERRORS: [str(error)]})
        fields = tuple(sorted(message_dict))
        messages = tuple(
            "%s: %s" % (field, " ".join(field_messages))
            for field, field_messages in sorted(message_dict.items())
        )
        return ConfigurationDrift(drifted=True, evaluated=True,
                                  fields=fields, messages=messages)
    except Exception:
        logger.exception("[HEALTH] full_clean crashed for %s %s",
                         type(instance).__name__, getattr(instance, "id", None))
        return ConfigurationDrift(drifted=False, evaluated=False)
    return ConfigurationDrift(drifted=False, evaluated=True)


def station_link_drifted(station_link) -> bool:
    """Whether a stored station link's configuration has drifted — the
    station-scope predicate layer-5 evidence filters on."""
    return configuration_drift(station_link).drifted


def connection_declares_validation_rules(connection) -> bool:
    """True when the plugin's ``NetworkConnection`` subclass overrides
    ``clean()`` — the no-I/O implemented-ness seam, mirroring
    ``source_probe_supported``. A plugin that declares no rules must report
    ``UNSUPPORTED``, never clean: silence is not validation."""
    return type(connection).clean is not NetworkConnection.clean


def probe_age_minutes(now, at):
    """Whole minutes since a probe observation — the one age computation
    behind every 'N minute(s) ago' the diagnostic renders."""
    return int(max((now - at).total_seconds(), 0) // 60)


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
    # External layers only: who produced the winning observation, the
    # superseded observation it displaced, and that loser's rendered line
    provenance: Optional[str] = None
    superseded: Optional[Evidence] = None
    superseded_message: Optional[str] = None

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

    enabled_check = HealthCheck(
        id="connection_enabled",
        layer=None,
        label=_("Connection enabled"),
        state=CheckState.OK,
        message=_("The connection is enabled and scheduled every %(interval)s minutes.")
                % {"interval": connection.interval},
    )

    drift = configuration_drift(connection)
    precondition = (enabled_check, _configuration_precondition(connection, drift))

    if drift.drifted:
        # Connection-scope drift short-circuits every layer below — the
        # operator is sent to a field on their own form, never to the
        # partner's server. Report-only: ingestion itself still runs.
        return ConnectionHealthChecklist(
            status=CheckState.MISCONFIGURED,
            first_failing_layer=None,
            headline_check_id="configuration_valid",
            headline_message=_("The stored configuration is no longer valid — "
                               "check field(s): %(fields)s.")
                             % {"fields": ", ".join(drift.fields)},
            precondition=precondition,
            checks=_all_skipped(_ladder_plan(),
                                _("the stored configuration is invalid.")),
        )

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
    when nothing failed; advisory findings never lead.

    One sanctioned exception to "epistemic states never lead": a *blocking*
    ``UNSUPPORTED`` — only the worker-consuming signal emits one — reaches
    the headline as information when nothing genuinely failed or warned. It
    is the signal layer 2 exists for, and silently degrading it would be
    worse than being loud; but a real verdict always outranks information,
    and (unlike ``FAILED``) it never short-circuits the layers below."""
    for check in checks:
        if check.blocking and check.state == CheckState.FAILED:
            return CheckState.FAILED, check.layer, check
    for check in checks:
        if check.blocking and check.state == CheckState.WARNING:
            return CheckState.WARNING, check.layer, check
    for check in checks:
        if check.blocking and check.state == CheckState.UNSUPPORTED:
            return CheckState.UNSUPPORTED, check.layer, check
    return CheckState.OK, None, None


def _configuration_precondition(connection, drift):
    """
    The configuration row of the precondition band, from an already-computed
    :class:`ConfigurationDrift`. ``MISCONFIGURED`` is the only blocking
    outcome; the two ``UNSUPPORTED`` shapes (no rules declared, validator
    crashed) are epistemic and advisory.
    """
    def row(state, message, blocking=True):
        return HealthCheck(id="configuration_valid", layer=None,
                           label=_("Configuration valid"), state=state,
                           message=message, blocking=blocking)

    if drift.drifted:
        return row(
            CheckState.MISCONFIGURED,
            _("The stored configuration no longer passes validation — "
              "%(details)s. Fix the named field(s) on the connection's "
              "edit form. Nothing below is evaluated; ingestion itself "
              "is not stopped by this finding.")
            % {"details": "; ".join(drift.messages)},
        )
    if not drift.evaluated:
        return row(
            CheckState.UNSUPPORTED,
            _("The plugin's validation rules crashed, so configuration "
              "drift could not be evaluated. This is not evidence the "
              "configuration is wrong; see the application logs."),
            blocking=False,
        )
    if not connection_declares_validation_rules(connection):
        return row(
            CheckState.UNSUPPORTED,
            _("This plugin declares no connection-level configuration rules "
              "of its own, so only core's field validation ran — silence is "
              "not validation."),
            blocking=False,
        )
    return row(
        CheckState.OK,
        _("The stored configuration passes the plugin's validation rules."),
    )


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
        # One evidence slot per external layer: probe steps stay stored at
        # DNS/TCP granularity, but the layer holds a single verdict
        ("network_path", LAYER_NETWORK, _("Network path to the source")),
        ("source_check", LAYER_SOURCE, _("Source accepts credentials and offers data")),
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
        self._source_endpoint = _UNRESOLVED
        self._drifted_ids = None
        self._data = None
        self.schedule_entries = find_connection_schedule_entries(connection)

    @property
    def queue_health(self):
        if self._queue_health is None:
            self._queue_health = self._queue_health_provider()
        return self._queue_health

    def run(self):
        checks = []
        for check_id, layer, label in _ladder_plan():
            # A failure above makes a check meaningless — with one honest
            # exception: when the source layer consulted data freshness (for
            # the sources-count qualification), the data verdict was
            # genuinely observed and reporting it as SKIPPED would hide the
            # very evidence that triggered the layer-5 verdict
            observed_anyway = check_id == "data_freshness" and self._data is not None
            if self.failed and not observed_anyway:
                check = HealthCheck(
                    id=check_id, layer=layer, label=label,
                    state=CheckState.SKIPPED,
                    message=_("Not evaluated — a failure above makes this "
                              "check meaningless."),
                )
            else:
                # A check returns (state, message, blocking) with an optional
                # trailing CheckLink — or a dict of HealthCheck kwargs
                result = getattr(self, f"_check_{check_id}")()
                if isinstance(result, dict):
                    check = HealthCheck(id=check_id, layer=layer, label=label,
                                        **result)
                else:
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
        unsupported = self.queue_health.unsupported_message("worker_consuming")
        if unsupported:
            # The one blocking UNSUPPORTED in the system: this is the signal
            # layer 2 exists for — the one beat-said-yes hands its failure
            # to — so an untested stack here reaches the headline as
            # information. Blocking-but-not-FAILED means it never
            # short-circuits the layers below to SKIPPED.
            return {"state": CheckState.UNSUPPORTED, "message": unsupported,
                    "blocking": True}
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
        unsupported = self.queue_health.unsupported_message("queue_depth")
        if unsupported:
            return {"state": CheckState.UNSUPPORTED, "message": unsupported,
                    "blocking": False}
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
        # Task ages are computed from time_start, which the *worker* stamps —
        # so this signal is judged against the worker's own reported stack,
        # cached on the heartbeat, not this process's. An unreported stack
        # makes no claim: suppressing the stuck-task signal on silence would
        # blind the very check this layer leans on.
        unsupported = (
            self.queue_health.unsupported_message("running_tasks")
            or worker_stack_guard_message(heartbeat_worker_versions(self.connection))
        )
        if unsupported:
            return {"state": CheckState.UNSUPPORTED, "message": unsupported,
                    "blocking": False}
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

    # -- Layers 4-5: the external layers. Each holds ONE evidence slot fed
    # from three producers — the on-demand probe (PROBE), core's own trusted
    # run record (INTERNAL: successes, and write-time-stamped failures), and
    # the read-time text classification of unstamped failure rows
    # (LOG_CLASSIFICATION). Disagreement resolves on the freshest
    # observation, ties to the probe; the superseded observation is retained
    # on the slot. Nothing here performs I/O against the partner's host —
    # a successful scheduled run is real DNS, TCP, auth and bytes, strictly
    # better than a synthetic probe, and it is what lets the diagnostic go
    # green again after a fix instead of only red after a fault.

    @property
    def source_endpoint(self):
        if self._source_endpoint is _UNRESOLVED:
            try:
                self._source_endpoint = self.connection.get_source_endpoint()
            except Exception:
                logger.exception("[HEALTH] get_source_endpoint raised for connection %s",
                                 self.connection.id)
                self._source_endpoint = None
        return self._source_endpoint

    @property
    def drifted_link_ids(self):
        """Enabled station links whose stored configuration no longer passes
        validation — excluded from layer-5 evidence, or a fault in our own
        configuration would be attributed to the partner's server."""
        if self._drifted_ids is None:
            self._drifted_ids = {
                link.id
                for link in self.connection.station_links.filter(enabled=True)
                if station_link_drifted(link)
            }
        return self._drifted_ids

    def _log_freshness_seconds(self):
        return self.connection.interval * 60 * LOG_EVIDENCE_INTERVAL_MULTIPLIER

    def _terminal_pull_logs(self, since):
        """Terminal pull rows that constitute evidence: COMPLETED and
        FAILED. SKIPPED rows merely look like evidence and are excluded by
        the status filter."""
        return (StationLinkActivityLog.objects
                .filter(station_link__network_connection=self.connection,
                        station_link__enabled=True,
                        direction="pull",
                        status__in=_TERMINAL_LOG_STATUSES,
                        time__gte=since)
                .order_by("-time"))

    def _render_evidence(self, evidence):
        return _("%(message)s (%(origin)s, %(minutes)d minute(s) ago)") % {
            "message": evidence.message,
            "origin": PROVENANCE_LABELS[evidence.provenance],
            "minutes": probe_age_minutes(self.now, evidence.at),
        }

    # Probe evidence -------------------------------------------------------

    def _probe_slot_row(self, layer_id):
        """The decisive stored probe row for one external layer —
        connection-scope rows only: station-scope checks carry a station
        link and are excluded from the connection's verdict by
        construction, not by discipline."""
        check_ids = (CHECK_DNS, CHECK_TCP) if layer_id == 4 else (CHECK_SOURCE,)
        rows = list(SourceProbeResult.objects
                    .filter(connection=self.connection, station_link__isnull=True,
                            check_id__in=check_ids)
                    .order_by("-at")[:len(check_ids)])
        if not rows:
            return None
        # Steps of one probe share their `at`; the decisive row of the
        # newest probe is its failure if it has one, else its last step
        batch = [row for row in rows if row.at == rows[0].at]
        for row in batch:
            if row.status == SourceCheckStatus.FAILED:
                return row
        for row in batch:
            if row.check_id == CHECK_TCP:
                return row
        return batch[0]

    def _probe_evidence(self, probe_row):
        """A fresh OK/FAILED probe row as slot evidence; anything else
        (stale, malformed, plugin-declined) is not evidence."""
        if probe_row is None:
            return None
        if (self.now - probe_row.at).total_seconds() > PROBE_FRESHNESS_SECONDS:
            return None
        if probe_row.status == SourceCheckStatus.OK:
            state = CheckState.OK
        elif probe_row.status == SourceCheckStatus.FAILED:
            state = CheckState.FAILED
        else:
            return None
        # Probe messages are core-authored step summaries, already normalised
        return Evidence(PROVENANCE_PROBE, state, probe_row.message, probe_row.at)

    # Log evidence ---------------------------------------------------------

    def _log_evidence(self, layer_id):
        """The freshest activity-log observation bearing on one external
        layer, within 2x the connection's interval."""
        window_start = self.now - timedelta(seconds=self._log_freshness_seconds())
        for log in self._terminal_pull_logs(window_start):
            evidence = self._evidence_from_log(log, layer_id)
            if evidence is not None:
                return evidence
        return None

    def _evidence_from_log(self, log, layer_id):
        succeeded = (log.status == StationLinkActivityLog.ActivityStatus.COMPLETED
                     and log.success)
        if succeeded:
            if layer_id == 4:
                # The strongest layer-4 evidence in the system: real DNS,
                # TCP and a completed exchange — even a zero-sources run
                return Evidence(
                    PROVENANCE_INTERNAL, CheckState.OK,
                    _("A scheduled run reached the source host over the "
                      "network and completed."),
                    log.time,
                )
            if log.station_link_id in self.drifted_link_ids:
                return None
            if log.sources_count == 0:
                # The one thing a zero-sources success did not do is
                # transfer bytes — no layer-5 OK from it
                return None
            return Evidence(
                PROVENANCE_INTERNAL, CheckState.OK,
                _("A scheduled run authenticated against the source and "
                  "completed."),
                log.time,
            )

        # A terminal failure row. The write-time stamp is the trusted tier;
        # the read-time text rules run only on rows the writer did not stamp
        if log.error_category is not None:
            category = log.error_category
            layer = log.error_layer
            provenance = PROVENANCE_INTERNAL
            message = category_message(category)
        else:
            outcome = classify_failure_text(log.message)
            if outcome is None:
                # Genuinely ambiguous: no classification rather than a guess
                return None
            layer = outcome.layer
            provenance = PROVENANCE_LOG_CLASSIFICATION
            message = outcome.message

        # The layer belongs to the rule/stamp; no layer means the failure
        # stays layer-6 detail and feeds no external slot
        if layer != layer_id:
            return None
        if layer_id == 5 and log.station_link_id in self.drifted_link_ids:
            return None
        return Evidence(provenance, CheckState.FAILED, message, log.time)

    # The sources count ----------------------------------------------------

    def _sources_count_evidence(self):
        """The sources count qualifies layer 5 **only when layer 6 is
        already red**: every station's data stale and every terminal log in
        layer 6's own window resolved zero source items → FAILED; any
        non-zero → OK, the fault is downstream. A count nobody reported
        (NULL) is silence, and silence is never read as a fault."""
        data_check = self._data_freshness()[0]
        if data_check[0] != CheckState.FAILED:
            # Layer 6 green or merely partial: no standalone alarm — a
            # quiet interval on a healthy connection raises nothing
            return None

        thresholds = connection_thresholds(self.connection)
        logs = (self._terminal_pull_logs(self.now - thresholds.freshness_error_limit)
                .exclude(station_link_id__in=self.drifted_link_ids))
        counts = logs.aggregate(
            total=Count("id"),
            offered=Count("id", filter=Q(sources_count__gt=0)),
            unknown=Count("id", filter=Q(sources_count__isnull=True)),
            newest=Max("time"),
            newest_offered=Max("time", filter=Q(sources_count__gt=0)),
        )
        if not counts["total"]:
            return None
        if counts["offered"]:
            return Evidence(
                PROVENANCE_INTERNAL, CheckState.OK,
                _("Runs within the data-freshness window found source data "
                  "on offer — the fault is downstream of the source."),
                counts["newest_offered"],
            )
        if counts["unknown"]:
            return None
        return Evidence(
            PROVENANCE_INTERNAL, CheckState.FAILED,
            _("Data is stale and every run within the data-freshness "
              "window resolved zero source items — the source is offering "
              "no data."),
            counts["newest"],
        )

    # The slot -------------------------------------------------------------

    def _external_slot(self, layer_id, supported, unsupported_message):
        probe_row = self._probe_slot_row(layer_id)

        candidates = []
        probe_evidence = self._probe_evidence(probe_row)
        if probe_evidence is not None:
            candidates.append(probe_evidence)
        log_evidence = self._log_evidence(layer_id)
        if log_evidence is not None:
            candidates.append(log_evidence)
        if layer_id == 5:
            sources_evidence = self._sources_count_evidence()
            if sources_evidence is not None:
                candidates.append(sources_evidence)

        if candidates:
            # Freshest observation wins; ties go to the probe
            winner = max(candidates,
                         key=lambda e: (e.at, e.provenance == PROVENANCE_PROBE))
            losers = [c for c in candidates if c is not winner]
            superseded = max(losers, key=lambda e: e.at) if losers else None
            return {
                "state": winner.state,
                "message": self._render_evidence(winner),
                "blocking": True,
                "provenance": winner.provenance,
                "superseded": superseded,
                "superseded_message": (self._render_evidence(superseded)
                                       if superseded else None),
            }

        # No usable evidence: rest at STALE (or surface a fresh
        # malformed/declined probe row), never at FAILED
        if probe_row is not None:
            fresh = (self.now - probe_row.at).total_seconds() <= PROBE_FRESHNESS_SECONDS
            if fresh and probe_row.status == SourceCheckStatus.MALFORMED:
                return {
                    "state": CheckState.UNSUPPORTED,
                    "message": _("The plugin returned a malformed result, "
                                 "which core does not trust: %(message)s")
                               % {"message": probe_row.message},
                    "blocking": False,
                }
            if fresh and probe_row.status == SourceCheckStatus.UNSUPPORTED:
                return {
                    "state": CheckState.UNSUPPORTED,
                    "message": _("%(message)s (on-demand probe, %(minutes)d "
                                 "minute(s) ago)")
                               % {"message": probe_row.message,
                                  "minutes": probe_age_minutes(self.now, probe_row.at)},
                    "blocking": False,
                }
            return {
                "state": CheckState.STALE,
                "message": _("Not recently checked — the last on-demand probe "
                             "ran %(minutes)d minute(s) ago, outside the "
                             "15-minute freshness window.")
                           % {"minutes": probe_age_minutes(self.now, probe_row.at)},
                "blocking": False,
            }
        if supported:
            return {
                "state": CheckState.STALE,
                "message": _("Not recently checked — no probe has run and no "
                             "recent run left usable evidence. External "
                             "layers are probed on demand only."),
                "blocking": False,
            }
        return {"state": CheckState.UNSUPPORTED, "message": unsupported_message,
                "blocking": False}

    def _check_network_path(self):
        return self._external_slot(
            4,
            supported=self.source_endpoint is not None,
            unsupported_message=_("This plugin does not name its source "
                                  "endpoint, so core cannot probe the "
                                  "network path."),
        )

    def _check_source_check(self):
        return self._external_slot(
            5,
            supported=connection_implements_check_source(self.connection),
            unsupported_message=_("This plugin does not implement the source "
                                  "check."),
        )

    # -- Layer 6: data freshness, rolled up per station from the shared
    # status helper. All stations affected -> FAILED, some -> WARNING,
    # none -> OK — one misconfigured station cannot turn a healthy
    # connection red.

    def _data_freshness(self):
        """Memoized ``(check_result, stale_count)`` — computed once whether
        reached from the ladder or consulted early by the sources-count
        qualification of layer 5."""
        if self._data is None:
            self._data = self._compute_data_freshness()
        return self._data

    def _check_data_freshness(self):
        return self._data_freshness()[0]

    def _compute_data_freshness(self):
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
            return ((CheckState.OK,
                     _("This connection has no enabled station links."),
                     True),
                    0)

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
            return (CheckState.OK, message, True, link), 0
        if stale == total:
            return ((CheckState.FAILED,
                     _("All %(total)d enabled station(s) have stale data — no "
                       "recent observations within the connection's freshness "
                       "limit.") % counts,
                     True, link),
                    stale)
        return ((CheckState.WARNING,
                 _("%(stale)d of %(total)d enabled stations have stale data — "
                   "no recent observations within the connection's freshness "
                   "limit.") % counts,
                 True, link),
                stale)


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
