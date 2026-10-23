import calendar
import re
from datetime import date
from zoneinfo import ZoneInfo

from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _

from adl.core.models import NetworkConnection, StationLink
from ..availability import day_availability, month_availability

MONTH_PARAM = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
DAY_PARAM = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_month(value):
    match = MONTH_PARAM.match(value or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return (year, month) if year >= 1900 else None


def _parse_day(value):
    match = DAY_PARAM.match(value or "")
    if not match:
        return None
    year, month, day = (int(group) for group in match.groups())
    if year < 1900:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_param(year, month):
    return f"{year:04d}-{month:02d}"


def _availability_url(station_link_id, year, month):
    return (
        f"{reverse('data_availability')}"
        f"?station_link={station_link_id}&month={_month_param(year, month)}"
    )


def _day_url(station_link_id, day):
    return f"{reverse('data_availability')}?station_link={station_link_id}&day={day.isoformat()}"


def _calendar_weeks(availability, station_link_id):
    """Rows of seven cells, Monday first; ``None`` pads days outside the month.

    Each cell is a ``(day, url)`` pair, the url opening that day's view.
    """
    by_day = {
        day.date.day: (day, _day_url(station_link_id, day.date)) for day in availability.days
    }
    return [
        [by_day.get(day) for day in week]
        for week in calendar.Calendar(firstweekday=0).monthdayscalendar(
            availability.year, availability.month
        )
    ]


def data_availability(request):
    """Month calendar of a station link's data availability.

    All state lives in the query string (``connection``, ``station_link``,
    ``month`` as ``YYYY-MM``, ``day`` as ``YYYY-MM-DD``); a valid ``day`` shows
    that day's hour matrix instead of the month calendar; anything unknown or malformed is ignored, so
    every URL renders.
    """
    station_link = None
    link_id = _positive_int(request.GET.get("station_link"))
    if link_id:
        station_link = (
            StationLink.objects.filter(id=link_id)
            .select_related("network_connection", "station")
            .first()
        )

    connection_id = _positive_int(request.GET.get("connection"))
    if station_link:
        # the link alone is enough: its connection wins over a stale param
        connection_id = station_link.network_connection_id

    connections = NetworkConnection.objects.order_by("name")
    if connection_id and not connections.filter(id=connection_id).exists():
        connection_id = None
    station_links = []
    if connection_id:
        station_links = list(
            StationLink.objects.filter(network_connection_id=connection_id)
            .select_related("station")
            .order_by("station__name")
        )

    context = {
        "breadcrumbs_items": [
            {"url": reverse("wagtailadmin_home"), "label": _("Home")},
            {"url": None, "label": _("Data availability")},
        ],
        "header_title": _("Data availability"),
        "header_icon": "table",
        "connections": connections,
        "connection_id": connection_id,
        "station_links": station_links,
        "station_link": station_link,
    }

    if station_link:
        today = dj_timezone.localtime(dj_timezone.now(), ZoneInfo(str(station_link.timezone)))
        day = _parse_day(request.GET.get("day"))
        if day:
            year, month = day.year, day.month
        else:
            year, month = _parse_month(request.GET.get("month")) or (today.year, today.month)
        availability = month_availability(station_link, year, month)
        prev_year, prev_month = _shift_month(year, month, -1)
        next_year, next_month = _shift_month(year, month, 1)
        context.update({
            "availability": availability,
            "month_start": date(year, month, 1),
            "weeks": _calendar_weeks(availability, station_link.id),
            "weekdays": [date(2024, 1, day) for day in range(1, 8)],  # a Monday-first week
            "prev_url": _availability_url(station_link.id, prev_year, prev_month),
            "next_url": _availability_url(station_link.id, next_year, next_month),
            "month_url": _availability_url(station_link.id, year, month),
            "monitoring_url": reverse("station_link_monitoring", args=[station_link.id]),
        })
        if day:
            context["day_detail"] = day_availability(station_link, day)

    return render(request, "monitoring/data_availability.html", context)
