"""
The source-check contract behind the ingestion diagnostic's external layers
(4 — network path, 5 — source).

The contract lives on :class:`~adl.core.models.NetworkConnection`, not on
``Plugin``: a plugin overrides ``get_source_endpoint()`` (host and port) and
``check_source()`` (a read-only, connection-scoped "does the source accept
our credentials and offer data" call). Core owns the generic DNS -> TCP
probe built on the endpoint, so no plugin ever implements layer 4 itself.

Nothing here runs on a schedule. Probing partner hosts on a timer across 26
deployments risks IP bans, so :func:`run_source_probe` is fired on demand
only, from the diagnostic page.

A plugin's return is never trusted: every result passes through
:func:`normalise_source_check_result`, which degrades anything malformed to
``MALFORMED`` rather than letting a buggy plugin crash the diagnostic or
smuggle an invented category into stored history.
"""

import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, replace
from typing import Optional, Tuple

from django.utils.translation import gettext as _

from .classification import FAILURE_CATEGORIES

logger = logging.getLogger(__name__)

# One probe may take at most this long, wall clock, across DNS, TCP and the
# plugin's own source check together
PROBE_WALL_CLOCK_SECONDS = 15

# Stable identifiers for the three probe steps — these become stored
# `SourceProbeResult.check_id` values, so they must never be renamed
CHECK_DNS = "dns_resolution"
CHECK_TCP = "tcp_connect"
CHECK_SOURCE = "source_check"


class SourceCheckStatus:
    """The closed status vocabulary of a source-check result."""

    OK = "OK"
    FAILED = "FAILED"
    # The plugin does not implement this contract
    UNSUPPORTED = "UNSUPPORTED"
    # The plugin returned something that is not a well-formed result; core
    # refuses to trust it
    MALFORMED = "MALFORMED"

    ALL = (OK, FAILED, UNSUPPORTED, MALFORMED)


@dataclass(frozen=True)
class SourceCheckResult:
    """
    The frozen result of one source check. ``category`` draws from the flat
    failure vocabulary shared with write-time classification
    (:data:`adl.core.classification.FAILURE_CATEGORIES`) and may be ``None``
    when the producer declines to claim one.
    """

    status: str
    category: Optional[str] = None
    message: str = ""
    latency_ms: Optional[int] = None


@dataclass(frozen=True)
class ProbeStep:
    """One executed probe step, with the diagnostic layer stamped by the
    producer: 4 for the network path, 5 for the source."""

    check_id: str
    layer: int
    result: SourceCheckResult


def normalise_source_check_result(value) -> SourceCheckResult:
    """
    Return a well-formed :class:`SourceCheckResult` for any plugin return.

    A non-result value, or one carrying an unknown status, degrades to
    ``MALFORMED``. An unknown category is dropped (the status survives) —
    a plugin cannot extend the shared vocabulary from outside.
    """
    if not isinstance(value, SourceCheckResult):
        return SourceCheckResult(
            status=SourceCheckStatus.MALFORMED,
            message=_("The plugin returned %(type)s instead of a SourceCheckResult.")
                    % {"type": type(value).__name__},
        )
    if value.status not in SourceCheckStatus.ALL:
        return SourceCheckResult(
            status=SourceCheckStatus.MALFORMED,
            message=_("The plugin returned an unknown status %(status)r.")
                    % {"status": value.status},
        )
    if value.category is not None and value.category not in FAILURE_CATEGORIES:
        return replace(value, category=None)
    return value


def connection_implements_check_source(connection) -> bool:
    """True when the connection's plugin overrides ``check_source()`` —
    answerable without performing any I/O, which is what lets the evaluator
    distinguish "not recently checked" from "not checkable at all"."""
    from adl.core.models import NetworkConnection
    return type(connection).check_source is not NetworkConnection.check_source


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _bounded_call(executor, fn, timeout_seconds):
    """Run ``fn`` with a wall-clock bound. Raises FutureTimeoutError on
    expiry; the abandoned worker thread is left to finish on its own."""
    return executor.submit(fn).result(timeout=max(timeout_seconds, 0.001))


def run_source_probe(connection, timeout_seconds=PROBE_WALL_CLOCK_SECONDS) -> Tuple[ProbeStep, ...]:
    """
    Probe ``connection``'s source on demand: DNS resolution, then a TCP
    connect, then the plugin's own ``check_source()``.

    DNS and TCP are reported **separately**, so a name-resolution fault is
    never presented as a dead host. A step whose predecessor failed is not
    emitted at all — the probe never claims to know something it could not
    have observed. The whole probe shares one wall-clock budget of
    ``timeout_seconds``.
    """
    deadline = time.monotonic() + timeout_seconds

    # Not a context manager: `with` would join abandoned worker threads on
    # exit, letting a stuck DNS lookup or plugin call outlive the wall-clock
    # bound this function promises. Two workers, so a stuck DNS thread
    # cannot queue-starve the later source check.
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        return _probe(connection, executor, deadline, timeout_seconds)
    finally:
        executor.shutdown(wait=False)


