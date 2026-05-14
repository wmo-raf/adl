from django.urls import path

from .views import country_boundary_proxy, widget_display_view

urlpatterns = [
    path("widget/<uuid:widget_uuid>/", widget_display_view, name="widget_display"),
    path("country-boundary/<str:iso3>/", country_boundary_proxy, name="country_boundary_proxy"),
]
