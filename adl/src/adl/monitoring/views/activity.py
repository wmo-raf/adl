from datetime import timedelta

from django.contrib.humanize.templatetags.humanize import naturaltime
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone as dj_timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from adl.core.models import NetworkConnection, ObservationRecord
from adl.monitoring.models import StationLinkActivityLog


class NetworkConnectionActivityView(APIView):
    def get(self, request, connection_id):
        # 1. Fetch the Connection
        connection = get_object_or_404(NetworkConnection, id=connection_id)
        
        # --- PREPARE QUERIES ---
        
        # Subquery 1: Latest Activity Log (Pipeline Status)
        # Uses Index: ['station_link', '-time']
        latest_log_sq = StationLinkActivityLog.objects.filter(
            station_link=OuterRef('pk')
        ).order_by('-time')
        
        # Subquery 2: Latest Observation (Data Status)
        # Uses Index: ['connection', 'station', '-time']
        # We must filter by 'connection' to utilize the composite index effectively
        latest_obs_sq = ObservationRecord.objects.filter(
            station=OuterRef('station'),
            connection=connection
        ).order_by('-time')
        
        # Main Query: Fetch StationLinks and annotate with latest timestamps/status
        # This executes ONE main SQL query instead of N+1
        station_links = connection.station_links.select_related("station").annotate(
            last_check=Subquery(latest_log_sq.values('time')[:1]),
            last_log_success=Subquery(latest_log_sq.values('success')[:1]),
            last_collected=Subquery(latest_obs_sq.values('time')[:1])
        )
        
        # --- SETUP THRESHOLDS ---
        
        now = dj_timezone.now()
        
        # A. Pipeline Tolerance (3x the configured interval)
        pipeline_tolerance = timedelta(minutes=connection.interval * 3)
        
        # B. Data Freshness Thresholds
        if connection.is_daily_data:
            # Daily: Active < 26h, Warning < 48h, Error > 48h
            freshness_warning_limit = timedelta(hours=26)
            freshness_error_limit = timedelta(hours=48)
        else:
            # High Frequency: Active < 4x interval, Warning < 12x interval
            freshness_warning_limit = timedelta(minutes=connection.interval * 4)
            freshness_error_limit = timedelta(minutes=connection.interval * 12)
        
        # --- PROCESS DATA & CALCULATE STATUS ---
        
        stations_output = []
        summary = {"active": 0, "warning": 0, "error": 0}
        data_viewer_url_base = reverse("viewer_table")
        
        for sl in station_links:
            # 1. Determine PIPELINE Status
            pipeline_status = "warning"  # Default if never checked
            if sl.last_check:
                time_since_check = now - sl.last_check
                if not sl.last_log_success:
                    pipeline_status = "error"  # Last run crashed
                elif time_since_check > pipeline_tolerance:
                    pipeline_status = "warning"  # Last run ok, but scheduler stopped
                else:
                    pipeline_status = "active"  # Healthy
            
            # 2. Determine DATA Status
            data_status = "warning"  # Default if no data
            if sl.last_collected:
                data_age = now - sl.last_collected
                if data_age <= freshness_warning_limit:
                    data_status = "active"
                elif data_age <= freshness_error_limit:
                    data_status = "warning"
                else:
                    data_status = "error"  # Data is stale
            
            # 3. Update Global Summary (Worst-case logic)
            if pipeline_status == "error" or data_status == "error":
                summary["error"] += 1
            elif pipeline_status == "warning" or data_status == "warning":
                summary["warning"] += 1
            else:
                summary["active"] += 1
            
            # 4. Generate URLs
            monitor_url = reverse("station_link_monitoring", args=(sl.id,)) + "?direction=pull"
            
            # Format outputs
            stations_output.append({
                "id": sl.id,
                "name": sl.station.name,
                
                # Dual Statuses
                "pipeline_status": pipeline_status,
                "data_status": data_status,
                
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