def _probe(connection, executor, deadline, timeout_seconds) -> Tuple[ProbeStep, ...]:
    steps = []

    endpoint = connection.get_source_endpoint()
    if endpoint is not None:
        host, port = endpoint

        dns_step = _dns_step(executor, host, port, deadline)
        steps.append(dns_step)
        if dns_step.result.status != SourceCheckStatus.OK:
            return tuple(steps)

        tcp_step = _tcp_step(executor, host, port, deadline)
        steps.append(tcp_step)
        if tcp_step.result.status != SourceCheckStatus.OK:
            return tuple(steps)

    steps.append(_source_step(connection, executor, deadline, timeout_seconds))
    return tuple(steps)


def _dns_step(executor, host, port, deadline) -> ProbeStep:
    started = time.monotonic()
    try:
        _bounded_call(executor, lambda: socket.getaddrinfo(host, port),
                      deadline - time.monotonic())
    except socket.gaierror as e:
        result = SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category="DNS_FAILURE",
            message=_("%(host)s did not resolve: %(error)s")
                    % {"host": host, "error": e},
            latency_ms=_elapsed_ms(started),
        )
    except FutureTimeoutError:
        result = SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category="DNS_FAILURE",
            message=_("Resolving %(host)s did not complete within the probe's "
                      "time budget.") % {"host": host},
            latency_ms=_elapsed_ms(started),
        )
    else:
        result = SourceCheckResult(
            status=SourceCheckStatus.OK,
            message=_("%(host)s resolved.") % {"host": host},
            latency_ms=_elapsed_ms(started),
        )
    return ProbeStep(CHECK_DNS, 4, result)


def _tcp_step(executor, host, port, deadline) -> ProbeStep:
    started = time.monotonic()
    context = {"host": host, "port": port}

    def connect():
        # The socket timeout alone is not the wall-clock bound:
        # create_connection applies it per resolved address, so a
        # multi-homed host that black-holes SYNs could consume it once per
        # address. The executor bound below caps the whole step regardless.
        conn = socket.create_connection(
            (host, port), timeout=max(deadline - time.monotonic(), 0.001)
        )
        conn.close()

    try:
        _bounded_call(executor, connect, deadline - time.monotonic())
    except ConnectionRefusedError:
        result = SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category="TCP_REFUSED",
            message=_("%(host)s refused a TCP connection on port %(port)s.") % context,
            latency_ms=_elapsed_ms(started),
        )
    except (socket.timeout, TimeoutError, FutureTimeoutError):
        result = SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category="TCP_TIMEOUT",
            message=_("A TCP connection to %(host)s:%(port)s timed out.") % context,
            latency_ms=_elapsed_ms(started),
        )
    except OSError as e:
        result = SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category="UNKNOWN",
            message=_("A TCP connection to %(host)s:%(port)s failed: %(error)s")
                    % {**context, "error": e},
            latency_ms=_elapsed_ms(started),
        )
    else:
        result = SourceCheckResult(
            status=SourceCheckStatus.OK,
            message=_("A TCP connection to %(host)s:%(port)s opened.") % context,
            latency_ms=_elapsed_ms(started),
        )
    return ProbeStep(CHECK_TCP, 4, result)


def _source_step(connection, executor, deadline, timeout_seconds) -> ProbeStep:
    started = time.monotonic()
    try:
        raw = _bounded_call(executor, connection.check_source,
                            deadline - time.monotonic())
    except FutureTimeoutError:
        return ProbeStep(CHECK_SOURCE, 5, SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            message=_("The source check did not complete within the probe's "
                      "%(seconds)s-second budget.") % {"seconds": timeout_seconds},
            latency_ms=_elapsed_ms(started),
        ))
    except Exception as e:
        logger.exception("[SOURCE PROBE] check_source raised for connection %s",
                         connection.id)
        return ProbeStep(CHECK_SOURCE, 5, SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            message=_("The source check raised %(type)s: %(error)s")
                    % {"type": type(e).__name__, "error": e},
            latency_ms=_elapsed_ms(started),
        ))

    result = normalise_source_check_result(raw)
    if result.latency_ms is None and result.status != SourceCheckStatus.UNSUPPORTED:
        result = replace(result, latency_ms=_elapsed_ms(started))
    return ProbeStep(CHECK_SOURCE, 5, result)
