from datetime import datetime, timedelta

import logging

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _
from wagtail.admin.paginator import WagtailPaginator

from adl.core.broker import get_ingestion_queue_health
from adl.core.models import NetworkConnection, StationLink
from adl.core.tasks import INGESTION_QUEUE_NAME, run_network_plugin
from adl.core.source_checks import (
    SourceCheckStatus,
    run_source_probe,
    run_station_source_check,
)

from ..constants import LAYER_LABELS, LAYER_SOURCE, PROBE_LAYER_IDS
from ..health import EVALUATED_LAYERS, evaluate_connection_health, probe_age_minutes
from ..models import (
    NetworkConnectionHealth,
    NetworkConnectionHealthTransition,
    SourceProbeResult,
)

logger = logging.getLogger(__name__)

# One probe per source host per minute — beneath the noise floor of the
# ingestion already hitting that host. Deliberately different from the
# evaluator's 15-minute freshness window: equalising them would make an
# operator wait 15 minutes to verify a password fix.
PROBE_COOLDOWN_SECONDS = 60

# The permission that gates the probe: someone who can edit a host and its
# credentials can already make the runtime dial them, and a new permission
# would have to be discovered and assigned across 26 deployments
PROBE_PERMISSION = "core.change_networkconnection"

# The manual re-run cooldown is the connection's own processing interval,
# capped here — deliberately stricter than the probe's 60 seconds: one press
# is a full auth cycle per station link, fired precisely when auth may be
# what is broken
MANUAL_RUN_COOLDOWN_CAP_SECONDS = 15 * 60


def _source_host(connection):
    """The connection's source host for cooldown keying, or ``None`` where
    the endpoint is unimplemented or its lookup raises — a plugin's endpoint
    lookup is never trusted to succeed, and a raising override must not turn
    a POST into a server error."""
    try:
        endpoint = connection.get_source_endpoint()
    except Exception:
        logger.exception("[SOURCE PROBE] get_source_endpoint raised for connection %s",
                         connection.id)
        return None
    if endpoint is None:
        return None
    host, _port = endpoint
    return host


def source_probe_cooldown_key(connection):
    """
    The cooldown cache key for one connection's source, keyed on the host
    with the **port excluded** — several connections to the same partner
    share one budget. Falls back to the connection id where the endpoint is
    unimplemented.
    """
    host = _source_host(connection)
    if host is not None:
        return f"adl_source_probe_cooldown:{host}"
    return f"adl_source_probe_cooldown:connection:{connection.id}"


def station_source_check_cooldown_key(station_link):
    """
    The cooldown cache key for one station link's source check, keyed on
    **(host, station link)** and independent of the connection probe —
    host-only keying would hand one station another station's verdict.
    """
    host = _source_host(station_link.network_connection)
    if host is not None:
        return f"adl_station_source_check_cooldown:{host}:{station_link.id}"
    return (f"adl_station_source_check_cooldown:"
            f"connection:{station_link.network_connection_id}:{station_link.id}")


def manual_run_cooldown_key(connection):
    """
    The cooldown cache key for one connection's manual re-run —
    **connection-keyed**, unlike the probe's host key: the run fans out to
    every station link on the connection, so the budget belongs to the
    connection that spends it.
    """
    return f"adl_manual_run_cooldown:connection:{connection.id}"


def manual_run_cooldown_seconds(connection):
    """The connection's processing interval, capped at 15 minutes."""
    return min(connection.interval * 60, MANUAL_RUN_COOLDOWN_CAP_SECONDS)


def latest_run_was_manual(heartbeat):
    """Whether the connection's most recent coordinator run was an operator
    press — the caption predicate: green that came from a manual run must
    say so, or the press reads as evidence of a working schedule."""
    if heartbeat is None or heartbeat.last_manual_run_at is None:
        return False
    return (heartbeat.last_run_at is None
            or heartbeat.last_manual_run_at > heartbeat.last_run_at)


