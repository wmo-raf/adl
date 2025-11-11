from datetime import timedelta

from django.db.models import Min, Max
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
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
from adl.viewer.models import MapViewerSetting
from .auth import HasAPIKeyOrIsAuthenticated
from .pagination import StandardResultsSetPagination
from .serializers import (
    NetworkSerializer,
    NetworkConnectionSerializer,
    ObservationRecordSerializer,
    StationLinkSerializer,
    DataParameterSerializer
)
from .utils import validate_iso_datetime, _group_records_by_time


@extend_schema(
    summary="List all networks",
    description="Returns a list of all networks configured in the system.",
    responses=NetworkSerializer(many=True),
    tags=["Networks"]
)
@api_view()
@permission_classes([HasAPIKey])
def get_networks(request):
    networks = Network.objects.all()
    data = NetworkSerializer(networks, many=True).data
    return Response(data)


@extend_schema(
    summary="Get station link details",
    description="Returns detailed information about a station link including mapped data parameters and available data dates.",
    parameters=[
        OpenApiParameter(name="station_link_id", type=int, location=OpenApiParameter.PATH,
                         description="ID of the station link"),
    ],
    responses=StationLinkSerializer,
    tags=["Station Links"]
)
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
            
            parameter_categories_dict = {category[0]: category[1] for category in DataParameter.CATEGORY_CHOICES}
            data_categories = {}
            for parameter in data_parameters:
                category_id = parameter['category']
                if category_id not in data_categories:
                    data_categories[category_id] = parameter_categories_dict[category_id]
            
            station_link_info['data_categories'] = [{"id": category_id, "name": name} for category_id, name in
                                                    data_categories.items()]
    
    return Response(station_link_info)


@extend_schema(
    summary="Get network connections",
    description="Returns all network connections available in the system.",
    responses=NetworkConnectionSerializer(many=True),
    tags=["Connections"]
)
@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_network_connections(request):
    connections = NetworkConnection.objects.all()
    data = NetworkConnectionSerializer(connections, many=True).data
    return Response(data)


@extend_schema(
    summary="List all data parameters",
    description="Returns all data parameters and their categories.",
    responses={
        200: OpenApiExample(
            name="Data Parameters Response",
            value={
                "categories": [{"id": "TMP", "name": "Temperature"}],
                "data_parameters": []
            }
        )
    },
    tags=["Parameters"]
)
@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_data_parameters(request):
    parameter_categories = [{"id": category[0], "name": category[1]} for category in DataParameter.CATEGORY_CHOICES]
    data_parameters = DataParameter.objects.all()
    data = DataParameterSerializer(data_parameters, many=True).data
    
    response_data = {
        "categories": parameter_categories,
        "data_parameters": data,
    }
    
    return Response(response_data)


@extend_schema(
    summary="Get station links by network connection",
    description="Returns all station links for the given network connection.",
    parameters=[
        OpenApiParameter(name="network_conn_id", type=int, location=OpenApiParameter.PATH,
                         description="ID of the network connection"),
    ],
    responses=StationLinkSerializer(many=True),
    tags=["Station Links"]
)
@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_network_connection_station_links(request, network_conn_id):
    network = get_object_or_404(NetworkConnection, id=network_conn_id)
    stations = network.station_links.all()
    data = StationLinkSerializer(stations, many=True).data
    return Response(data)


@extend_schema(
    summary="Get raw observation records for a station in a network connection",
    description="Returns raw ungrouped observation records for a specific station and connection.",
    parameters=[
        OpenApiParameter(name="connection_id", type=int, location=OpenApiParameter.PATH),
        OpenApiParameter(name="station_id", type=str, location=OpenApiParameter.PATH),
    ],
    responses=ObservationRecordSerializer(many=True),
    tags=["Observation Records"]
)
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


@extend_schema(
    summary="Get latest data for station link",
    description="Returns the latest observation for each parameter at the station link.",
    parameters=[
        OpenApiParameter(name="station_link_id", type=int, location=OpenApiParameter.PATH),
    ],
    responses=ObservationRecordSerializer(many=True),
    tags=["Observation Records"]
)
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


