from django.urls import path

from .views import table_view, chart_view, map_view

urlpatterns = [
    path("table/", table_view, name="viewer_table"),
    path("chart/", chart_view, name="viewer_chart"),
    path("map/", map_view, name="viewer_map"),
]
