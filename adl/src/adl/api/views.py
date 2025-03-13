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
            "error": "No observation records found for the given station and connection."
        }, status=404)
    
    data = {
        "station_id": station_id,
        "connection_id": connection_id,
        "time": latest_records[0].time.isoformat(),
        "data": {record.parameter.name: record.value for record in latest_records}
    }
    
    return Response(data)
