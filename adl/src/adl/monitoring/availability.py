"""
Availability read model: which hours of a station link's history have data.

Everything the Data availability page renders is computed here and returned as
plain data; the view does no availability arithmetic.

Vocabulary (see ``CONTEXT.md``): an hour is *present* when at least one record
exists for any parameter in it; an *expected hour* is an hour from the
station link's *availability floor* up to now; a *gap* is an expected hour
with no record.

Hours are the UTC hour buckets of ``HourlyObsAgg``, the source of truth. A
bucket belongs to the local day its start falls in, so in a zone whose offset
is not a whole number of hours a day holds the buckets starting within it.
"""

from bisect import bisect_left
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as py_tz
from math import ceil
from typing import List, Optional
from zoneinfo import ZoneInfo

from django.db.models import Min
from django.utils import timezone as dj_timezone

from adl.core.models import DataParameter, HourlyObsAgg
from adl.core.source_checks import SourceCheckStatus
from .models import AvailabilityCheck

COMPLETE = "complete"
PARTIAL = "partial"
EMPTY = "empty"
NOT_EXPECTED = "not_expected"

# Hour cell states of the day view
PRESENT = "present"
MISSING = "missing"

# Partial days are shaded in this many steps of growing intensity
INTENSITY_LEVELS = 4

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class DayAvailability:
    date: date
    expected_hours: int
    present_hours: int
    # a currently mapped parameter lacks data in one or more expected hours,
    # even if the day is complete at the any-parameter level
    has_parameter_gap: bool = False
    # the day has gaps and every one lies in the window of a stored, answered
    # availability check
    checked: bool = False

    @property
    def missing_hours(self):
        return self.expected_hours - self.present_hours

    @property
    def state(self):
        if self.expected_hours == 0:
            return NOT_EXPECTED
        if self.present_hours == self.expected_hours:
            return COMPLETE
        if self.present_hours == 0:
            return EMPTY
        return PARTIAL

    @property
    def intensity(self):
        """Share of the expected hours that are gaps, 0 to 1."""
        if not self.expected_hours:
            return 0.0
        return self.missing_hours / self.expected_hours

    @property
    def level(self):
        """``intensity`` in 1..INTENSITY_LEVELS steps, for a partial day."""
        return max(1, min(INTENSITY_LEVELS, ceil(self.intensity * INTENSITY_LEVELS)))

    @property
    def label(self):
        if not self.expected_hours:
            return ""
        return f"{self.present_hours}/{self.expected_hours}"


@dataclass(frozen=True)
class MonthAvailability:
    year: int
    month: int
    timezone_name: str
    days: List[DayAvailability]
    floor: Optional[datetime]


@dataclass(frozen=True)
class HourCell:
    start: datetime  # UTC start of the hour bucket
    local_time: datetime
    state: str
    records_count: int

    @property
    def iso(self):
        """The UTC hour start, as sent back by the check form."""
        return self.start.isoformat()


@dataclass(frozen=True)
class ParameterRow:
    parameter: Optional[object]  # ``None`` for the any-parameter row
    mapped: bool
    cells: List[HourCell]


@dataclass(frozen=True)
class DayDetail:
    date: date
    timezone_name: str
    any_row: ParameterRow
    rows: List[ParameterRow]
    floor: Optional[datetime]


def _floor_hour(value):
    return value.replace(minute=0, second=0, microsecond=0)


def _ceil_hour(value):
    floored = _floor_hour(value)
    return floored if floored == value else floored + HOUR


def _availability_floor(station_link):
    """Start of the first expected hour, or ``None`` when nothing is expected."""
    start_date = station_link.get_first_collection_date()
    if start_date is not None:
        return _floor_hour(start_date.astimezone(py_tz.utc))

    first = HourlyObsAgg.objects.filter(
        station_id=station_link.station_id,
        connection_id=station_link.network_connection_id,
    ).aggregate(first=Min("bucket"))["first"]
    return first.astimezone(py_tz.utc) if first else None


def _mapped_parameters(station_link):
    """Distinct ADL parameters of the link's current variable mappings, in order."""
    parameters = {}
    for mapping in station_link.get_variable_mappings() or []:
        parameter = getattr(mapping, "adl_parameter", None)
        if parameter is not None:
            parameters.setdefault(parameter.id, parameter)
    return list(parameters.values())


def _month_boundaries(year, month, tz):
    """UTC starts of each local day of the month, plus the end of the last."""
    days_in_month = monthrange(year, month)[1]
    boundaries = [
        datetime(year, month, day, tzinfo=tz).astimezone(py_tz.utc)
        for day in range(1, days_in_month + 1)
    ]
    boundaries.append(
        (datetime(year, month, days_in_month, tzinfo=tz) + timedelta(days=1))
        .replace(hour=0, minute=0)
        .astimezone(py_tz.utc)
    )
    return boundaries


