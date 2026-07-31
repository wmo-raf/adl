from datetime import datetime

import logging

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _

from adl.core.models import NetworkConnection
from adl.core.source_checks import SourceCheckStatus, run_source_probe

from ..constants import LAYER_LABELS, LAYER_SOURCE, PROBE_LAYER_IDS
from ..health import EVALUATED_LAYERS, evaluate_connection_health, probe_age_minutes
from ..models import NetworkConnectionHealth, SourceProbeResult

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


def source_probe_cooldown_key(connection):
    """
    The cooldown cache key for one connection's source, keyed on the host
    with the **port excluded** — several connections to the same partner
    share one budget. Falls back to the connection id where the endpoint is
    unimplemented.
    """
    try:
        endpoint = connection.get_source_endpoint()
    except Exception:
        # A plugin's endpoint lookup is never trusted to succeed — a raising
        # override must not turn the probe POST into a server error
        logger.exception("[SOURCE PROBE] get_source_endpoint raised for connection %s",
                         connection.id)
        endpoint = None
    if endpoint is not None:
        host, _port = endpoint
        return f"adl_source_probe_cooldown:{host}"
    return f"adl_source_probe_cooldown:connection:{connection.id}"


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
