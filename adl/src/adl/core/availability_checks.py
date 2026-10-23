"""
The availability-check contract: "does the source have data for this window?"

Distinct from the **source check** (:mod:`adl.core.source_checks`), which asks
whether the source is reachable and offers anything for a station at all. An
availability check is scoped to a *gap window* of one station link and is
answered in one of two tiers:

- **listing** — the plugin's own cheap answer from
  ``StationLink.check_availability(start, end)``, e.g. an FTP file listing.
- **fetch** — the core fallback, which works for every plugin: fetch and parse
  the window through ``get_station_data``, count what is there, save nothing.

Core stamps the tier itself; a plugin cannot claim one. A plugin's return is
never trusted: :func:`normalise_availability_check_result` degrades anything
malformed to ``MALFORMED`` rather than letting a buggy plugin break the page
or put an invented category into stored history.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from django.utils.translation import gettext as _

from .classification import FAILURE_CATEGORIES
from .redaction import redact_secrets
from .source_checks import SourceCheckStatus

# Which tier answered. Stored on every result, so never rename these values.
TIER_LISTING = "listing"
TIER_FETCH = "fetch"
TIERS = (TIER_LISTING, TIER_FETCH)


@dataclass(frozen=True)
class AvailabilityRange:
    """A time range the source covers, at the source's natural granularity:
    a daily file is one 24 h range, a 10-minute file a 10-minute one.
    ``count`` is the number of records or files when the source knows it;
    ``label`` carries things like a file name."""

    start: datetime
    end: datetime
    count: Optional[int] = None
    label: str = ""


@dataclass(frozen=True)
class AvailabilityCheckResult:
    """
    The frozen result of one availability check. ``category`` draws from the
    shared failure vocabulary and may be ``None``. ``parameter_coverage`` maps
    an ADL parameter id to the UTC hour starts in which the source has a value
    for it; only the fetch tier can populate it.
    """

    status: str
    ranges: Tuple[AvailabilityRange, ...] = ()
    parameter_coverage: Optional[Dict[int, Tuple[datetime, ...]]] = None
    category: Optional[str] = None
    message: str = ""
    tier: Optional[str] = None


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None \
        and value.utcoffset() is not None


def _malformed(message) -> AvailabilityCheckResult:
    return AvailabilityCheckResult(status=SourceCheckStatus.MALFORMED, message=message)


def _normalise_range(value) -> Optional[AvailabilityRange]:
    """A well-formed range from a ``(start, end, count, label)`` tuple or an
    :class:`AvailabilityRange`, or ``None`` when it is neither."""
    if isinstance(value, AvailabilityRange):
        value = (value.start, value.end, value.count, value.label)
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    start, end, count, label = value
    if not (_aware(start) and _aware(end)) or not start < end:
        return None
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        return None
    if not isinstance(label, str):
        return None
    return AvailabilityRange(start, end, count, redact_secrets(label))


def _normalise_coverage(value) -> Tuple[bool, Optional[Dict[int, Tuple[datetime, ...]]]]:
    if value is None:
        return True, None
    if not isinstance(value, dict):
        return False, None
    coverage = {}
    for parameter_id, hours in value.items():
        if isinstance(parameter_id, bool) or not isinstance(parameter_id, int):
            return False, None
        if not isinstance(hours, (tuple, list)) or not all(_aware(hour) for hour in hours):
            return False, None
        coverage[parameter_id] = tuple(hours)
    return True, coverage


def normalise_availability_check_result(value, tier=TIER_LISTING) -> AvailabilityCheckResult:
    """
    Return a well-formed :class:`AvailabilityCheckResult` for any plugin
    return, stamped with ``tier``.

    A non-result value, an unknown status, or malformed ranges or coverage
    degrade to ``MALFORMED``. An unknown category is dropped (the status
    survives). The message is redacted here, once, for every plugin.
    """
    if not isinstance(value, AvailabilityCheckResult):
        return replace(_malformed(
            _("The plugin returned %(type)s instead of an AvailabilityCheckResult.")
            % {"type": type(value).__name__}), tier=tier)
    if value.status not in SourceCheckStatus.ALL:
        return replace(_malformed(
            _("The plugin returned an unknown status %(status)r.")
            % {"status": value.status}), tier=tier)

    if not isinstance(value.ranges, (tuple, list)):
        return replace(_malformed(_("The plugin returned ranges that are not a list.")),
                       tier=tier)
    ranges: List[AvailabilityRange] = []
    for item in value.ranges:
        normalised = _normalise_range(item)
        if normalised is None:
            return replace(_malformed(
                _("The plugin returned a malformed availability range.")), tier=tier)
        ranges.append(normalised)

    valid, coverage = _normalise_coverage(value.parameter_coverage)
    if not valid:
        return replace(_malformed(
            _("The plugin returned malformed per-parameter coverage.")), tier=tier)

    category = value.category if value.category in FAILURE_CATEGORIES else None
    return AvailabilityCheckResult(
        status=value.status,
        ranges=tuple(ranges),
        parameter_coverage=coverage,
        category=category,
        message=redact_secrets(value.message if isinstance(value.message, str) else ""),
        tier=tier,
    )


def station_link_implements_check_availability(station_link) -> bool:
    """True when the station link's class overrides ``check_availability()``
    — answerable without any I/O, which is what decides the button's wording
    (instant or background) before anything is dialled."""
    from adl.core.models import StationLink
    return type(station_link).check_availability is not StationLink.check_availability
