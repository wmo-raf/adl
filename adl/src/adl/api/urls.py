from django.urls import path

from .views import (
    get_network_connections,
    get_network_connection_station_links,
    get_station_link_latest_data,
    get_station_link_timeseries_data,
    get_data_parameters,
    get_station_link_detail
)

urlpatterns = [
    path("network-connection/", get_network_connections, name="network_connections"),
    path("station-link/<int:station_link_id>/", get_station_link_detail, name="station_link_detail"),
    path("data-parameters/", get_data_parameters, name="data_parameters"),
    path("network-connection/<int:network_conn_id>/station-links/", get_network_connection_station_links,
         name="network_connection_station_links"),
    path("data/latest/<int:station_link_id>/", get_station_link_latest_data, name="station_link_latest_data"),
    path("data/timeseries/<int:station_link_id>/", get_station_link_timeseries_data,
         name="station_link_timeseries_data"),
]
