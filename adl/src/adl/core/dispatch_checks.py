"""
Core-side containment for :meth:`DispatchChannel.test_connection`.

``test_connection()`` is documented on the base class as returning a dict and
never raising, but every implementation past ``Wis2BoxUpload`` lives in an
independently-versioned plugin repo that upgrades on its own schedule. The
contract had already drifted on its first out-of-core implementation —
``adl-s3-plugin`` returned a ``(bool, str)`` tuple, and the admin's "Test
connection" button raised ``TypeError`` on ``result["supported"]`` rather than
reporting anything at all.

So core does not trust the return, and does not trust the clock either.
:func:`run_dispatch_connection_test` calls the channel under the shared
wall-clock bound in :mod:`adl.core.probes` and passes whatever comes back
through :func:`normalise_dispatch_test_result`, which reports a non-conforming
return as a channel-side failure naming the offending type. The next plugin to
drift — in shape or in latency — degrades to a legible message instead of a
500 or a wedged web worker.

Mirrors :mod:`adl.core.source_checks` on the ingestion side (decision #152),
without converging on its ``SourceCheckResult`` shape — that retrofit reaches
into sibling plugin repos and was deliberately left out of scope there.
"""

import logging
import time
from collections.abc import Mapping

from django.utils.translation import gettext as _

from .probes import PROBE_WALL_CLOCK_SECONDS, ProbeTimeout, run_bounded
from .redaction import redact_secrets

logger = logging.getLogger(__name__)

# Keys a conforming `test_connection()` must supply. `latency_ms` is not
# among them: the caller times the call anyway, so an omitted latency is
# filled in rather than treated as a broken result.
REQUIRED_RESULT_KEYS = ("ok", "supported", "message")


def channel_implements_test_connection(channel) -> bool:
    """True when the channel type overrides ``test_connection()``.

    Answerable without performing any I/O, which is what lets a caller tell
    "this press will dial a destination" from "this press cannot dial
    anything" — the base implementation returns its not-supported dict
    without going near the network, so such a press must not spend a
    cooldown budget. Mirrors
    :func:`adl.core.source_checks.connection_implements_check_source`.
    """
    from adl.core.models import DispatchChannel
    return type(channel).test_connection is not DispatchChannel.test_connection


def _malformed(message):
    """A malformed return is the channel's failure, not an unsupported
    channel type: ``supported`` stays True so the admin renders it as an
    error rather than the softer "not supported for this channel type"."""
    return {"ok": False, "supported": True, "message": message, "latency_ms": None}


def normalise_dispatch_test_result(value, channel_type=None, measured_ms=None):
    """
    Return a well-formed test-connection dict for any channel return.

    A non-mapping return, or one missing a required key, is reported as a
    malformed result naming ``channel_type``. Otherwise the verdict is taken
    as given and only coerced: ``ok`` and ``supported`` to bool, ``message``
    to str, and an unreadable ``latency_ms`` to ``measured_ms`` — a bad
    latency should never cost the operator the verdict it accompanies.

    ``measured_ms`` is the caller's own timing of the probe, used whenever
    the channel does not report a usable one. The admin's success message
    renders the latency unconditionally, so leaving it None would put
    "(None ms)" in front of an operator.
    """
    context = {"channel": channel_type or _("The channel")}

    if not isinstance(value, Mapping):
        return _malformed(
            _("%(channel)s returned %(type)s instead of a test-connection dict.")
            % {**context, "type": type(value).__name__}
        )

    missing = [key for key in REQUIRED_RESULT_KEYS if key not in value]
    if missing:
        return _malformed(
            _("%(channel)s returned a test-connection dict missing %(keys)s.")
            % {**context, "keys": ", ".join(missing)}
        )

    return {
        "ok": bool(value["ok"]),
        "supported": bool(value["supported"]),
        # Redacted here rather than at each channel: a plugin's own failure
        # text is the likeliest place for a destination credential to appear,
        # and no channel can be relied on to strip it.
        "message": redact_secrets(str(value["message"])),
        "latency_ms": _coerce_latency(value.get("latency_ms"), measured_ms),
    }


def _coerce_latency(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def run_dispatch_connection_test(channel, timeout_seconds=PROBE_WALL_CLOCK_SECONDS):
    """
    Probe ``channel``'s destination and return a well-formed result dict.

    All three failure modes the base-class docstring asks implementations to
    avoid are contained here: a raised exception becomes a reported failure,
    a non-conforming return becomes a malformed-result message, and a probe
    that outruns ``timeout_seconds`` becomes a failure naming the budget.

    The bound covers the whole call, not the destination-facing request
    inside it — a channel that builds its client eagerly (``adl-s3-plugin``
    dials ``head_bucket`` from ``__init__``) blocks before its own
    ``test_connection`` body reaches any timeout it might set. The abandoned
    worker is left to finish on its own and cannot extend this call.
    """
    channel_type = type(channel).__name__
    started = time.monotonic()

    def elapsed_ms():
        return int((time.monotonic() - started) * 1000)

    try:
        raw = run_bounded(channel.test_connection, timeout_seconds)
    except ProbeTimeout:
        logger.warning(
            "[DISPATCH TEST] %s exceeded the %ss budget for channel %s",
            channel_type, timeout_seconds, channel.id,
        )
        return {
            "ok": False,
            "supported": True,
            "message": _("%(channel)s did not complete its connection test "
                         "within the %(seconds)s-second budget.")
                       % {"channel": channel_type, "seconds": timeout_seconds},
            "latency_ms": elapsed_ms(),
        }
    except Exception as e:
        logger.exception("[DISPATCH TEST] %s raised for channel %s", channel_type, channel.id)
        return {
            "ok": False,
            "supported": True,
            "message": _("The connection test raised %(type)s: %(error)s")
                       % {"type": type(e).__name__, "error": redact_secrets(e)},
            "latency_ms": elapsed_ms(),
        }

    return normalise_dispatch_test_result(
        raw, channel_type=channel_type, measured_ms=elapsed_ms()
    )
