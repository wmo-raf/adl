from datetime import timedelta

from django.contrib.humanize.templatetags.humanize import naturaltime
from django.urls import reverse
from django.utils import timezone as dj_timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from adl.core.models import NetworkConnection, ObservationRecord
from adl.core.utils import get_object_or_none
from adl.monitoring.models import StationLinkActivityLog


def compute_status(log: StationLinkActivityLog | None):
    if not log:
        return "warning"
    
    reference_time = log.obs_end_time or log.time
    age = dj_timezone.now() - reference_time
    
    if (
            age > timedelta(minutes=20)
            or not log.success
            or log.status != StationLinkActivityLog.ActivityStatus.COMPLETED
    ):
        return "warning"
    
    return "active"


class NetworkConnectionActivityView(APIView):
    def get(self, request, connection_id):
        connection = get_object_or_none(NetworkConnection, id=connection_id)
        if not connection:
            return Response({"error": "Connection not found"}, status=404)
        
        # Fetch station links
        station_links = connection.station_links.select_related("station")
        
        # --- Fetch latest activity logs per station link
        latest_logs = (
            StationLinkActivityLog.objects
            .filter(station_link__in=station_links)
            .order_by("station_link", "-time")
            .distinct("station_link")
        )
        
        logs_map = {log.station_link_id: log for log in latest_logs}
        
        # --- Fetch latest observation records per station (fallback)
        latest_obs = (
            ObservationRecord.objects
            .filter(
                station__in=[sl.station for sl in station_links],
                connection=connection
            )
            .order_by("station", "-time")
            .distinct("station")
        )
        obs_map = {o.station_id: o for o in latest_obs}
        
        stations_output = []
        summary = {"active": 0, "warning": 0, }
        
        data_viewer_url = reverse("viewer_table"),
        
        for sl in station_links:
            log = logs_map.get(sl.id)
            obs = obs_map.get(sl.station_id)
            shown_time = obs.time
            
            # ========= Compute status =========
            status = compute_status(log) if log else "warning"
            summary[status] += 1
            
            # ========= Human readable =========
            last_collected_human = naturaltime(shown_time) if shown_time else None
            last_check_human = naturaltime(log.time)
            
            station_link_monitoring_url = reverse(
                "station_link_monitoring",
                args=(sl.id,)
            )
            
            station_link_monitoring_url += f"?direction=pull"
            
            stations_output.append({
                "id": sl.id,
                "name": sl.station.name,
                "status": status,
                "last_check": log.time,
                "last_check_human": last_check_human,
                "last_collected": shown_time,
                "last_collected_human": last_collected_human,
                "log_id": log.id if log else None,
                "logs_url": station_link_monitoring_url,
                "data_viewer_url": data_viewer_url,
            })
        
        return Response({
            "connection": {
                "id": connection.id,
                "name": connection.name,
                "enabled": connection.enabled,
                "interval_minutes": connection.interval,
                "plugin": connection.plugin_name,
            },
            "summary": summary,
            "stations": stations_output,
        })
