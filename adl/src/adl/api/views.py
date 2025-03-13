from collections import defaultdict
from datetime import datetime

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_api_key.permissions import HasAPIKey

from adl.core.models import (
    Network,
    NetworkConnection, StationLink, ObservationRecord, )
from .serializers import (
    NetworkSerializer,
    NetworkConnectionSerializer,
    ObservationRecordSerializer, StationLinkSerializer
)


@api_view()
@permission_classes([HasAPIKey])
def get_networks(request):
    networks = Network.objects.all()
    data = NetworkSerializer(networks, many=True).data
    return Response(data)


@api_view()
@permission_classes([HasAPIKey])
def get_network_connections(request):
    connections = NetworkConnection.objects.all()
    data = NetworkConnectionSerializer(connections, many=True).data
    return Response(data)


@api_view()
@permission_classes([HasAPIKey])
def get_network_connection_station_links(request, network_conn_id):
    network = get_object_or_404(NetworkConnection, id=network_conn_id)
    stations = network.station_links.all()
    data = StationLinkSerializer(stations, many=True).data
    return Response(data)


@api_view()
@permission_classes([HasAPIKey])
def get_raw_observation_records_for_connection_station(request, connection_id, station_id):
    records = NetworkConnection.objects.get(id=connection_id).observation_records.filter(station_id=station_id)
    serialized_data = ObservationRecordSerializer(records, many=True).data
    
    data = {
        "station_id": station_id,
        "connection_id": connection_id,
        "records": serialized_data,
    }
    
    return Response(data)


@api_view()
@permission_classes([HasAPIKey])
def get_station_link_latest_data(request, station_link_id):
    station_link = get_object_or_404(StationLink, id=station_link_id)
    connection_id = station_link.network_connection.id
    station_id = station_link.station_id
    
    latest_records = ObservationRecord.objects.filter(
        connection_id=connection_id,
        station_id=station_id
    ).distinct('parameter_id').order_by('parameter_id', '-time').select_related('parameter')
    
    if not latest_records.exists():
        return Response({
            "error": "No observation records found for the given station link."
        }, status=404)
    
    data = {
        "station_id": station_id,
        "connection_id": connection_id,
        "time": latest_records[0].time.isoformat(),
        "data": {record.parameter.name: record.value for record in latest_records}
    }
    
    return Response(data)


@api_view()
@permission_classes([HasAPIKey])
def get_station_link_timeseries_data(request, station_link_id):
    # Fetch the StationLink object or return 404 if not found
    station_link = get_object_or_404(StationLink, id=station_link_id)
    connection_id = station_link.network_connection.id
    station_id = station_link.station_id
    
    # Get query parameters for time range (optional)
    start_time = request.GET.get('start_time')
    end_time = request.GET.get('end_time')
    
    # Initialize the base query
    query = ObservationRecord.objects.filter(
        connection_id=connection_id,
        station_id=station_id
    ).select_related('parameter')
    
    # Apply time range filtering if provided
    if start_time and end_time:
        try:
            start_time = datetime.fromisoformat(start_time)
            end_time = datetime.fromisoformat(end_time)
            query = query.filter(time__gte=start_time, time__lte=end_time)
        except ValueError:
            return Response({
                "error": "Invalid date format. Use ISO format (e.g., 2023-10-01T00:00:00Z)."
            }, status=400)
    
    # Fetch the records ordered by time
    records = query.order_by('time')
    
    if not records.exists():
        return Response({
            "error": "No observation records found for the given station and connection."
        }, status=404)
    
    # Group records by time
    grouped_data = defaultdict(lambda: {"data": {}})
    for record in records:
        time_key = record.time.isoformat()
        if time_key not in grouped_data:
            grouped_data[time_key] = {
                "station_id": station_id,
                "connection_id": connection_id,
                "time": time_key,
                "data": {}
            }
        grouped_data[time_key]["data"][record.parameter.name] = record.value
    
    # Convert the dictionary to a list of records
    result = list(grouped_data.values())
    
    return Response(result)
