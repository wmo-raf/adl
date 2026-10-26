import calendar
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from celery.result import AsyncResult
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _

from adl.core.availability_checks import TIER_FETCH, TIER_LISTING
from adl.core.models import NetworkConnection, StationLink
from adl.core.models import DispatchChannel
from adl.core.permissions import can_manage_channel, can_manage_connection
from adl.core.source_checks import SourceCheckStatus
from .. import gap_service
from ..availability import (
    SORT_MISSING,
    SORT_NAME,
    connection_availability,
    day_availability,
    month_availability,
    whole_day_window,
)

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


def _grid_url(connection_id, year, month, sort):
    params = {"connection": connection_id, "month": _month_param(year, month)}
    if sort == SORT_NAME:
        params["sort"] = SORT_NAME
    return f"{reverse('data_availability')}?{urlencode(params)}"


def _grid_rows(summaries, running):
    """Template rows of a connection grid: label link plus a day link per cell,
    and the check or recovery running for the link, if any (``running`` maps
    station link id to it)."""
    return [
        {
            "summary": summary,
            "running": running.get(summary.station_link.id),
            "month_url": _availability_url(
                summary.station_link.id, summary.days[0].date.year, summary.days[0].date.month
            ),
            "cells": [(day, _day_url(summary.station_link.id, day.date)) for day in summary.days],
        }
        for summary in summaries
    ]


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


def _matrix_rows(day_detail, overlay):
    """The day view's rows, any-parameter row first, each cell paired with what
    the stored availability checks say about it."""
    def build(row, is_any):
        parameter_id = None if is_any else row.parameter.id
        return {
            "is_any": is_any,
            "parameter": row.parameter,
            "parameter_id": parameter_id,
            "mapped": row.mapped,
            "cells": [
                {"cell": cell, "mark": overlay.cells.get((parameter_id, cell.start))}
                for cell in row.cells
            ],
        }

    return [build(day_detail.any_row, True)] + [build(row, False) for row in day_detail.rows]


def _span_label(start, end):
    """``06:00–12:00`` for a window in local time; a window that ends at midnight
    of a later day reads ``24:00``, so a whole day is ``00:00–24:00``."""
    end_text = "24:00" if end.date() > start.date() and end.time() == time(0, 0) \
        else end.strftime("%H:%M")
    return f"{start.strftime('%H:%M')}\u2013{end_text}"


def _check_items(overlay, tz, can_check=False):
    """The stored checks of the day, with their window in the station's local time."""
    items = [
        {
            "summary": summary,
            "check": summary.check,
            "local_start": summary.check.window_start.astimezone(tz),
            "local_end": summary.check.window_end.astimezone(tz),
            "span": _span_label(summary.check.window_start.astimezone(tz),
                                summary.check.window_end.astimezone(tz)),
            "by_listing": summary.check.tier == TIER_LISTING,
            "by_fetch": summary.check.tier == TIER_FETCH,
            "ok": summary.check.status == SourceCheckStatus.OK,
            # a listing that did not answer never falls through by itself; the
            # operator asks for the expensive fetch explicitly
            "can_fetch_instead": can_check
            and summary.check.tier == TIER_LISTING
            and summary.check.status != SourceCheckStatus.OK,
        }
        for summary in overlay.summaries
    ]
    # newest first: a later check that overlaps the window supersedes a failed one
    for index, item in enumerate(items):
        item["can_fetch_instead"] = item["can_fetch_instead"] and not any(
            newer["check"].window_start < item["check"].window_end
            and newer["check"].window_end > item["check"].window_start
            for newer in items[:index]
        )
    return items


def _whole_day(station_link, day, overlay):
    """The whole-day check on offer for ``day``, or ``None`` when no mapped
    parameter is missing. ``checked`` says an answered check already covers it."""
    window = whole_day_window(station_link, day)
    if window is None:
        return None
    start, end = window
    tz = ZoneInfo(str(station_link.timezone))
    return {
        "local_start": start.astimezone(tz),
        "local_end": end.astimezone(tz),
        "span": _span_label(start.astimezone(tz), end.astimezone(tz)),
        "hours": int((end - start) / timedelta(hours=1)),
        "checked": any(
            summary.check.status == SourceCheckStatus.OK
            and summary.check.window_start <= start
            and summary.check.window_end >= end
            for summary in overlay.summaries
        ),
    }


