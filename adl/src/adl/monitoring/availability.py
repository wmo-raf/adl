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

from adl.core.models import HourlyObsAgg

COMPLETE = "complete"
PARTIAL = "partial"
EMPTY = "empty"
NOT_EXPECTED = "not_expected"

# Partial days are shaded in this many steps of growing intensity
INTENSITY_LEVELS = 4

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class DayAvailability:
    date: date
    expected_hours: int
    present_hours: int

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


def month_availability(station_link, year, month, now=None):
    """Per-local-day availability of ``station_link`` for one calendar month."""
    now = (now or dj_timezone.now()).astimezone(py_tz.utc)
    tz = ZoneInfo(str(station_link.timezone))
    floor = _availability_floor(station_link)

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

    elapsed_until = _floor_hour(now)
    days = []
    for index in range(days_in_month):
        lo = _ceil_hour(boundaries[index])
        hi = min(_ceil_hour(boundaries[index + 1]), elapsed_until)
        if floor is None:
            # nothing is expected anywhere without a floor
            lo = hi
        else:
            lo = max(lo, floor)

        expected = max(0, int((hi - lo) / HOUR))
        present = bisect_left(buckets, hi) - bisect_left(buckets, lo) if expected else 0
        days.append(DayAvailability(
            date=date(year, month, index + 1),
            expected_hours=expected,
            present_hours=present,
        ))

    return MonthAvailability(
        year=year,
        month=month,
        timezone_name=str(station_link.timezone),
        days=days,
        floor=floor,
    )
