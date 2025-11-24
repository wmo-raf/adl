from datetime import timedelta

from django.contrib.humanize.templatetags.humanize import naturaltime
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone as dj_timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from adl.core.models import (
    NetworkConnection,
    ObservationRecord,
    DispatchChannel,
    StationChannelDispatchStatus
)
from adl.monitoring.models import StationLinkActivityLog


class NetworkConnectionActivityView(APIView):
    def get(self, request, connection_id):
        # 1. Fetch the Connection
        connection = get_object_or_404(NetworkConnection, id=connection_id)
        
        # --- PREPARE QUERIES ---
        
        # Subquery 1: Latest Activity Log (Pipeline Status)
        # Uses Index: ['station_link', '-time']
        latest_log_sq = StationLinkActivityLog.objects.filter(
            station_link=OuterRef('pk'),
            direction='pull'  # Explicitly looking for PULL activities
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
        check_interval = channel.data_check_interval
        
        # A. Pipeline Tolerance (Is the job running?)
        # Standard: 3 missed cycles means the scheduler is stuck
        pipeline_tolerance = timedelta(minutes=check_interval * 3)
        
        # B. Data Freshness (Is the data current?)
        
        # Base limits based on check interval
        base_warning_minutes = check_interval * 4
        base_error_minutes = check_interval * 12
        
        # Calculate Aggregation Offset
        aggregation_offset = timedelta(0)
        
        if channel.send_aggregated_data:
            # If aggregating, the data is inherently old by the size of the window.
            # We add this window to the allowed tolerance.
            if channel.aggregation_period == 'hourly':
                aggregation_offset = timedelta(hours=1)
            elif channel.aggregation_period == 'daily':  # Future proofing
                aggregation_offset = timedelta(days=1)
            
            # Note: We add an extra buffer because aggregation usually happens
            # *after* the period closes + processing time.
            aggregation_offset += timedelta(minutes=5)
        
        freshness_warning_limit = timedelta(minutes=base_warning_minutes) + aggregation_offset
        freshness_error_limit = timedelta(minutes=base_error_minutes) + aggregation_offset
        
        # --- 3. PROCESS DATA ---
        
        stations_output = []
        summary = {"active": 0, "warning": 0, "error": 0}
        
        for sl in station_links:
            # --- Pipeline Status ---
            pipeline_status = "warning"
            if sl.last_attempt:
                time_since_attempt = now - sl.last_attempt
                if not sl.last_attempt_success:
                    pipeline_status = "error"
                elif time_since_attempt > pipeline_tolerance:
                    pipeline_status = "warning"
                else:
                    pipeline_status = "active"
            
            # --- Data Status (With Aggregation Logic) ---
            data_status = "warning"
            if sl.last_sent_obs:
                data_age = now - sl.last_sent_obs
                
                if data_age <= freshness_warning_limit:
                    data_status = "active"
                elif data_age <= freshness_error_limit:
                    data_status = "warning"
                else:
                    data_status = "error"
            
            # --- Summary ---
            if pipeline_status == "error" or data_status == "error":
                summary["error"] += 1
            elif pipeline_status == "warning" or data_status == "warning":
                summary["warning"] += 1
            else:
                summary["active"] += 1
            
            monitor_url = reverse("station_link_monitoring", args=(sl.id,)) + f"?direction=push&channel={channel.id}"
            
            stations_output.append({
                "id": sl.id,
                "name": sl.station.name,
                "connection_name": sl.network_connection.name,
                "connection_id": sl.network_connection.id,
                
                "pipeline_status": pipeline_status,
                "data_status": data_status,
                "last_check": sl.last_attempt,
                "last_check_human": naturaltime(sl.last_attempt) if sl.last_attempt else None,
                "last_collected": sl.last_sent_obs,
                "last_collected_human": naturaltime(sl.last_sent_obs) if sl.last_sent_obs else None,
                "logs_url": monitor_url,
                "data_viewer_url": "#",
            })
        
        return Response({
            "connection": {
                "id": channel.id,
                "name": channel.name,
                "enabled": channel.enabled,
                "interval_minutes": channel.data_check_interval,
                "plugin": "Dispatch",
            },
            "summary": summary,
            "stations": stations_output,
        })
