from django.urls import path

from .views import (
    table_view,
    chart_view,
    map_view,
    data_availability_summary_view
)
from .views.qc import (
    qc_status_view,
    qc_inspect_view
)
from .views.tileserv import (
    latest_records_mvt,
    nearest_records_mvt
)

urlpatterns = [
    path("table/", table_view, name="viewer_table"),
    path("chart/", chart_view, name="viewer_chart"),
    path("map/", map_view, name="viewer_map"),
    path("qc/status/", qc_status_view, name="qc_view"),
    path("qc/inspect/<int:station_id>/", qc_inspect_view, name="qc_inspect"),
    path('tiles/latest/<int:z>/<int:x>/<int:y>.pbf', latest_records_mvt, name='latest_records_mvt'),
    path('tiles/nearest/<int:z>/<int:x>/<int:y>.pbf', nearest_records_mvt, name='nearest_records_mvt'),
    path("data-availability/summary/", data_availability_summary_view, name="data_availability_summary"),
]