def _ok_check_windows(link_ids, start, end):
    """``{station link id: [(window start, window end)]}`` of the answered
    availability checks overlapping ``[start, end)``."""
    windows = {}
    for link_id, window_start, window_end in AvailabilityCheck.objects.filter(
        station_link_id__in=link_ids,
        status=SourceCheckStatus.OK,
        window_start__lt=end,
        window_end__gt=start,
    ).values_list("station_link_id", "window_start", "window_end"):
        windows.setdefault(link_id, []).append(
            (window_start.astimezone(py_tz.utc), window_end.astimezone(py_tz.utc))
        )
    return windows


def _gaps_covered(lo, hi, buckets, parameter_buckets, check_windows):
    """Whether ``[lo, hi)`` has gap hours, all inside a check window.

    A gap hour has no record for any parameter, or lacks a currently mapped
    parameter. Hours that have since filled are no longer gaps, which is what
    makes a result stop counting once its hours are present.
    """
    present = set(buckets[bisect_left(buckets, lo):bisect_left(buckets, hi)])
    per_parameter = [
        set(values[bisect_left(values, lo):bisect_left(values, hi)])
        for values in parameter_buckets.values()
    ]
    gaps = [
        hour
        for hour in (lo + HOUR * offset for offset in range(int((hi - lo) / HOUR)))
        if hour not in present or any(hour not in values for values in per_parameter)
    ]
    return bool(gaps) and all(
        any(start <= hour < end for start, end in check_windows) for hour in gaps
    )


def _month_days(year, month, boundaries, floor, now, buckets, parameter_buckets,
                check_windows=()):
    """Per-day availability from sorted UTC bucket lists.

    ``buckets`` holds the hours with any record, ``parameter_buckets`` maps each
    mapped parameter id to its own sorted hours, ``check_windows`` the
    ``(start, end)`` windows of the link's answered availability checks.
    """
    elapsed_until = _floor_hour(now)
    days = []
    for index in range(len(boundaries) - 1):
        lo = _ceil_hour(boundaries[index])
        hi = min(_ceil_hour(boundaries[index + 1]), elapsed_until)
        if floor is None:
            # nothing is expected anywhere without a floor
            lo = hi
        else:
            lo = max(lo, floor)

        expected = max(0, int((hi - lo) / HOUR))
        present = bisect_left(buckets, hi) - bisect_left(buckets, lo) if expected else 0
        has_gap = bool(expected) and any(
            bisect_left(values, hi) - bisect_left(values, lo) < expected
            for values in parameter_buckets.values()
        )
        days.append(DayAvailability(
            date=date(year, month, index + 1),
            expected_hours=expected,
            present_hours=present,
            has_parameter_gap=has_gap,
            checked=bool(expected) and bool(check_windows)
            and _gaps_covered(lo, hi, buckets, parameter_buckets, check_windows),
        ))
    return days


def month_availability(station_link, year, month, now=None):
    """Per-local-day availability of ``station_link`` for one calendar month."""
    now = (now or dj_timezone.now()).astimezone(py_tz.utc)
    tz = ZoneInfo(str(station_link.timezone))
    floor = _availability_floor(station_link)

    boundaries = _month_boundaries(year, month, tz)
    first_bucket = _ceil_hour(boundaries[0])
    last_bucket_end = _ceil_hour(boundaries[-1])

    buckets = sorted({
        bucket.astimezone(py_tz.utc)
        for bucket in HourlyObsAgg.objects.filter(
            station_id=station_link.station_id,
            connection_id=station_link.network_connection_id,
            bucket__gte=first_bucket,
            bucket__lt=last_bucket_end,
        ).values_list("bucket", flat=True)
    })

    mapped_ids = [parameter.id for parameter in _mapped_parameters(station_link)]
    parameter_buckets = {parameter_id: [] for parameter_id in mapped_ids}
    if mapped_ids:
        rows = HourlyObsAgg.objects.filter(
            station_id=station_link.station_id,
            connection_id=station_link.network_connection_id,
            parameter_id__in=mapped_ids,
            bucket__gte=first_bucket,
            bucket__lt=last_bucket_end,
        ).values_list("parameter_id", "bucket")
        for parameter_id, bucket in rows:
            parameter_buckets[parameter_id].append(bucket.astimezone(py_tz.utc))
        for values in parameter_buckets.values():
            values.sort()

    return MonthAvailability(
        year=year,
        month=month,
        timezone_name=str(station_link.timezone),
        days=_month_days(
            year, month, boundaries, floor, now, buckets, parameter_buckets,
            _ok_check_windows([station_link.id], first_bucket, last_bucket_end).get(station_link.id, ()),
        ),
        floor=floor,
    )


