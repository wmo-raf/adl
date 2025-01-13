from django.urls import path

from .views import (
    get_networks,
    get_stations_for_network,
    get_network_connections,
    get_raw_observation_records_for_connection_station
)

urlpatterns = [
    path("networks/", get_networks, name="networks"),
    path("stations/<int:network_id>/", get_stations_for_network, name="network_stations"),
    path("network-connections/", get_network_connections, name="network_connections"),
    path("raw-observation-records/<int:connection_id>/<int:station_id>/",
         get_raw_observation_records_for_connection_station,
         name="raw_observation_records_for_connection_station"),
]