# The states of the day view's status panel
PANEL_CHECK = "check"
PANEL_RECOVER = "recover"
PANEL_RECOVERED = "recovered"
PANEL_NOTHING = "nothing"
PANEL_FAILED = "failed"
PANEL_RUNNING = "running"


def _day_panel(whole_day, check_items, running=None):
    """What the day view's status panel offers, from the day's newest stored check:
    check the source, recover what a check found, or the outcome of the last step.
    While a check or recovery is in flight for the station link (``running``) it
    shows that instead, whoever started it. ``None`` when no mapped parameter is
    missing."""
    if whole_day is None:
        return None
    if running is not None:
        return {"state": PANEL_RUNNING, "running": running, "latest": None,
                "whole_day": whole_day}
    latest = check_items[0] if check_items else None
    if latest is None:
        state = PANEL_CHECK
    elif not latest["ok"]:
        state = PANEL_FAILED
    elif latest["summary"].verdict != gap_service.HAS_DATA:
        state = PANEL_NOTHING
    elif latest["check"].recovery_saved is not None:
        # a recovery ran (even one that saved nothing): report it and ask the
        # source afresh rather than offering the same recovery again
        state = PANEL_RECOVERED
    else:
        state = PANEL_RECOVER
    return {"state": state, "latest": latest, "whole_day": whole_day}


def _late_dispatch(user, station_link, check_items):
    """The channels the newest check's recovered window may be sent to, for a user
    who may manage them; ``None`` when that check was not recovered."""
    latest = check_items[0]["check"] if check_items else None
    if latest is None or not latest.recovered:
        return None
    channels = [channel for channel in gap_service.late_dispatch_channels(station_link)
                if can_manage_channel(user, channel)]
    return {"check": latest, "channels": channels} if channels else None


def data_availability(request):
    """Month calendar of a station link's data availability, or the connection
    grid of all its links when only a connection is chosen.

    All state lives in the query string (``connection``, ``station_link``,
    ``month`` as ``YYYY-MM``, ``sort`` as ``name`` for the grid, ``day`` as ``YYYY-MM-DD``); a valid ``day`` shows
    that day's hour matrix instead of the month calendar; anything unknown or malformed is ignored, so
    every URL renders.
    """
    station_link = None
    link_id = _positive_int(request.GET.get("station_link"))
    if link_id:
        station_link = (
            # no select_related on the polymorphic connection: it would load the
            # base class, hiding the plugin subclass' ``variable_mappings``
            StationLink.objects.filter(id=link_id).select_related("station").first()
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
            "running_url": reverse("availability_running"),
        })
        running = gap_service.in_flight(station_link.id)
        if running is not None and running.day and (running.day.year, running.day.month) == (year, month):
            context["running"] = running
            context["watch_running"] = not day

        if day:
            day_detail = day_availability(station_link, day)
            overlay = gap_service.day_check_overlay(station_link, day_detail)
            context["day_detail"] = day_detail
            context["matrix_rows"] = _matrix_rows(day_detail, overlay)
            can_check = (
                station_link.network_connection.has_external_source
                and can_manage_connection(request.user, station_link.network_connection)
            )
            context["can_check"] = can_check
            context["check_instant"] = station_link.availability_check_supported
            context["check_url"] = reverse("availability_check")
            if can_check:
                context["whole_day"] = _whole_day(station_link, day, overlay)
            context["check_items"] = _check_items(
                overlay, ZoneInfo(str(station_link.timezone)), can_check)
            if can_check:
                context["late_dispatch"] = _late_dispatch(
                    request.user, station_link, context["check_items"])
                context["panel"] = _day_panel(
                    context["whole_day"], context["check_items"],
                    running=gap_service.in_flight(station_link.id))


    elif connection_id:
        connection = connections.get(id=connection_id)
        today = dj_timezone.localtime(dj_timezone.now(), ZoneInfo(str(connection.stations_timezone)))
        year, month = _parse_month(request.GET.get("month")) or (today.year, today.month)
        sort = SORT_NAME if request.GET.get("sort") == SORT_NAME else SORT_MISSING
        grid = connection_availability(connection, station_links, year, month, sort=sort)
        running = gap_service.in_flight_many([link.id for link in station_links])
        prev_year, prev_month = _shift_month(year, month, -1)
        next_year, next_month = _shift_month(year, month, 1)
        context.update({
            "grid": grid,
            "grid_rows": _grid_rows(grid.rows, running),
            "grid_disabled_rows": _grid_rows(grid.disabled_rows, running),
            "grid_days": list(range(1, grid.days_in_month + 1)),
            "grid_sort": sort,
            "month_start": date(year, month, 1),
            "prev_url": _grid_url(connection_id, prev_year, prev_month, sort),
            "next_url": _grid_url(connection_id, next_year, next_month, sort),
            "sort_missing_url": _grid_url(connection_id, year, month, SORT_MISSING),
            "sort_name_url": _grid_url(connection_id, year, month, SORT_NAME),
        })

    return render(request, "monitoring/data_availability.html", context)


