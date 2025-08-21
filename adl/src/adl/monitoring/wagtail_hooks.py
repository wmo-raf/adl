from django.urls import include, path
from wagtail import hooks

from .panels import StationActivityPanel


@hooks.register('register_admin_urls')
def urlconf_adl_monitoring():
    return [
        path('monitoring/', include('adl.monitoring.urls')),
    ]


@hooks.register('construct_homepage_panels')
def add_plugin_monitoring_panels(request, panels):
    panels.append(StationActivityPanel())
