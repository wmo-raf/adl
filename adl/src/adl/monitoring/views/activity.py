from datetime import timedelta
from django.db.models import OuterRef, Subquery, Value, Case, When

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
        
        # --- 1. Prepare Subqueries ---
        # We prepare the SQL instructions, but they don't run yet.
        
        # Get latest log time for the specific StationLink
        latest_log_time_sq = StationLinkActivityLog.objects.filter(
            station_link=OuterRef('pk')
        ).order_by('-time').values('time')[:1]
        
        latest_log_success_sq = StationLinkActivityLog.objects.filter(
            station_link=OuterRef('pk')
        ).order_by('-time').values('success')[:1]
        
        # Get latest observation time
        latest_obs_time_sq = ObservationRecord.objects.filter(
            station=OuterRef('station'),
            connection=connection
        ).order_by('-time').values('time')[:1]
        
        # --- 2. The Main Query ---
        # We fetch all links and attach the latest dates in a SINGLE database round-trip.
        station_links = connection.station_links.select_related("station").annotate(
            last_check=Subquery(latest_log_time_sq),
            last_log_success=Subquery(latest_log_success_sq),
            last_collected=Subquery(latest_obs_time_sq)
        )
        
        stations_output = []
        summary = {"active": 0, "warning": 0, "error": 0}
        data_viewer_url = reverse("viewer_table")
        
        
        # --- 3. Build Response ---
        for sl in station_links:
            # Logic: If no check ever -> Warning. If check exists -> Active (if success) or Error (if failed)
            status = "warning"
            if sl.last_check is not None:
                status = "active" if sl.last_log_success else "error"
            
            # Update summary counts safely
            summary[status] += 1
            
            # Construct URLs
            monitor_url = reverse("station_link_monitoring", args=(sl.id,)) + "?direction=pull"
            
            stations_output.append({
                "id": sl.id,
                "name": sl.station.name,
                "status": status,
                "last_check": sl.last_check,
                "last_check_human": naturaltime(sl.last_check) if sl.last_check else None,
                "last_collected": sl.last_collected,
                "last_collected_human": naturaltime(sl.last_collected) if sl.last_collected else None,
                "logs_url": monitor_url,
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