def _json_error(message, status):
    return JsonResponse({"error": str(message)}, status=status)


def _parse_instant(value):
    """An aware datetime from an ISO-8601 string (``Z`` allowed), or ``None``."""
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _managed_station_link(request, link_id):
    """The station link, or a ``PermissionDenied``/``None``: the check actions
    are gated on managing its connection, which holds the credentials the
    action will use."""
    station_link = StationLink.objects.filter(id=link_id).first() if link_id else None
    if station_link is None:
        return None
    if not can_manage_connection(request.user, station_link.network_connection):
        raise PermissionDenied
    return station_link


@require_POST
def availability_check(request):
    """Ask the source whether it has data for a whole local day of a station link.

    ``station_link`` and ``day`` (``YYYY-MM-DD``, the station link's local day,
    trimmed to its missing mapped hours), optionally ``fetch=1`` (skip the cheap
    check and fetch the data). Answers ``{"state": "SUCCESS", "check_id": ...}``
    when the listing tier answered at once, or ``{"state": "PENDING", "task_id":
    ...}`` when a background task will; poll :func:`availability_check_status`.
    """
    station_link = _managed_station_link(request, _positive_int(request.POST.get("station_link")))
    if station_link is None:
        return _json_error(_("Unknown station link."), 404)

    day = _parse_day(request.POST.get("day"))
    if day is None:
        return _json_error(_("Unknown day."), 400)

    try:
        outcome = gap_service.check_whole_day(
            station_link, day, force_fetch=request.POST.get("fetch") == "1")
    except gap_service.CheckInFlight as exc:
        return _json_error(exc, 409)
    except gap_service.CheckCoolingDown as exc:
        return _json_error(exc, 429)
    except gap_service.GapServiceError as exc:
        return _json_error(exc, 400)

    if outcome.check is not None:
        return JsonResponse({"state": "SUCCESS", "tier": outcome.tier,
                             "check_id": outcome.check.id})
    return JsonResponse({"state": "PENDING", "tier": outcome.tier, "task_id": outcome.task_id})


@require_GET
def availability_check_status(request, task_id):
    """The state of a background availability check, for the page to poll.

    ``station_link`` must be given and manageable by the user, and the stored
    result must belong to it, so a task id alone reveals nothing.
    """
    station_link = _managed_station_link(request, _positive_int(request.GET.get("station_link")))
    if station_link is None:
        return _json_error(_("Unknown station link."), 404)

    result = AsyncResult(task_id)
    if result.state == "SUCCESS":
        from ..models import AvailabilityCheck
        if not AvailabilityCheck.objects.filter(
                id=result.result, station_link=station_link).exists():
            return _json_error(_("Unknown task."), 404)
        return JsonResponse({"state": "SUCCESS", "check_id": result.result})
    if result.state in ("FAILURE", "REVOKED"):
        # the failure text may carry a secret; the stored result, not the task, reports causes
        return JsonResponse({"state": "FAILURE", "message": str(
            _("The availability check could not run to completion. See the application logs."))})
    return JsonResponse({"state": "PENDING"})


@require_POST
def availability_recover(request):
    """Ingest the window of a stored check that found data.

    ``station_link`` and ``check`` (the stored check's id). Answers
    ``{"state": "PENDING", "task_id": ...}``; poll
    :func:`availability_recover_status`. Needs ``can_manage_connection``.
    """
    station_link = _managed_station_link(request, _positive_int(request.POST.get("station_link")))
    if station_link is None:
        return _json_error(_("Unknown station link."), 404)

    check_id = _positive_int(request.POST.get("check"))
    if check_id is None:
        return _json_error(_("Unknown check."), 400)

    try:
        task_id = gap_service.recover(station_link, check_id)
    except gap_service.CheckInFlight as exc:
        return _json_error(exc, 409)
    except gap_service.GapServiceError as exc:
        return _json_error(exc, 400)
    return JsonResponse({"state": "PENDING", "task_id": task_id})


