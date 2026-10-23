"""
The gap service: ask the source whether it has data for a gap window.

``check`` validates the window an operator selected in the day view, then
answers it in one of two tiers (see :mod:`adl.core.availability_checks`):

- **listing** — the station link's own cheap ``check_availability()``, run
  synchronously under the shared probe wall clock;
- **fetch** — the core fallback for every plugin: a Celery task fetches and
  parses the window through ``get_station_data``, counts records per hour and
  per parameter, and **saves nothing**.

Every answer is stored as an :class:`~adl.monitoring.models.AvailabilityCheck`.
Only one check can be in flight per station link; the claim is taken in the
cache before anything is dialled or enqueued, because the point is to never
flood a partner host with sessions.

Core, not the plugin, intersects the covered ranges with the window's missing
hours (:func:`covered_missing_hours`).
"""

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as py_tz
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _

from adl.core.availability_checks import (
    TIER_FETCH,
    TIER_LISTING,
    AvailabilityCheckResult,
    AvailabilityRange,
    normalise_availability_check_result,
)
from adl.core.classification import classify_failure
from adl.core.probes import PROBE_WALL_CLOCK_SECONDS, ProbeTimeout, run_bounded
from adl.core.redaction import redact_secrets
from adl.core.source_checks import SourceCheckStatus
from .availability import HOUR, MISSING, _mapped_parameters, missing_hours
from .models import AvailabilityCheck

logger = logging.getLogger(__name__)

# A claim outlives any single check; the task releases it as soon as it ends,
# so this only bounds how long a killed worker can block the station link.
INFLIGHT_SECONDS = 15 * 60


class GapServiceError(Exception):
    """Base of the refusals a caller reports to the operator."""


class InvalidWindow(GapServiceError):
    """The window is not exactly a run of missing hours of one local day."""


class CheckUnavailable(GapServiceError):
    """The connection has no external source to ask."""


class CheckInFlight(GapServiceError):
    """A check or recovery is already running for this station link."""


def inflight_key(station_link_id):
    """The cache key of the per-station-link in-flight claim, shared by every
    long-running gap action so that only one runs at a time."""
    return f"availability-inflight-{station_link_id}"


@dataclass(frozen=True)
class GapWindow:
    start: datetime  # UTC, hour aligned
    end: datetime
    parameter_id: Optional[int]  # the selected row; ``None`` for any-parameter

    @property
    def hours(self) -> List[datetime]:
        count = int((self.end - self.start) / HOUR)
        return [self.start + HOUR * offset for offset in range(count)]


@dataclass(frozen=True)
class CheckOutcome:
    """What ``check`` did: a stored ``check`` (answered now), or the ``task_id``
    of the fetch-tier task that will store one."""

    tier: str
    check: Optional[AvailabilityCheck] = None
    task_id: Optional[str] = None


def validate_window(station_link, start, end, parameter_id=None, now=None) -> GapWindow:
    """The :class:`GapWindow` for exactly the selected run, or ``InvalidWindow``.

    The window must be hour aligned, lie within one local day, belong to a
    currently mapped parameter row (unmapped rows cannot create a window), and
    consist only of missing hours of that row.
    """
    for value in (start, end):
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise InvalidWindow(_("The window must have aware start and end times."))
    start, end = start.astimezone(py_tz.utc), end.astimezone(py_tz.utc)
    if not start < end:
        raise InvalidWindow(_("The window must end after it starts."))
    for value in (start, end):
        if value.minute or value.second or value.microsecond:
            raise InvalidWindow(_("The window must start and end on the hour."))

    tz = ZoneInfo(str(station_link.timezone))
    if start.astimezone(tz).date() != (end - timedelta(microseconds=1)).astimezone(tz).date():
        raise InvalidWindow(_("A check window cannot be longer than one local day."))

    if parameter_id is not None and parameter_id not in {
        parameter.id for parameter in _mapped_parameters(station_link)
    }:
        raise InvalidWindow(_("Only a currently mapped parameter can be checked."))

    window = GapWindow(start, end, parameter_id)
    missing = missing_hours(station_link, start, end, parameter_id, now=now)
    if missing != window.hours:
        raise InvalidWindow(_("The window must be a run of missing hours."))
    return window


def covered_missing_hours(ranges, missing) -> List[datetime]:
    """The ``missing`` hour starts that any of ``ranges`` overlaps, even
    partially: a source holding one 10-minute file in an hour has data for
    that hour."""
    return [
        hour for hour in missing
        if any(r.start < hour + HOUR and r.end > hour for r in ranges)
    ]


def check_ranges(check: AvailabilityCheck) -> List[AvailabilityRange]:
    return [
        AvailabilityRange(
            start=datetime.fromisoformat(item["start"]),
            end=datetime.fromisoformat(item["end"]),
            count=item.get("count"),
            label=item.get("label", ""),
        )
        for item in check.ranges or []
    ]


def check_parameter_hours(check: AvailabilityCheck):
    """``{parameter id: set of UTC hour starts}`` of a stored check, or ``None``
    when it carries no per-parameter coverage."""
    if check.parameter_coverage is None:
        return None
    return {
        int(parameter_id): {datetime.fromisoformat(hour) for hour in hours}
        for parameter_id, hours in check.parameter_coverage.items()
    }