@dataclass(frozen=True)
class LinkMonthSummary:
    station_link: object
    enabled: bool
    timezone_name: str
    days: List[DayAvailability]

    @property
    def expected_hours(self):
        return sum(day.expected_hours for day in self.days)

    @property
    def present_hours(self):
        return sum(day.present_hours for day in self.days)

    @property
    def missing_hours(self):
        return self.expected_hours - self.present_hours

    @property
    def percent(self):
        """Share of expected hours present, 0 to 100; ``None`` when none expected."""
        if not self.expected_hours:
            return None
        # never rounds up to 100 while hours are still missing
        return min(round(100 * self.present_hours / self.expected_hours), 99 if self.missing_hours else 100)

    @property
    def name(self):
        return self.station_link.station.name


@dataclass(frozen=True)
class ConnectionGrid:
    year: int
    month: int
    days_in_month: int
    rows: List[LinkMonthSummary]  # enabled links, in the requested order
    disabled_rows: List[LinkMonthSummary]  # always alphabetical, never ranked


SORT_MISSING = "missing"
SORT_NAME = "name"


def _link_mapped_ids(station_link):
    ids = []
    for mapping in station_link.get_variable_mappings() or []:
        parameter_id = getattr(mapping, "adl_parameter_id", None)
        if parameter_id is None:
            parameter = getattr(mapping, "adl_parameter", None)
            parameter_id = getattr(parameter, "id", None)
        if parameter_id is not None and parameter_id not in ids:
            ids.append(parameter_id)
    return ids


def connection_availability(connection, station_links, year, month, sort=SORT_MISSING, now=None):
    """Month availability of every station link of ``connection``.

    The records of all links are read with one aggregate query (plus one more
    for the first record of links without a collection start date) and rolled
    up in Python. Enabled links are ranked worst-first by missing expected
    hours, or alphabetically for ``sort="name"``; disabled links are listed
    apart, alphabetically.
    """
    now = (now or dj_timezone.now()).astimezone(py_tz.utc)
    station_links = list(station_links)
    days_in_month = monthrange(year, month)[1]
    if not station_links:
        return ConnectionGrid(year, month, days_in_month, [], [])

    def zone_name(link):
        if link.use_connection_timezone:
            return str(connection.stations_timezone)
        return str(link.timezone_info)

    zones = {link.id: ZoneInfo(zone_name(link)) for link in station_links}
    boundaries = {link.id: _month_boundaries(year, month, zones[link.id]) for link in station_links}
    window_start = _ceil_hour(min(b[0] for b in boundaries.values()))
    window_end = _ceil_hour(max(b[-1] for b in boundaries.values()))

    # station id -> {parameter id: [UTC buckets]}
    by_station = {}
    rows = HourlyObsAgg.objects.filter(
        connection_id=connection.id,
        station_id__in=[link.station_id for link in station_links],
        bucket__gte=window_start,
        bucket__lt=window_end,
    ).values_list("station_id", "parameter_id", "bucket")
    for station_id, parameter_id, bucket in rows:
        by_station.setdefault(station_id, {}).setdefault(parameter_id, []).append(
            bucket.astimezone(py_tz.utc)
        )

    start_dates = {link.id: link.get_first_collection_date() for link in station_links}
    first_records = {}
    if any(start is None for start in start_dates.values()):
        first_records = {
            row["station_id"]: row["first"]
            for row in HourlyObsAgg.objects.filter(
                connection_id=connection.id,
                station_id__in=[link.station_id for link in station_links],
            ).values("station_id").annotate(first=Min("bucket"))
        }

    check_windows = _ok_check_windows([link.id for link in station_links], window_start, window_end)

    summaries = []
    for link in station_links:
        start = start_dates[link.id]
        if start is not None:
            floor = _floor_hour(start.astimezone(py_tz.utc))
        else:
            first = first_records.get(link.station_id)
            floor = first.astimezone(py_tz.utc) if first else None

        per_parameter = by_station.get(link.station_id, {})
        buckets = sorted({bucket for values in per_parameter.values() for bucket in values})
        parameter_buckets = {
            parameter_id: sorted(per_parameter.get(parameter_id, []))
            for parameter_id in _link_mapped_ids(link)
        }
        summaries.append(LinkMonthSummary(
            station_link=link,
            enabled=link.enabled,
            timezone_name=str(zones[link.id]),
            days=_month_days(
                year, month, boundaries[link.id], floor, now, buckets, parameter_buckets,
                check_windows.get(link.id, ()),
            ),
        ))

    def by_name(summary):
        return (summary.name.lower(), summary.station_link.id)

    enabled = [summary for summary in summaries if summary.enabled]
    disabled = sorted((summary for summary in summaries if not summary.enabled), key=by_name)
    if sort == SORT_NAME:
        enabled.sort(key=by_name)
    else:
        enabled.sort(key=lambda summary: (-summary.missing_hours, *by_name(summary)))
    return ConnectionGrid(year, month, days_in_month, enabled, disabled)