def connection_health(request, connection_id):
    """
    The per-connection ingestion diagnostic page. The checklist is computed
    on this read, so the page is never staler than the moment it was opened —
    but persisting the verdict belongs to the sweep task alone, so a GET has
    no write side effects. The stored row supplies ``since``; before the
    first sweep there is none, which is the day-one state on every
    deployment, and the page renders regardless.
    """
    connection = get_object_or_404(NetworkConnection, id=connection_id)

    checklist = evaluate_connection_health(connection)
    health = NetworkConnectionHealth.objects.filter(connection=connection).first()
    heartbeat = getattr(connection, "heartbeat", None)

    # Hidden rather than disabled when unpermitted or unsupported — and
    # enabled during cooldown: the shared result is the limit, and a
    # countdown would reintroduce the refusal that was rejected
    show_probe_button = (
        request.user.has_perm(PROBE_PERMISSION)
        and connection.source_probe_supported
    )

    layer_groups = [
        {
            "layer": layer,
            "label": LAYER_LABELS[layer],
            "checks": checklist.checks_for_layer(layer),
            # The one button covers both external layers, rendered inside
            # the layers 4-5 block, after the source group
            "probe_button": show_probe_button and layer == LAYER_SOURCE,
        }
        for layer in EVALUATED_LAYERS
    ]

    # Transitions at the bottom of the same page, paginated in place, read
    # from the append-only log. Flapping surfaces as a count of verdict
    # changes over the retained window — the creation row (no prior verdict)
    # is a starting point, not a flap, and rows past retention are excluded
    # even when the daily cleanup has not pruned them yet.
    now = dj_timezone.now()
    retention_days = NetworkConnectionHealthTransition.RETENTION_DAYS
    transitions = connection.health_transitions.order_by("-at")
    verdict_changes = transitions.filter(
        at__gte=now - timedelta(days=retention_days),
        from_status__isnull=False,
    ).count()
    paginator = WagtailPaginator(transitions, 20)
    transitions_page = paginator.get_page(request.GET.get("p", 1))
    transition_rows = [
        {
            "at": transition.at,
            "from_status": transition.from_status,
            "from_layer_label": LAYER_LABELS.get(transition.from_first_failing_layer),
            "to_status": transition.to_status,
            "to_layer_label": LAYER_LABELS.get(transition.to_first_failing_layer),
        }
        for transition in transitions_page
    ]

    context = {
        "breadcrumbs_items": [
            {"url": reverse("wagtailadmin_home"), "label": _("Home")},
            {"url": reverse("connections_list"), "label": _("Network Connections")},
            {"url": None, "label": _("Ingestion Diagnostic — %(name)s") % {"name": connection.name}},
        ],
        "header_title": _("Ingestion Diagnostic — %(name)s") % {"name": connection.name},
        "header_icon": "crosshairs",
        "connection": connection,
        "checklist": checklist,
        "health": health,
        "first_failing_layer_label": LAYER_LABELS.get(checklist.first_failing_layer),
        "layer_groups": layer_groups,
        # Hidden rather than disabled, like the probe button — and hidden on
        # a disabled connection: there is nothing to run
        "show_run_button": (request.user.has_perm(PROBE_PERMISSION)
                            and connection.enabled),
        "latest_run_was_manual": latest_run_was_manual(heartbeat),
        "heartbeat": heartbeat,
        "transitions_page": transitions_page,
        "transition_rows": transition_rows,
        "elided_page_range": paginator.get_elided_page_range(transitions_page.number),
        "verdict_changes": verdict_changes,
        "transitions_retention_days": retention_days,
    }
    return render(request, "monitoring/connection_health.html", context=context)


