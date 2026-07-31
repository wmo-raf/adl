from django.contrib.humanize.templatetags.humanize import naturaltime
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone as dj_timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from adl.core.models import (
    NetworkConnection,
    DispatchChannel,
    StationChannelDispatchStatus
)
from adl.monitoring.constants import LAYER_LABELS
from adl.monitoring.models import StationLinkActivityLog
from adl.monitoring.status import (
    annotate_station_pull_activity,
    compute_station_status,
    connection_thresholds,
    dispatch_channel_thresholds,
)


class NetworkConnectionActivityView(APIView):
    def get(self, request, connection_id):
        # 1. Fetch the Connection
        connection = get_object_or_404(NetworkConnection, id=connection_id)
        
        # Main Query: Fetch StationLinks annotated with the latest
        # timestamps via the shared helper — ONE main SQL query, no N+1
        station_links = annotate_station_pull_activity(
            connection.station_links.select_related("station")
        )
        
        # --- SETUP THRESHOLDS ---

        now = dj_timezone.now()
        thresholds = connection_thresholds(connection)

        # --- PROCESS DATA & CALCULATE STATUS ---
        
        stations_count = station_links.count()
        stations_output = []
        summary = {"active": 0, "warning": 0, "error": 0}
        data_viewer_url_base = reverse("viewer_table")
        
        for sl in station_links:
            # 1. Determine PIPELINE and DATA Status
            status = compute_station_status(
                last_check=sl.last_check,
                last_check_success=sl.last_log_success,
                last_data_time=sl.last_collected,
                thresholds=thresholds,
                now=now,
            )

            # 2. Update Global Summary (Worst-case logic)
            summary[status.overall_status] += 1

            # 3. Generate URLs
            monitor_url = reverse("station_link_monitoring", args=(sl.id,)) + "?direction=pull"
            
            # Format outputs
            stations_output.append({
                "id": sl.id,
                "name": sl.station.name,
                
                # Dual Statuses
                "pipeline_status": status.pipeline_status,
                "data_status": status.data_status,
                
                # Pipeline Data
                "last_check": sl.last_check,
                "last_check_human": naturaltime(sl.last_check) if sl.last_check else None,
                
                # Observation Data
                "last_collected": sl.last_collected,
                "last_collected_human": naturaltime(sl.last_collected) if sl.last_collected else None,
                "data_age_seconds": (now - sl.last_collected).total_seconds() if sl.last_collected else None,
                
                # URLs
                "logs_url": monitor_url,
                "data_viewer_url": data_viewer_url_base,  # You might want to append params here usually
            })
        
        # The stored ingestion-diagnostic verdict — the sweep's row, read
        # as-is. The panel must never trigger an evaluation cascade; before
        # the first sweep there is no row and the status is simply null.
        health = getattr(connection, "health", None)

        return Response({
            "connection": {
                "id": connection.id,
                "name": connection.name,
                "enabled": connection.enabled,
                "interval_minutes": connection.interval,
                "plugin": connection.plugin_name,
                "stations_count": stations_count,
                "health": {
                    "status": health.status if health else None,
                    "first_failing_layer": health.first_failing_layer if health else None,
                    "first_failing_layer_label": (
                        str(LAYER_LABELS.get(health.first_failing_layer, ""))
                        if health and health.first_failing_layer else None
                    ),
                    "since": health.since if health else None,
                    "since_human": naturaltime(health.since) if health else None,
                    "diagnostic_url": reverse("connection_health", args=(connection.id,)),
                },
            },
            "summary": summary,
            "stations": stations_output,
        })


class DispatchChannelMonitoringView(APIView):
    def get(self, request, channel_id):
        channel = get_object_or_404(DispatchChannel, id=channel_id)
        
        # --- 1. PREPARE SUBQUERIES ---
        latest_log_sq = StationLinkActivityLog.objects.filter(
            dispatch_channel=channel,
            station_link=OuterRef('pk'),
            direction='push'
        ).order_by('-time')
        
        latest_dispatch_sq = StationChannelDispatchStatus.objects.filter(
            channel=channel,
            station=OuterRef('station')
        ).values('last_sent_obs_time')[:1]
        
        station_links = channel.stations_allowed_to_send().select_related("station", "network_connection").annotate(
            last_attempt=Subquery(latest_log_sq.values('time')[:1]),
            last_attempt_success=Subquery(latest_log_sq.values('success')[:1]),
            last_sent_obs=Subquery(latest_dispatch_sq)
        )
        
        # --- 2. SETUP THRESHOLDS ---

        now = dj_timezone.now()
        thresholds = dispatch_channel_thresholds(channel)

        # --- 3. PROCESS DATA ---
        
        stations_output = []
        summary = {"active": 0, "warning": 0, "error": 0}
        stations_count = station_links.count()
        
        for sl in station_links:
            status = compute_station_status(
                last_check=sl.last_attempt,
                last_check_success=sl.last_attempt_success,
                last_data_time=sl.last_sent_obs,
                thresholds=thresholds,
                now=now,
            )

            # --- Summary ---
            summary[status.overall_status] += 1

            monitor_url = reverse("station_link_monitoring", args=(sl.id,)) + f"?direction=push&channel={channel.id}"
            
            stations_output.append({
                "id": sl.id,
                "name": sl.station.name,
                "connection_name": sl.network_connection.name,
                "connection_id": sl.network_connection.id,
                
                "pipeline_status": status.pipeline_status,
                "data_status": status.data_status,
                "last_check": sl.last_attempt,
                "last_check_human": naturaltime(sl.last_attempt) if sl.last_attempt else None,
                "last_collected": sl.last_sent_obs,
                "last_collected_human": naturaltime(sl.last_sent_obs) if sl.last_sent_obs else None,
                "logs_url": monitor_url,
                "data_viewer_url": "#",
            })
        
        heartbeat = getattr(channel, "heartbeat", None)

        return Response({
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "enabled": channel.enabled,
                "interval_minutes": channel.data_check_interval,
                "plugin": "Dispatch",
                "stations_count": stations_count,
                "public_url": channel.public_url,
                "last_run_at": heartbeat.last_run_at if heartbeat else None,
                "last_run_human": naturaltime(heartbeat.last_run_at) if heartbeat else None,
                "stations_spawned": heartbeat.stations_spawned if heartbeat else None,
                "overdue": channel.is_dispatch_overdue(now=now),
            },
            "summary": summary,
            "stations": stations_output,
        })