def day_availability(station_link, day, now=None):
    """Hour-by-hour availability of ``station_link`` for one local day.

    Returns the any-parameter row plus one row per parameter: every currently
    mapped parameter (even with no data) and any other parameter with data
    that day, flagged unmapped. An hour that is not expected is
    ``NOT_EXPECTED`` whatever its data; ``records_count`` is always the
    stored count.
    """
    now = (now or dj_timezone.now()).astimezone(py_tz.utc)
    tz = ZoneInfo(str(station_link.timezone))
    floor = _availability_floor(station_link)

    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    lo = _ceil_hour(start.astimezone(py_tz.utc))
    hi = _ceil_hour((start + timedelta(days=1)).replace(hour=0, minute=0).astimezone(py_tz.utc))
    hours = [lo + HOUR * offset for offset in range(int((hi - lo) / HOUR))]
    elapsed_until = _floor_hour(now)

    counts = {}  # parameter id -> {bucket: records_count}
    for parameter_id, bucket, records_count in HourlyObsAgg.objects.filter(
        station_id=station_link.station_id,
        connection_id=station_link.network_connection_id,
        bucket__gte=lo,
        bucket__lt=hi,
    ).values_list("parameter_id", "bucket", "records_count"):
        counts.setdefault(parameter_id, {})[bucket.astimezone(py_tz.utc)] = records_count

    def expected(hour):
        return floor is not None and floor <= hour < elapsed_until

    def build_row(parameter, mapped, per_hour):
        cells = []
        for hour in hours:
            records_count = per_hour.get(hour, 0)
            if not expected(hour):
                state = NOT_EXPECTED
            else:
                state = PRESENT if records_count else MISSING
            cells.append(HourCell(
                start=hour,
                local_time=hour.astimezone(tz),
                state=state,
                records_count=records_count,
            ))
        return ParameterRow(parameter=parameter, mapped=mapped, cells=cells)

    any_counts = {}
    for per_hour in counts.values():
        for hour, records_count in per_hour.items():
            any_counts[hour] = any_counts.get(hour, 0) + records_count

    mapped = _mapped_parameters(station_link)
    mapped_ids = {parameter.id for parameter in mapped}
    rows = [build_row(parameter, True, counts.get(parameter.id, {})) for parameter in mapped]

    unmapped_ids = [pid for pid in counts if pid not in mapped_ids]
    unmapped = DataParameter.objects.filter(id__in=unmapped_ids).order_by("name")
    rows += [build_row(parameter, False, counts[parameter.id]) for parameter in unmapped]

    return DayDetail(
        date=day,
        timezone_name=str(station_link.timezone),
        any_row=build_row(None, True, any_counts),
        rows=rows,
        floor=floor,
    )


def missing_hours(station_link, start, end, parameter_id=None, now=None):
    """UTC hour starts in ``[start, end)`` that are *missing*: expected, and
    with no record, for any parameter or (given ``parameter_id``) for that one.

    The gap service validates a check window against this, and intersects a
    source's covered ranges with it.
    """
    now = (now or dj_timezone.now()).astimezone(py_tz.utc)
    start = start.astimezone(py_tz.utc)
    end = end.astimezone(py_tz.utc)
    floor = _availability_floor(station_link)
    elapsed_until = _floor_hour(now)

    hours = []
    hour = _ceil_hour(start)
    while hour < end:
        if floor is not None and floor <= hour < elapsed_until:
            hours.append(hour)
        hour += HOUR
    if not hours:
        return []

    records = HourlyObsAgg.objects.filter(
        station_id=station_link.station_id,
        connection_id=station_link.network_connection_id,
        bucket__gte=hours[0],
        bucket__lt=hours[-1] + HOUR,
    )
    if parameter_id is not None:
        records = records.filter(parameter_id=parameter_id)
    present = {bucket.astimezone(py_tz.utc) for bucket in records.values_list("bucket", flat=True)}
    return [hour for hour in hours if hour not in present]


def whole_day_window(station_link, day, now=None):
    """The UTC ``(start, end)`` of a whole-day availability check, or ``None``.

    The span runs from the first to the last hour in which a currently mapped
    parameter is missing. Hours where every mapped parameter is present never
    extend it at the edges, and unmapped parameters never count. ``None``
    means the day has no such hour, so no check is offered.
    """
    detail = day_availability(station_link, day, now=now)
    gap_hours = sorted({
        cell.start
        for row in detail.rows
        if row.mapped
        for cell in row.cells
        if cell.state == MISSING
    })
    if not gap_hours:
        return None
    return gap_hours[0], gap_hours[-1] + HOUR