def _failed(exc_or_message, category=None) -> AvailabilityCheckResult:
    if isinstance(exc_or_message, BaseException):
        category = classify_failure(exc_or_message)[0]
        message = _("The availability check raised %(type)s: %(error)s") % {
            "type": type(exc_or_message).__name__, "error": redact_secrets(exc_or_message)}
    else:
        message = exc_or_message
    return AvailabilityCheckResult(
        status=SourceCheckStatus.FAILED, category=category, message=message)


def _local(station_link, value):
    return value.astimezone(ZoneInfo(str(station_link.timezone)))


def run_listing_check(station_link, window) -> AvailabilityCheckResult:
    """Tier 1: the plugin's own answer, bounded by the probe wall clock and
    normalised. A raise or a timeout is a ``FAILED`` result, not a crash."""
    try:
        raw = run_bounded(
            lambda: station_link.check_availability(
                _local(station_link, window.start), _local(station_link, window.end)),
            PROBE_WALL_CLOCK_SECONDS,
        )
    except ProbeTimeout:
        return normalise_availability_check_result(_failed(
            _("The availability check did not complete within the probe's "
              "%(seconds)s-second budget.") % {"seconds": PROBE_WALL_CLOCK_SECONDS}),
            TIER_LISTING)
    except Exception as exc:
        logger.exception("[AVAILABILITY CHECK] check_availability raised for station link %s",
                         station_link.id)
        return normalise_availability_check_result(_failed(exc), TIER_LISTING)
    return normalise_availability_check_result(raw, TIER_LISTING)


def run_fetch_check(station_link, window) -> AvailabilityCheckResult:
    """Tier 2: fetch and parse the window, count what the source has per hour
    and per mapped parameter, and discard the records. Saves nothing."""
    tz = ZoneInfo(str(station_link.timezone))
    mappings = list(station_link.get_variable_mappings() or [])
    try:
        records = station_link.plugin.get_station_data(
            station_link,
            start_date=window.start.astimezone(tz),
            end_date=window.end.astimezone(tz),
        )

        per_hour = Counter()
        per_parameter = {}
        for record in records or []:
            if not isinstance(record, dict):
                continue
            observed = record.get("observation_time")
            if not isinstance(observed, datetime):
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=tz)
            observed = observed.astimezone(py_tz.utc)
            if not window.start <= observed < window.end:
                continue
            hour = observed.replace(minute=0, second=0, microsecond=0)
            for mapping in mappings:
                if record.get(mapping.source_parameter_name) is None:
                    continue
                per_hour[hour] += 1
                parameter_id = getattr(mapping, "adl_parameter_id", None)
                if parameter_id is None:
                    parameter_id = mapping.adl_parameter.id
                per_parameter.setdefault(parameter_id, Counter())[hour] += 1
    except Exception as exc:
        logger.exception("[AVAILABILITY CHECK] fetch failed for station link %s", station_link.id)
        return normalise_availability_check_result(_failed(exc), TIER_FETCH)

    ranges = tuple(
        AvailabilityRange(hour, hour + HOUR, count, "") for hour, count in sorted(per_hour.items())
    )
    coverage = {
        parameter.id: tuple(sorted(per_parameter.get(parameter.id, {})))
        for parameter in _mapped_parameters(station_link)
    }
    return normalise_availability_check_result(AvailabilityCheckResult(
        status=SourceCheckStatus.OK,
        ranges=ranges,
        parameter_coverage=coverage,
        message=_("Fetched and parsed %(records)s record(s) for %(hours)s hour(s).") % {
            "records": sum(per_hour.values()), "hours": len(per_hour)},
    ), TIER_FETCH)


def store_result(station_link, window, result, now=None) -> AvailabilityCheck:
    coverage = None
    if result.parameter_coverage is not None:
        coverage = {
            str(parameter_id): [hour.astimezone(py_tz.utc).isoformat() for hour in hours]
            for parameter_id, hours in result.parameter_coverage.items()
        }
    return AvailabilityCheck.objects.create(
        station_link=station_link,
        window_start=window.start,
        window_end=window.end,
        created_at=now or dj_timezone.now(),
        tier=result.tier,
        status=result.status,
        category=result.category,
        message=result.message,
        ranges=[
            {"start": r.start.isoformat(), "end": r.end.isoformat(),
             "count": r.count, "label": r.label}
            for r in result.ranges
        ],
        parameter_coverage=coverage,
    )


def release(station_link_id):
    cache.delete(inflight_key(station_link_id))