@require_GET
def availability_recover_status(request, task_id):
    """The state of a background recovery, for the page to poll: ``SUCCESS`` with
    the ``fetched`` and ``saved`` counts, ``BUSY`` when a scheduled pull held the
    station's lock, ``FAILURE`` or ``PENDING``. Scoped to a manageable station
    link like :func:`availability_check_status`."""
    station_link = _managed_station_link(request, _positive_int(request.GET.get("station_link")))
    if station_link is None:
        return _json_error(_("Unknown station link."), 404)

    result = AsyncResult(task_id)
    if result.state == "SUCCESS":
        report = result.result
        if not isinstance(report, dict) or report.get("station_link") != station_link.id:
            return _json_error(_("Unknown task."), 404)
        if report["busy"]:
            return JsonResponse({"state": "BUSY", "message": str(
                _("The station is busy with a scheduled pull. Try again in a moment."))})
        return JsonResponse({"state": "SUCCESS", "fetched": report["fetched"],
                             "saved": report["saved"]})
    if result.state in ("FAILURE", "REVOKED"):
        return JsonResponse({"state": "FAILURE", "message": str(
            _("The recovery could not run to completion. See the application logs."))})
    return JsonResponse({"state": "PENDING"})


@require_POST
def availability_send_window(request):
    """Send a recovered check's window to a dispatch channel (late dispatch).

    ``station_link``, ``check`` (the recovered check's id) and ``channel``. Never
    automatic. Answers ``{"state": "PENDING", "task_id": ...}``; poll
    :func:`availability_send_window_status`. Needs both ``can_manage_connection``
    and ``can_manage_channel``.
    """
    station_link = _managed_station_link(request, _positive_int(request.POST.get("station_link")))
    if station_link is None:
        return _json_error(_("Unknown station link."), 404)

    channel_id = _positive_int(request.POST.get("channel"))
    channel = DispatchChannel.objects.filter(id=channel_id).first() if channel_id else None
    if channel is None:
        return _json_error(_("Unknown dispatch channel."), 400)
    if not can_manage_channel(request.user, channel):
        raise PermissionDenied

    check_id = _positive_int(request.POST.get("check"))
    if check_id is None:
        return _json_error(_("Unknown check."), 400)

    try:
        task_id = gap_service.send_window(station_link, check_id, channel.id)
    except gap_service.GapServiceError as exc:
        return _json_error(exc, 400)
    return JsonResponse({"state": "PENDING", "task_id": task_id})


@require_GET
def availability_send_window_status(request, task_id):
    """The state of a background late dispatch, for the page to poll: ``SUCCESS``
    with the ``sent`` count, ``BUSY`` when a normal dispatch held the station's
    lock, ``FAILURE`` or ``PENDING``. Scoped like :func:`availability_recover_status`."""
    station_link = _managed_station_link(request, _positive_int(request.GET.get("station_link")))
    if station_link is None:
        return _json_error(_("Unknown station link."), 404)

    result = AsyncResult(task_id)
    if result.state == "SUCCESS":
        report = result.result
        if not isinstance(report, dict) or report.get("station_link") != station_link.id:
            return _json_error(_("Unknown task."), 404)
        if report["busy"]:
            return JsonResponse({"state": "BUSY", "message": str(
                _("The channel is busy dispatching this station. Try again in a moment."))})
        return JsonResponse({"state": "SUCCESS", "sent": report["sent"]})
    if result.state in ("FAILURE", "REVOKED"):
        return JsonResponse({"state": "FAILURE", "message": str(
            _("The dispatch could not run to completion. See the activity log."))})
    return JsonResponse({"state": "PENDING"})


@require_GET
def availability_running(request):
    """Whether a check or recovery is running for a station link, for a page that
    shows it to poll: ``{"running": bool, "kind": ..., "since": ..., "day": ...}``.
    Read-only status, so open to anyone who can see the availability pages; the
    actions it reports on stay gated on ``can_manage_connection``."""
    link_id = _positive_int(request.GET.get("station_link"))
    if not link_id or not StationLink.objects.filter(id=link_id).exists():
        return _json_error(_("Unknown station link."), 404)

    running = gap_service.in_flight(link_id)
    if running is None:
        return JsonResponse({"running": False})
    return JsonResponse({
        "running": True, "kind": running.kind,
        "since": running.since.isoformat() if running.since else None,
        "day": running.day.isoformat() if running.day else None,
    })