@extend_schema(
    summary="Get time series data for a station link",
    description=(
            "Returns observation records grouped by time for a given station link, "
            "optionally filtered by time range and parameter category."
    ),
    parameters=[
        OpenApiParameter(name="station_link_id", type=int, location=OpenApiParameter.PATH),
        OpenApiParameter(name="start_date", required=False, type=str, location=OpenApiParameter.QUERY,
                         description="Start datetime (ISO 8601 format)"),
        OpenApiParameter(name="end_date", required=False, type=str, location=OpenApiParameter.QUERY,
                         description="End datetime (ISO 8601 format)"),
        OpenApiParameter(name="category", required=False, type=str, location=OpenApiParameter.QUERY,
                         description="Parameter category to filter by"),
    ],
    responses=ObservationRecordSerializer(many=True),
    tags=["Observation Records"]
)
@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_station_link_timeseries_data(request, station_link_id):
    # Fetch the StationLink object or return 404 if not found
    station_link = get_object_or_404(StationLink, id=station_link_id)
    connection_id = station_link.network_connection.id
    station_id = station_link.station_id
    
    # Get query parameters for time range (optional)
    start_date = request.GET.get('start_date', None)
    end_date = request.GET.get('end_date', None)
    
    category = request.GET.get('category', None)
    
    paginate = request.GET.get('paginate', 'false').lower() != 'false'
    
    if start_date or end_date:
        try:
            start_date = validate_iso_datetime('start_date', start_date)
            end_date = validate_iso_datetime('end_date', end_date)
        
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
    
    if not start_date:
        # get the last 24 hours of data if no start_time is provided
        start_date = (dj_timezone.now() - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    
    # Initialize the base query
    query = ObservationRecord.objects.filter(
        connection_id=connection_id,
        station_id=station_id,
        time__gte=start_date,
    )
    
    if category:
        # Filter by parameter category if provided
        query = query.filter(parameter__category=category)
    
    if not end_date:
        # set end_time to 30 days from start_time if not provided
        end_date = start_date + timedelta(days=30)
    
    # Ensure end_time is not in the future
    if end_date > dj_timezone.now():
        end_date = dj_timezone.now()
    
    if end_date:
        query = query.filter(time__lte=end_date)
    
    # Fetch the records ordered by time
    records = query.order_by('-time')
    
    if not records.exists():
        return Response({
            "error": "No observation records found for the given station and filters"
        }, status=404)
    
    # Group records by time
    grouped_data = _group_records_by_time(records, station_id, connection_id)
    
    if not paginate:
        return Response({"results": grouped_data})
    
    paginator = StandardResultsSetPagination()
    paginated = paginator.paginate_queryset(grouped_data, request)
    
    return paginator.get_paginated_response(paginated)


@api_view()
@permission_classes([HasAPIKeyOrIsAuthenticated])
def get_network_connection_data_parameters(request, network_conn_id):
    network = get_object_or_404(NetworkConnection, id=network_conn_id)
    stations = network.station_links.all()
    
    unique_variable_mappings = {}
    
    for station_link in stations:
        station_link_variable_mappings = None
        if hasattr(station_link.network_connection, 'variable_mappings'):
            station_link_variable_mappings = station_link.network_connection.variable_mappings.all()
        elif hasattr(station_link, 'variable_mappings'):
            station_link_variable_mappings = station_link.variable_mappings.all()
        
        if station_link_variable_mappings:
            for variable_mapping in station_link_variable_mappings:
                if hasattr(variable_mapping, 'adl_parameter'):
                    unique_variable_mappings[variable_mapping.adl_parameter.id] = variable_mapping.adl_parameter
    
    # Get the map settings with prefetch
    map_settings = MapViewerSetting.for_request(request)
    
    # Get all styles in one query, filtered by the parameters we have
    parameter_ids = list(unique_variable_mappings.keys())
    styles = map_settings.data_parameter_styles.filter(
        data_parameter_id__in=parameter_ids
    ).select_related('data_parameter')
    
    # Build a dictionary of styles
    styles_dict = {
        style.data_parameter.id: {
            'color_scale': style.get_maplibre_color_scale(),
            'color_stops': style.get_color_scale_json(),
        }
        for style in styles
    }
    
    # Serialize data parameters
    data_parameters = DataParameterSerializer(unique_variable_mappings.values(), many=True)
    
    # Add style information to each parameter
    result = []
    for param in data_parameters.data:
        param_with_style = param.copy()
        param_id = param['id']
        
        param_with_style['style'] = styles_dict.get(param_id, None)
        
        result.append(param_with_style)
    
    return Response(result)
