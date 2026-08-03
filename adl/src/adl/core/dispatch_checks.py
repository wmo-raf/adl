"""
Core-side containment for :meth:`DispatchChannel.test_connection`.

``test_connection()`` is documented on the base class as returning a dict and
never raising, but every implementation past ``Wis2BoxUpload`` lives in an
independently-versioned plugin repo that upgrades on its own schedule. The
contract had already drifted on its first out-of-core implementation —
``adl-s3-plugin`` returned a ``(bool, str)`` tuple, and the admin's "Test
connection" button raised ``TypeError`` on ``result["supported"]`` rather than
reporting anything at all.

So core does not trust the return. :func:`run_dispatch_connection_test` calls
the channel and passes whatever comes back through
:func:`normalise_dispatch_test_result`, which reports a non-conforming return
as a channel-side failure naming the offending type. The next plugin to drift
degrades to a legible message instead of a 500.

Mirrors :mod:`adl.core.source_checks` on the ingestion side (decision #152),
without converging on its ``SourceCheckResult`` shape — that retrofit reaches
into sibling plugin repos and was deliberately left out of scope there.
"""

import logging
import time
from collections.abc import Mapping

from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

# Keys a conforming `test_connection()` must supply. `latency_ms` is not
# among them: the caller times the call anyway, so an omitted latency is
# filled in rather than treated as a broken result.
REQUIRED_RESULT_KEYS = ("ok", "supported", "message")


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
        "message": str(value["message"]),
        "latency_ms": _coerce_latency(value.get("latency_ms"), measured_ms),
    }


def _coerce_latency(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def run_dispatch_connection_test(channel):
    """
    Probe ``channel``'s destination and return a well-formed result dict.

    Both failure modes the base-class docstring only asks implementations to
    avoid are contained here: a raised exception becomes a reported failure,
    and a non-conforming return becomes a malformed-result message. The
    probe's own time bound is still the implementation's to keep.
    """
    channel_type = type(channel).__name__
    started = time.monotonic()

    def elapsed_ms():
        return int((time.monotonic() - started) * 1000)

    try:
        raw = channel.test_connection()
    except Exception as e:
        logger.exception("[DISPATCH TEST] %s raised for channel %s", channel_type, channel.id)
        return {
            "ok": False,
            "supported": True,
            "message": _("The connection test raised %(type)s: %(error)s")
                       % {"type": type(e).__name__, "error": e},
            "latency_ms": elapsed_ms(),
        }

    return normalise_dispatch_test_result(
        raw, channel_type=channel_type, measured_ms=elapsed_ms()
    )