def _parse_claim(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def connection_probe_source(request, connection_id):
    """
    Fire the on-demand source probe (layers 4-5) for one connection —
    synchronously, in the web process, following the dispatch
    test-connection pattern: a wedged ingestion queue must not be able to
    mask a source health check.

    The cooldown is claimed with an atomic cache add **before** the probe
    fires. The TTL is never extended on completion and never released early,
    including when the probe raises — so a press inside the cooldown always
    resolves to one of two answers, never an error: the stored result with
    its age and origin, or a distinct "probe in flight" message.
    """
    connection = get_object_or_404(NetworkConnection, id=connection_id)

    if not request.user.has_perm(PROBE_PERMISSION):
        raise PermissionDenied

    diagnostic_page = redirect("connection_health", connection_id=connection.id)
    if request.method != "POST":
        return diagnostic_page

    if not connection.source_probe_supported:
        messages.warning(
            request,
            _("This plugin does not implement the source-check contract, so "
              "there is nothing to probe."),
        )
        return diagnostic_page

    now = dj_timezone.now()
    key = source_probe_cooldown_key(connection)
    if not cache.add(key, now.isoformat(), timeout=PROBE_COOLDOWN_SECONDS):
        _report_existing_probe(request, connection, cache.get(key), now)
        return diagnostic_page

    try:
        steps = run_source_probe(connection)
    except Exception:
        # The claim stays: a crashed probe still dialled the host, so the
        # budget is spent either way
        logger.exception("[SOURCE PROBE] Probe crashed for connection %s", connection.id)
        messages.error(
            request,
            _("The probe could not run to completion. See the application "
              "logs for the cause."),
        )
        return diagnostic_page

    for step in steps:
        SourceProbeResult.objects.create(
            connection=connection,
            station_link=None,
            check_id=step.check_id,
            layer=PROBE_LAYER_IDS[step.layer],
            status=step.result.status,
            category=step.result.category,
            message=step.result.message,
            latency_ms=step.result.latency_ms,
            at=now,
        )

    _report_probe_outcome(request, steps)
    return diagnostic_page


def _report_existing_probe(request, connection, claim, now):
    """A press inside the cooldown: the shared result is the limit, so the
    answer is the stored result (with its age and origin) or the in-flight
    state — never a refusal."""
    claimed_at = _parse_claim(claim)
    newest = (SourceProbeResult.objects
              .filter(connection=connection, station_link__isnull=True)
              .order_by("-at")
              .first())

    if newest is not None and (claimed_at is None or newest.at >= claimed_at):
        messages.info(
            request,
            _("Probed %(minutes)d minute(s) ago (on-demand probe): "
              "%(message)s — one probe per source host per minute; this "
              "shared result is the limit.")
            % {"minutes": probe_age_minutes(now, newest.at),
               "message": newest.message},
        )
    else:
        # Claimed but no result yet. Usually a probe is still running; a
        # crashed probe leaves this same state until the claim expires, so
        # the message promises a retry window, never a result
        messages.info(
            request,
            _("A probe for this source was started less than a minute ago "
              "and has not recorded a result yet. Refresh shortly, or try "
              "again in a minute."),
        )


def _running_ingestion_tasks_for(connection):
    """Ingestion tasks the workers report as currently executing for this
    connection, or ``()`` when none — including when the broker did not
    answer: unknown must not block the press, the cooldown still protects
    the source.

    Matching on ``args[0]`` requires that both ingestion task signatures
    (``run_network_plugin`` and ``process_station_link_batch``) keep the
    connection id as their first argument; a batch still executing counts
    as a run in flight."""
    observation = get_ingestion_queue_health()
    tasks = observation.running_tasks or ()
    return tuple(task for task in tasks
                 if task.args and task.args[0] == connection.id)


def connection_run_now(request, connection_id):
    """
    Trigger an ingestion run immediately — "run the tick now", nothing
    narrower or wider. The press enqueues the **coordinator task** on the
    real ingestion queue, so a successful run proves the workers are alive;
    the run itself is byte-identical to a scheduled one (start date, batch
    size, per-station timeout, batch clamp all come from the coordinator).

    ``manual=True`` changes only the heartbeat write: the press stamps
    ``last_manual_run_at``, never ``last_run_at``, so a manual run cannot
    make the scheduler layer look healthy.

    The in-flight state is the primary limiter — a press while a run is
    executing shows the running one instead of queueing duplicate work (the
    worker's per-station lock writes the pull-side SKIPPED row on any
    collision that slips through). Below that sits a connection-keyed
    cooldown of the processing interval capped at 15 minutes, deliberately
    stricter than the probe's: one press is an auth cycle per station link.
    """
    connection = get_object_or_404(NetworkConnection, id=connection_id)

    if not request.user.has_perm(PROBE_PERMISSION):
        raise PermissionDenied

    diagnostic_page = redirect("connection_health", connection_id=connection.id)
    if request.method != "POST":
        return diagnostic_page

    if not connection.enabled:
        messages.warning(
            request,
            _("Ingestion for this connection is disabled — enable it before "
              "running it."),
        )
        return diagnostic_page

    running = _running_ingestion_tasks_for(connection)
    if running:
        ages = [task.age_seconds for task in running if task.age_seconds is not None]
        if ages:
            message = _("An ingestion run for this connection is already "
                        "running (started %(minutes)d minute(s) ago). Its "
                        "outcome will appear in the activity log.") \
                      % {"minutes": int(max(ages) // 60)}
        else:
            message = _("An ingestion run for this connection is already "
                        "running. Its outcome will appear in the activity log.")
        messages.info(request, message)
        return diagnostic_page

    now = dj_timezone.now()
    key = manual_run_cooldown_key(connection)
    if not cache.add(key, now.isoformat(),
                     timeout=manual_run_cooldown_seconds(connection)):
        claimed_at = _parse_claim(cache.get(key))
        minutes = probe_age_minutes(now, claimed_at) if claimed_at else 0
        messages.info(
            request,
            _("A manual run was triggered %(minutes)d minute(s) ago. The "
              "cooldown is the connection's processing interval, capped at "
              "15 minutes — check the activity log for that run's outcome.")
            % {"minutes": minutes},
        )
        return diagnostic_page

    run_network_plugin.apply_async(
        args=[connection.id],
        kwargs={"manual": True},
        queue=INGESTION_QUEUE_NAME,
    )
    messages.success(
        request,
        _("Ingestion run enqueued on the real queue — it runs exactly as a "
          "scheduled tick would. Results will appear in the activity log."),
    )
    return diagnostic_page


def _station_link_page(station_link):
    """Redirect back to the station link's inspect page — the page the
    check button lives on. Falls back to the monitoring timeline where the
    inspect viewset is not registered for this model."""
    from adl.core.utils import get_url_for_station_link
    try:
        return redirect(get_url_for_station_link(station_link, "inspect",
                                                 takes_args=True))
    except Exception:
        return redirect("station_link_monitoring", link_id=station_link.id)


def station_link_check_source(request, link_id):
    """
    Run the on-demand station-scope source check (layer 5) for **one**
    station link — synchronously, one station at a time, with no fan-out
    anywhere: 27 stations means 27 connect/auth/list cycles, and a burst of
    failed authentications is what actually trips a ban.

    Cooldown mechanics mirror the connection probe, but the key is
    **(host, station link)** — one station's press must never answer for
    another's. The result persists against the same probe-result model with
    the station-link FK set; the connection evaluator filters those rows
    out by query, so this check can never move the connection's verdict.
    """
    station_link = get_object_or_404(StationLink, id=link_id)

    if not request.user.has_perm(PROBE_PERMISSION):
        raise PermissionDenied

    inspect_page = _station_link_page(station_link)
    if request.method != "POST":
        return inspect_page

    if not station_link.station_source_check_supported:
        messages.warning(
            request,
            _("This plugin does not implement the station source check, so "
              "there is nothing to run."),
        )
        return inspect_page

    now = dj_timezone.now()
    key = station_source_check_cooldown_key(station_link)
    if not cache.add(key, now.isoformat(), timeout=PROBE_COOLDOWN_SECONDS):
        _report_existing_station_check(request, station_link, cache.get(key), now)
        return inspect_page

    try:
        step = run_station_source_check(station_link)
    except Exception:
        # The claim stays: a crashed check still dialled the host, so the
        # budget is spent either way
        logger.exception("[SOURCE PROBE] Station check crashed for station link %s",
                         station_link.id)
        messages.error(
            request,
            _("The station source check could not run to completion. See "
              "the application logs for the cause."),
        )
        return inspect_page

    SourceProbeResult.objects.create(
        connection=station_link.network_connection,
        station_link=station_link,
        check_id=step.check_id,
        layer=PROBE_LAYER_IDS[step.layer],
        status=step.result.status,
        category=step.result.category,
        message=step.result.message,
        latency_ms=step.result.latency_ms,
        at=now,
    )

    _report_station_check_outcome(request, step)
    return inspect_page


def _report_existing_station_check(request, station_link, claim, now):
    """A press inside the cooldown: the shared result is the limit, so the
    answer is this station's own stored result (with its age and origin) or
    the in-flight state — never a refusal."""
    claimed_at = _parse_claim(claim)
    newest = (SourceProbeResult.objects
              .filter(station_link=station_link)
              .order_by("-at")
              .first())

    if newest is not None and (claimed_at is None or newest.at >= claimed_at):
        messages.info(
            request,
            _("Checked %(minutes)d minute(s) ago (on-demand station check): "
              "%(message)s — one check per station per minute; this shared "
              "result is the limit.")
            % {"minutes": probe_age_minutes(now, newest.at),
               "message": newest.message},
        )
    else:
        messages.info(
            request,
            _("A check for this station was started less than a minute ago "
              "and has not recorded a result yet. Refresh shortly, or try "
              "again in a minute."),
        )


def _report_station_check_outcome(request, step):
    result = step.result
    if result.status == SourceCheckStatus.FAILED:
        messages.error(request, result.message)
    elif result.status == SourceCheckStatus.OK:
        # Zero matches is OK by design: the resolved path and match count
        # in the message let the operator judge better than a rule can
        messages.success(request, result.message)
    else:
        messages.warning(
            request,
            _("The check ran, but the plugin did not return a usable result."),
        )


def _report_probe_outcome(request, steps):
    failed = [s for s in steps if s.result.status == SourceCheckStatus.FAILED]
    if failed:
        first = failed[0]
        messages.error(request, first.result.message)
        return
    ok = [s for s in steps if s.result.status == SourceCheckStatus.OK]
    if ok:
        messages.success(
            request,
            _("Source probe completed: %(count)d check(s) passed.")
            % {"count": len(ok)},
        )
    else:
        messages.warning(
            request,
            _("The probe ran, but the plugin did not return a usable result."),
        )
