from datetime import timedelta

from django.db.models import Min, Max
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_api_key.permissions import HasAPIKey

from adl.core.models import (
    Network,
    NetworkConnection,
    StationLink,
    ObservationRecord,
    DataParameter
)
from .auth import HasAPIKeyOrIsAuthenticated
from .serializers import (
    NetworkSerializer,
    NetworkConnectionSerializer,
    ObservationRecordSerializer,
    StationLinkSerializer,
    DataParameterSerializer
)
from .utils import validate_iso_datetime, _group_records_by_time


@api_view()
@permission_classes([HasAPIKey])
def get_networks(request):
    networks = Network.objects.all()
    data = NetworkSerializer(networks, many=True).data
    return Response(data)


@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_station_link_detail(request, station_link_id):
    station_link = get_object_or_404(StationLink, id=station_link_id)
    station_link_info = StationLinkSerializer(station_link).data
    
    data_dates = ObservationRecord.objects.filter(
        station_id=station_link.station_id,
        connection_id=station_link.network_connection_id).aggregate(
        earliest_time=Min('time'),
        latest_time=Max('time')
    )
    
    station_link_info.update({
        "data_dates": {
            "earliest_time": data_dates['earliest_time'].isoformat() if data_dates['earliest_time'] else None,
            "latest_time": data_dates['latest_time'].isoformat() if data_dates['latest_time'] else None,
        }
    })
    
    variable_mappings = None
    if hasattr(station_link.network_connection, 'variable_mappings'):
        variable_mappings = station_link.network_connection.variable_mappings.all()
    elif hasattr(station_link, 'variable_mappings'):
        variable_mappings = station_link.variable_mappings.all()
    
    if variable_mappings:
        data_parameters = []
        for mapping in variable_mappings:
            if hasattr(mapping, 'adl_parameter'):
                data_parameters.append(mapping.adl_parameter)
        
        if data_parameters:
            data_parameters = DataParameterSerializer(data_parameters, many=True).data
            station_link_info['data_parameters'] = data_parameters
    
    return Response(station_link_info)


@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_network_connections(request):
    connections = NetworkConnection.objects.all()
    data = NetworkConnectionSerializer(connections, many=True).data
    return Response(data)


@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_data_parameters(request):
    data_parameters = DataParameter.objects.all()
    data = DataParameterSerializer(data_parameters, many=True).data
    return Response(data)


@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
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
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_station_link_latest_data(request, station_link_id):
    station_link = get_object_or_404(StationLink, id=station_link_id)
    connection_id = station_link.network_connection.id
    station_id = station_link.station_id
    
    latest_records = ObservationRecord.objects.filter(
        connection_id=connection_id,
        station_id=station_id
    ).distinct('parameter_id').order_by('parameter_id', '-time')
    
    if not latest_records:
        return Response({
            "error": "No observation records found for the given station link."
        }, status=404)
    
    data = {
        "station_id": station_id,
        "connection_id": connection_id,
        "data": [
            {"time": record.time.isoformat(), "parameter_id": record.parameter_id, "value": record.value}
            for record in latest_records
        ]
    }
    
    return Response(data)


@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_station_link_timeseries_data(request, station_link_id):
    # Fetch the StationLink object or return 404 if not found
    station_link = get_object_or_404(StationLink, id=station_link_id)
    connection_id = station_link.network_connection.id
    station_id = station_link.station_id
    
    # Get query parameters for time range (optional)
    start_time = request.GET.get('start_time', None)
    end_time = request.GET.get('end_time', None)
    
    if start_time or end_time:
        try:
            start_time = validate_iso_datetime('start_time', start_time)
            end_time = validate_iso_datetime('end_time', end_time)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
    
    if not start_time:
        # get the last 24 hours of data if no start_time is provided
        start_time = (dj_timezone.now() - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    
    # Initialize the base query
    query = ObservationRecord.objects.filter(
        connection_id=connection_id,
        station_id=station_id,
        time__gte=start_time,
    )
    
    if end_time:
        query = query.filter(time__lte=end_time)
    
    # Fetch the records ordered by time
    records = query.order_by('-time')
    
    if not records.exists():
        return Response({
            "error": "No observation records found for the given station and connection."
        }, status=404)
    
    # Group records by time
    grouped_data = _group_records_by_time(records, station_id, connection_id)
    
    return Response(grouped_data)