def check(station_link, start, end, parameter_id=None, force_fetch=False, now=None) -> CheckOutcome:
    """Ask the source whether it has data for the window.

    Raises :class:`InvalidWindow`, :class:`CheckUnavailable` or
    :class:`CheckInFlight` for a refusal. The in-flight claim is taken before
    anything is dialled or enqueued, and released when the check ends.

    A listing result of ``FAILED`` or ``MALFORMED`` is stored and reported as
    is — it never falls through to the expensive fetch tier by itself; the
    caller asks for that explicitly with ``force_fetch``. Only ``UNSUPPORTED``
    (this link cannot answer cheaply) goes straight to the fetch tier.
    """
    from .tasks import run_availability_check

    window = validate_window(station_link, start, end, parameter_id, now=now)
    if not station_link.network_connection.has_external_source:
        raise CheckUnavailable(_("This connection has no external source to check."))

    if not cache.add(inflight_key(station_link.id), "check", timeout=INFLIGHT_SECONDS):
        raise CheckInFlight(
            _("A check or recovery is already running for this station link."))

    try:
        if station_link.availability_check_supported and not force_fetch:
            result = run_listing_check(station_link, window)
            if result.status != SourceCheckStatus.UNSUPPORTED:
                stored = store_result(station_link, window, result, now=now)
                release(station_link.id)
                return CheckOutcome(tier=TIER_LISTING, check=stored)

        task = run_availability_check.delay(
            station_link.id, window.start.isoformat(), window.end.isoformat(), parameter_id)
    except BaseException:
        release(station_link.id)
        raise
    return CheckOutcome(tier=TIER_FETCH, task_id=task.id)


def run_fetch_task(station_link_id, start_iso, end_iso, parameter_id) -> int:
    """The body of the fetch-tier Celery task; returns the stored check's id.
    Releases the in-flight claim however it ends."""
    from adl.core.models import StationLink

    try:
        station_link = StationLink.objects.select_related("network_connection").get(
            id=station_link_id)
        window = GapWindow(datetime.fromisoformat(start_iso), datetime.fromisoformat(end_iso),
                           parameter_id)
        result = run_fetch_check(station_link, window)
        return store_result(station_link, window, result).id
    finally:
        release(station_link_id)


# ---- rendering overlay -----------------------------------------------------

HAS_DATA = "has_data"
NOTHING = "nothing"


@dataclass(frozen=True)
class CheckSummary:
    check: AvailabilityCheck
    missing_total: int
    covered: int
    parameter_counts: List[Tuple[object, int]]  # (parameter, hours the source has)

    @property
    def answered(self):
        return self.check.status == SourceCheckStatus.OK

    @property
    def verdict(self):
        if not self.answered:
            return None
        return HAS_DATA if self.covered else NOTHING


@dataclass(frozen=True)
class DayCheckOverlay:
    # (parameter id or None, hour start) -> HAS_DATA / NOTHING, for missing cells
    cells: dict
    summaries: List[CheckSummary]  # newest first


def day_check_overlay(station_link, day_detail) -> DayCheckOverlay:
    """What the stored checks say about the day's missing cells.

    The latest check covering an hour applies to it; a check whose window no
    longer has a missing cell is not shown. A check that answered ``OK`` marks
    each missing cell in its window as the source having data or nothing; a
    fetch-tier check with per-parameter coverage answers parameter rows
    exactly, otherwise a row falls back to the any-parameter ranges.
    """
    rows = [(None, day_detail.any_row)] + [(row.parameter.id, row) for row in day_detail.rows]
    missing_by_row = {
        key: {cell.start for cell in row.cells if cell.state == MISSING} for key, row in rows
    }
    all_missing = set().union(*missing_by_row.values()) if missing_by_row else set()
    if not all_missing:
        return DayCheckOverlay(cells={}, summaries=[])

    day_start = min(cell.start for cell in day_detail.any_row.cells)
    day_end = max(cell.start for cell in day_detail.any_row.cells) + HOUR
    checks = list(AvailabilityCheck.objects.filter(
        station_link=station_link, window_start__lt=day_end, window_end__gt=day_start,
    ).order_by("created_at", "id"))

    parameters = {row.parameter.id: row.parameter for row in day_detail.rows}
    cells = {}
    summaries = []
    for check in checks:  # oldest first, so the latest overwrites
        window_missing = {hour for hour in all_missing
                          if check.window_start <= hour < check.window_end}
        if not window_missing:
            continue
        answered = check.status == SourceCheckStatus.OK
        ranges = check_ranges(check)
        by_parameter = check_parameter_hours(check)

        covered_any = set(covered_missing_hours(ranges, sorted(window_missing)))
        if answered:
            for key, _row in rows:
                for hour in missing_by_row[key] & window_missing:
                    if key is not None and by_parameter is not None and key in by_parameter:
                        has = hour in by_parameter[key]
                    else:
                        has = hour in covered_any
                    cells[(key, hour)] = HAS_DATA if has else NOTHING

        parameter_counts = []
        if answered and by_parameter:
            for parameter_id, hours in by_parameter.items():
                if parameter_id in parameters:
                    count = len({h for h in hours if check.window_start <= h < check.window_end})
                    parameter_counts.append((parameters[parameter_id], count))
        summaries.append(CheckSummary(
            check=check,
            missing_total=len(window_missing),
            covered=len(covered_any) if answered else 0,
            parameter_counts=parameter_counts,
        ))

    summaries.reverse()
    return DayCheckOverlay(cells=cells, summaries=summaries)
