from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime
from django_celery_results.models import TaskResult
from rest_framework.decorators import api_view
from rest_framework.response import Response

from adl.core.models import NetworkConnection
from .constants import NETWORK_PLUGIN_TASK_NAME
from .models import StationLinkActivityLog
from .serializers import TaskResultSerializer, StationLinkActivityLogSerializer
from ..core.utils import get_object_or_none


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


@api_view()
def get_station_activity_log(request, connection_id, from_date=None):
    if from_date:
        from_date = parse_datetime(from_date)
        
        if not from_date:
            return Response({"error": "Invalid date format. Please provide a valid date format."}, status=400)
        
        if dj_timezone.is_naive(from_date):
            from_date = dj_timezone.make_aware(from_date)
    else:
        # use the beginning of today
        from_date = dj_timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    
    connection = get_object_or_none(NetworkConnection, id=connection_id)
    if not connection:
        return Response({"error": "Network connection not found."}, status=404)
    
    station_links = connection.station_links.all()
    
    filter_params = {
        "station_link__in": station_links,
    }
    
    if from_date:
        filter_params["time__gte"] = from_date
    
    stations_activity_log = StationLinkActivityLog.objects.filter(**filter_params)
    
    serialized_data = StationLinkActivityLogSerializer(stations_activity_log, many=True).data
    
    data = {
        "stations": [link.station.name for link in station_links],
        "connection": connection.name,
        "from_date": from_date.isoformat(),
        "activity_log": serialized_data
    }
    
    return Response(data)
