from django.urls import path

from adl.viewer.views.availability import DataAvailabilitySummaryView
from adl.viewer.views.qc import (
    get_qc_summary,
    get_station_qc_inspection
)
from .views import (
    get_network_connections,
    get_network_connection_station_links,
    get_station_link_latest_data,
    get_station_link_timeseries_data,
    get_data_parameters,
    get_station_link_detail,
    get_network_connection_data_parameters
)

urlpatterns = [
    path("network-connection/", get_network_connections, name="network_connections"),
    path("network-connection/<int:network_conn_id>/station-links/", get_network_connection_station_links,
         name="network_connection_station_links"),
    path("network-connection/<int:network_conn_id>/data-parameters/", get_network_connection_data_parameters,
         name="network_connection_data_parameters"),
    path("station-link/<int:station_link_id>/", get_station_link_detail, name="station_link_detail"),
    path("data-parameters/", get_data_parameters, name="data_parameters"),
    path("data/latest/<int:station_link_id>/", get_station_link_latest_data, name="station_link_latest_data"),
    path("data/timeseries/<int:station_link_id>/", get_station_link_timeseries_data,
         name="station_link_timeseries_data"),
    path("qc/summary/", get_qc_summary, name="qc_summary"),
    path("qc/inspection/<int:station_id>/", get_station_qc_inspection, name="qc_inspection"),
    path('data-availability/summary/', DataAvailabilitySummaryView.as_view(), name='data-availability-summary'),
]
