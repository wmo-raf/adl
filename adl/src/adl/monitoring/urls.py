from django.urls import path

from .views import (
    get_network_conn_plugin_task_results_since,
    get_station_activity_log
)

urlpatterns = [
    path("plugin-processing-results/<int:network_conn_id>/",
         get_network_conn_plugin_task_results_since,
         name="get_network_conn_plugin_task_results_since_no_date"),
    path("plugin-processing-results/<int:network_conn_id>/<str:from_date>/",
         get_network_conn_plugin_task_results_since,
         name="get_network_conn_plugin_task_results_since_with_date"),
    path("station-activity/<int:connection_id>/",
         get_station_activity_log,
         name="get_station_activity_log_with_date"),

]
