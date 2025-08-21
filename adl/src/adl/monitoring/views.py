from datetime import timedelta

from adl.core.models import NetworkConnection, DispatchChannel
from adl.core.utils import get_object_or_none
from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from django_celery_results.models import TaskResult
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .constants import NETWORK_PLUGIN_TASK_NAME
from .models import StationLinkActivityLog
from .serializers import TaskResultSerializer, StationLinkActivityLogSerializer


@api_view()
def get_network_conn_plugin_task_results_since(request, network_conn_id, from_date=None):
    if from_date:
        from_date = parse_datetime(from_date)
        
        if not from_date:
            return Response({"error": "Invalid date format. Please provide a valid date format."}, status=400)
        
        if dj_timezone.is_naive(from_date):
            from_date = dj_timezone.make_aware(from_date)
    else:
        # use the beginning of today
        from_date = dj_timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    
    network_conn_task_name = f"{NETWORK_PLUGIN_TASK_NAME}({network_conn_id})"
    
    queryset = TaskResult.objects.filter(
        periodic_task_name=network_conn_task_name,
        date_done__gte=from_date
    ).order_by("date_done")
    
    latest_record = queryset.last()
    
    serialized_data = TaskResultSerializer(queryset, many=True).data
    
    response = {
        "latest_record": TaskResultSerializer(latest_record).data if latest_record else None,
        "data": serialized_data
    }
    
    return Response(response)


# Settings you can tweak
MAX_LOOKBACK_DAYS = 30  # hard limit
MAX_RANGE_DAYS = 7  # per-request cap


def _clamp_to_bounds(start, end, now):
    # hard min/max
    hard_min = now - timedelta(days=MAX_LOOKBACK_DAYS)
    hard_max = now + timedelta(days=1)  # allow slight pan into near future
    # clamp
    start = max(start, hard_min)
    end = min(end, hard_max)
    # cap max span
    if (end - start) > timedelta(days=MAX_RANGE_DAYS):
        end = start + timedelta(days=MAX_RANGE_DAYS)
    return start, end, hard_min, hard_max


@api_view(["GET"])
def get_station_activity_log(request, connection_id):
    """
    Range-based activity fetch.
    Params:
      - start (ISO8601) inclusive
      - end   (ISO8601) exclusive
      - include_stations (bool) default true (send once, then false for subsequent tiles)
    Defaults:
      start: today at 00:00 (server TZ)
      end:   now (server TZ)
    Constraints:
      - cannot go earlier than now - 30 days
      - per-request range capped to 7 days
    """
    include_stations = request.GET.get("include_stations", "true").lower() != "false"
    
    # Parse start/end
    now = dj_timezone.now()
    start_str = request.GET.get("start")
    end_str = request.GET.get("end")
    
    if start_str:
        start = parse_datetime(start_str)
        if not start:
            return Response({"error": "Invalid 'start' datetime."}, status=status.HTTP_400_BAD_REQUEST)
        if dj_timezone.is_naive(start):
            start = dj_timezone.make_aware(start)
    else:
        # beginning of "today" in server/local time
        local_now = dj_timezone.localtime(now)
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = dj_timezone.make_aware(start) if dj_timezone.is_naive(start) else start
    
    if end_str:
        end = parse_datetime(end_str)
        if not end:
            return Response({"error": "Invalid 'end' datetime."}, status=status.HTTP_400_BAD_REQUEST)
        if dj_timezone.is_naive(end):
            end = dj_timezone.make_aware(end)
    else:
        end = now
    
    # Clamp to bounds & max range
    start, end, hard_min, hard_max = _clamp_to_bounds(start, end, now)
    if end <= start:
        return Response({"error": "'end' must be after 'start'."}, status=status.HTTP_400_BAD_REQUEST)
    #
    # filter_params = {
    #
    # }
    #
    # direction = request.GET.get("direction")
    # if direction in ("pull", "push"):
    #     filter_params["direction"] = direction
    #
    # dispatch_channel_id = request.GET.get("dispatch_channel_id")
    # if dispatch_channel_id:
    #     # Only meaningful for pushes
    #     filter_params["dispatch_channel_id"] = dispatch_channel_id
    
    # Fetch connection & station links
    connection = get_object_or_none(NetworkConnection, id=connection_id)
    if not connection:
        return Response({"error": "Network connection not found."}, status=status.HTTP_404_NOT_FOUND)
    
    station_links = list(connection.station_links.all())
    qs = (StationLinkActivityLog.objects
          .filter(station_link__in=station_links, time__gte=start, time__lt=end)
          .select_related("station_link__station", "dispatch_channel")
          .order_by("time", "id"))
    
    # direction filter
    direction = request.GET.get("direction")
    if direction in ("pull", "push"):
        qs = qs.filter(direction=direction)
    
    # push-only: channel filter
    dispatch_channel_id = request.GET.get("dispatch_channel_id")
    if dispatch_channel_id and direction == "push":
        # Validate channel belongs to this connection
        channel_exists = connection.dispatch_channels.filter(id=dispatch_channel_id).exists()
        if not channel_exists:
            return Response(
                {"error": "dispatch_channel_id not found for this connection."},
                status=status.HTTP_400_BAD_REQUEST
            )
        qs = qs.filter(dispatch_channel_id=dispatch_channel_id)
    
    serialized = StationLinkActivityLogSerializer(qs, many=True).data
    
    payload = {
        "connection": connection.name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "hard_min": hard_min.isoformat(),
        "hard_max": hard_max.isoformat(),
        "activity_log": serialized,
    }
    
    # Stations always useful for groups
    if request.GET.get("include_stations", "true").lower() != "false":
        payload["stations"] = [link.station.name for link in station_links]
        
        # If you want to send channels list once (only for this connection)
    if request.GET.get("include_channels", "false").lower() == "true":
        chans = connection.dispatch_channels.filter(enabled=True).values("id", "name", "public_url").order_by("name")
        payload["dispatch_channels"] = [
            {"id": str(c["id"]), "name": c["name"], "public_url": c["public_url"]} for c in chans
        ]
    
    return Response(payload, status=status.HTTP_200_OK)


def network_connection_monitoring(request, connection_id):
    connection = get_object_or_404(NetworkConnection, id=connection_id)
    
    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("connections_list"), "label": _("Network Connections")},
        {"url": "", "label": _("Network Monitoring")},
    ]
    
    context = {
        "page_title": _("Network Monitoring"),
        "breadcrumbs_items": breadcrumbs_items,
        "network_connection": connection,
        "data_api_base_url": "/monitoring/station-activity"
    }
    
    return render(request, "monitoring/network_monitoring.html", context)


def dispatch_channel_monitoring(request, channel_id):
    channel = get_object_or_404(DispatchChannel, id=channel_id)
    
    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("dispatch_channels_list"), "label": _("Dispatch Channels")},
        {"url": "", "label": _("Dispatch Channel Monitoring")},
    ]
    
    context = {
        "page_title": _("Dispatch Channel Monitoring"),
        "breadcrumbs_items": breadcrumbs_items,
        "channel": channel,
        "data_api_base_url": "/monitoring/station-activity"
    }
    
    return render(request, "monitoring/dispatch_channel_monitoring.html", context)
