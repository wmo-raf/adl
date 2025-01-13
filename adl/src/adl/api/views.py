from collections import defaultdict

from rest_framework.decorators import api_view
from rest_framework.response import Response

from adl.core.models import (
    Network,
    NetworkConnection,
)
from .serializers import (
    NetworkSerializer,
    StationSerializer,
    NetworkConnectionSerializer,
    ObservationRecordSerializer
)


@api_view()
def get_networks(request):
    networks = Network.objects.all()
    data = NetworkSerializer(networks, many=True).data
    return Response(data)


@api_view()
def get_stations_for_network(request, network_id):
    stations = Network.objects.get(id=network_id).stations.all()
    data = StationSerializer(stations, many=True).data
    return Response(data)


@api_view()
def get_network_connections(request):
    connections = NetworkConnection.objects.all()
    data = NetworkConnectionSerializer(connections, many=True).data
    return Response(data)


@api_view()
def get_raw_observation_records_for_connection_station(request, connection_id, station_id):
    records = NetworkConnection.objects.get(id=connection_id).observation_records.filter(station_id=station_id)
    serialized_data = ObservationRecordSerializer(records, many=True).data
    
    data = {
        "station_id": station_id,
        "connection_id": connection_id,
        "records": serialized_data,
    }
    
    return Response(data)
