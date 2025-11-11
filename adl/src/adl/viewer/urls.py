from django.urls import path

from .views import (
    table_view,
    chart_view,
    map_view,
    latest_records_mvt,
    nearest_records_mvt
)

urlpatterns = [
    path("table/", table_view, name="viewer_table"),
    path("chart/", chart_view, name="viewer_chart"),
    path("map/", map_view, name="viewer_map"),
    path('tiles/latest/<int:z>/<int:x>/<int:y>.pbf', latest_records_mvt, name='latest_records_mvt'),
    path('tiles/nearest/<int:z>/<int:x>/<int:y>.pbf', nearest_records_mvt, name='nearest_records_mvt'),
]
