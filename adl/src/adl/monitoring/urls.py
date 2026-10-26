from django.urls import path

from .views import (
    get_network_conn_plugin_task_results_since,
    get_station_activity_log,
    network_connection_monitoring,
    dispatch_channel_monitoring,
    station_link_monitoring
)

from .views.availability import (
    availability_check,
    availability_check_status,
    availability_recover,
    availability_recover_status,
    availability_send_window,
    availability_send_window_status,
    availability_running,
    data_availability,
)
from .views.activity import NetworkConnectionActivityView, DispatchChannelMonitoringView
from .views.health import (
    connection_health,
    connection_probe_source,
    connection_run_now,
    station_link_check_source,
)

urlpatterns = [
    path('availability/', data_availability, name='data_availability'),
    path('availability/check/', availability_check, name='availability_check'),
    path('availability/check/<str:task_id>/', availability_check_status,
         name='availability_check_status'),
    path('availability/running/', availability_running, name='availability_running'),
    path('availability/recover/', availability_recover, name='availability_recover'),
    path('availability/recover/<str:task_id>/', availability_recover_status,
         name='availability_recover_status'),
    path('availability/send-window/', availability_send_window, name='availability_send_window'),
    path('availability/send-window/<str:task_id>/', availability_send_window_status,
         name='availability_send_window_status'),
    path('connection/<int:connection_id>/health/', connection_health,
         name='connection_health'),
    path('connection/<int:connection_id>/health/probe-source/', connection_probe_source,
         name='connection_probe_source'),
    path('connection/<int:connection_id>/health/run-now/', connection_run_now,
         name='connection_run_now'),
    path("plugin-processing-results/<int:network_conn_id>/",
         get_network_conn_plugin_task_results_since,
         name="get_network_conn_plugin_task_results_since_no_date"),
    path("plugin-processing-results/<int:network_conn_id>/<str:from_date>/",
         get_network_conn_plugin_task_results_since,
         name="get_network_conn_plugin_task_results_since_with_date"),
    path("station-activity/<int:connection_id>/",
         get_station_activity_log,
         name="get_station_activity_log_with_date"),
    path('connection/<int:connection_id>/', network_connection_monitoring,
         name='network_connection_monitoring'),
    path("connection-activity/<int:connection_id>/", NetworkConnectionActivityView.as_view(),
         name='network_connection_activity'),
    path("dispatch-activity/<int:channel_id>/", DispatchChannelMonitoringView.as_view(),
         name='dispatch_activity'),
    path('dispatch-channel/<int:channel_id>/', dispatch_channel_monitoring,
         name='dispatch_channel_monitoring'),
    path('station-link/<int:link_id>/', station_link_monitoring,
         name='station_link_monitoring'),
    path('station-link/<int:link_id>/check-source/', station_link_check_source,
         name='station_link_check_source')
]
