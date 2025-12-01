from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from collections import defaultdict

from adl.core.models import (
    NetworkConnection,
    StationLink,
    ObservationRecord,
    HourlyObsAgg,
)


class DataAvailabilitySummaryView(APIView):
    """
    Returns 24-hour availability summary for all stations in a network connection.
    
    Query params:
        - connection_id (required): ID of the network connection
        
    Response:
        {
            "connection": {
                "id": 5,
                "name": "Kenya Met Auto",
                "is_daily": false
            },
            "time_range": {
                "start": "2025-05-31T00:00:00Z",
                "end": "2025-06-01T00:00:00Z"
            },
            "summary": {
                "total_stations": 8,
                "reporting": 5,
                "with_gaps": 2,
                "offline": 1
            },
            "stations": [
                {
                    "station_link_id": 12,
                    "station_id": 1,
                    "station_name": "Nairobi AWS",
                    "expected_hourly": 42,
                    "hourly_counts": {
                        "0": 42, "1": 42, ..., "23": 42
                    },
                    "total_records": 892,
                    "hours_with_data": 22,
                    "last_data_time": "2025-05-31T22:00:00Z",
                    "status": "gaps"
                }
            ]
        }
    """
    
    def get(self, request):
        connection_id = request.query_params.get('connection_id')
        
        if not connection_id:
            return Response(
                {"error": "connection_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            connection = NetworkConnection.objects.get(pk=connection_id)
        except NetworkConnection.DoesNotExist:
            return Response(
                {"error": "Network connection not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Time range: last 24 hours
        now = timezone.now()
        start_time = now - timedelta(hours=24)
        
        # Get all enabled station links for this connection
        station_links = StationLink.objects.filter(
            network_connection=connection,
            enabled=True
        ).select_related('station')
        
        # Build response based on connection type
        hour_labels = []
        hour_keys = []
        
        if connection.is_daily_data:
            stations_data = self._get_daily_availability(
                connection, station_links, start_time, now
            )
        else:
            stations_data, hour_labels, hour_keys = self._get_hourly_availability(
                connection, station_links, start_time, now
            )
        
        # Calculate summary stats
        total_stations = len(stations_data)
        reporting = sum(1 for s in stations_data if s['hours_with_data'] > 0)
        offline = sum(1 for s in stations_data if s['hours_with_data'] == 0)
        with_gaps = sum(
            1 for s in stations_data
            if 0 < s['hours_with_data'] < 24 and not connection.is_daily_data
        )
        
        return Response({
            "connection": {
                "id": connection.id,
                "name": connection.name,
                "is_daily": connection.is_daily_data
            },
            "time_range": {
                "start": start_time.isoformat(),
                "end": now.isoformat()
            },
            "summary": {
                "total_stations": total_stations,
                "reporting": reporting,
                "with_gaps": with_gaps,
                "offline": offline
            },
            "hour_labels": hour_labels,
            "hour_keys": hour_keys,
            "stations": stations_data
        })
    
    def _get_hourly_availability(self, connection, station_links, start_time, end_time):
        # 1. Setup Buckets (Same as before)
        hour_buckets = []
        current_bucket = start_time.replace(minute=0, second=0, microsecond=0)
        while current_bucket < end_time:
            hour_buckets.append(current_bucket)
            current_bucket += timedelta(hours=1)
        
        hour_labels = [bucket.strftime('%H:00') for bucket in hour_buckets]
        hour_keys = [bucket.strftime('%Y-%m-%d %H:00') for bucket in hour_buckets]
        
        # 2. Get all Station IDs
        station_map = {sl.station_id: sl for sl in station_links}
        station_ids = list(station_map.keys())
        
        # 3. BATCH QUERY: Fetch data for ALL stations in one go
        # Group by station and bucket
        all_data = HourlyObsAgg.objects.filter(
            station_id__in=station_ids,
            connection=connection,
            bucket__gte=start_time,
            bucket__lt=end_time
        ).values('station_id', 'bucket').annotate(
            record_count=Sum('records_count')
        )
        
        # 4. Transform DB result into a nested dictionary for fast lookup
        # Structure: data_map[station_id][timestamp_str] = count
        data_map = defaultdict(dict)
        for entry in all_data:
            key = entry['bucket'].strftime('%Y-%m-%d %H:00')
            data_map[entry['station_id']][key] = entry['record_count']
        
        # 5. Build Result List
        stations_data = []
        
        # TODO: cache 'expected_hourly' on the StationLink model for performance
        
        for station_link in station_links:
            s_id = station_link.station_id
            station_counts = data_map.get(s_id, {})
            
            hourly_counts = {}
            total_records = 0
            last_data_time = None
            
            # Map values to the fixed time grid
            for i, bucket in enumerate(hour_buckets):
                key = hour_keys[i]
                count = station_counts.get(key, 0)
                
                hourly_counts[key] = count
                total_records += count
                
                if count > 0:
                    last_data_time = bucket
            
            # Optimization: Don't calc median here every time.
            # Use a field or a fixed default for speed.
            expected_hourly = self._calculate_expected_hourly(station_link)
            
            hours_with_data = sum(1 for c in hourly_counts.values() if c > 0)
            status = self._determine_status(hours_with_data, 24, last_data_time)
            
            stations_data.append({
                "station_link_id": station_link.id,
                "station_name": station_link.station.name,
                "expected_hourly": expected_hourly,
                "hourly_counts": hourly_counts,
                "total_records": total_records,
                "hours_with_data": hours_with_data,
                "status": status,
                "last_data_time": last_data_time.isoformat() if last_data_time else None
            })
        
        return stations_data, hour_labels, hour_keys
    
    def _get_daily_availability(self, connection, station_links, start_time, end_time):
        """Get daily record counts for each station (for daily data connections)."""
        
        stations_data = []
        
        for station_link in station_links:
            station = station_link.station
            
            # For daily data, just count records for today
            daily_count = ObservationRecord.objects.filter(
                station=station,
                connection=connection,
                time__gte=start_time,
                time__lt=end_time,
                is_daily=True
            ).count()
            
            last_record = ObservationRecord.objects.filter(
                station=station,
                connection=connection,
                is_daily=True
            ).order_by('-time').first()
            
            last_data_time = last_record.time if last_record else None
            
            # For daily, we use a simplified hourly_counts with just one entry
            hourly_counts = {"today": daily_count}
            
            expected_daily = self._calculate_expected_daily(station_link)
            
            hours_with_data = 1 if daily_count > 0 else 0
            station_status = "complete" if daily_count > 0 else "offline"
            
            stations_data.append({
                "station_link_id": station_link.id,
                "station_id": station.id,
                "station_name": station.name,
                "expected_hourly": expected_daily,  # For daily, this is expected daily count
                "hourly_counts": hourly_counts,
                "total_records": daily_count,
                "hours_with_data": hours_with_data,
                "last_data_time": last_data_time.isoformat() if last_data_time else None,
                "status": station_status
            })
        
        return stations_data
    
    def _calculate_expected_hourly(self, station_link):
        """
        Calculate expected records per hour.
        
        Uses HourlyObsAgg which stores one row per (station, connection, parameter, hour).
        We sum records_count across all parameters to get total expected records per hour.
        
        Priority:
        1. Explicit configuration on station_link (if set)
        2. Historical median from last 7 days (using HourlyObsAgg)
        3. Fallback estimate from variable mappings
        """
        # 1. Check for explicit configuration
        if hasattr(station_link, 'expected_records_per_hour') and station_link.expected_records_per_hour:
            return station_link.expected_records_per_hour
        
        # 2. Calculate from recent history using pre-aggregated view
        lookback_days = 7
        start_time = timezone.now() - timedelta(days=lookback_days)
        
        # Sum records_count across all parameters for each hour bucket
        hourly_totals = list(
            HourlyObsAgg.objects.filter(
                station=station_link.station,
                connection=station_link.network_connection,
                bucket__gte=start_time
            ).values('bucket').annotate(
                total_records=Sum('records_count')
            ).filter(
                total_records__gt=0
            ).values_list('total_records', flat=True)
        )
        
        if hourly_totals:
            # Use median (more robust than mean against outliers)
            hourly_totals.sort()
            mid = len(hourly_totals) // 2
            return hourly_totals[mid]
        
        # 3. Fallback to mappings estimate
        return self._estimate_from_mappings(station_link)
    
    def _estimate_from_mappings(self, station_link):
        """
        Fallback estimation from variable mappings.
        
        Assumes each parameter reports once per hour (conservative estimate).
        """
        try:
            mappings = station_link.get_variable_mappings()
            num_params = mappings.count() if hasattr(mappings, 'count') else len(mappings)
            return num_params if num_params > 0 else 10
        except Exception:
            return 10
    
    def _calculate_expected_daily(self, station_link):
        """Calculate expected records per day for daily data connections."""
        try:
            variable_mappings = station_link.get_variable_mappings()
            num_parameters = variable_mappings.count() if hasattr(variable_mappings, 'count') else len(
                variable_mappings)
            return num_parameters if num_parameters > 0 else 10
        except Exception:
            return 10
    
    def _determine_status(self, hours_with_data, expected_hours, last_data_time):
        """Determine station status based on data availability."""
        
        if hours_with_data == 0:
            return "offline"
        
        coverage = hours_with_data / expected_hours
        
        # Check if last data is stale (more than 3 hours ago)
        if last_data_time:
            hours_since_last = (timezone.now() - last_data_time).total_seconds() / 3600
            if hours_since_last > 3:
                return "critical"
        
        if coverage >= 0.9:
            return "complete"
        elif coverage >= 0.5:
            return "gaps"
        else:
            return "critical"
