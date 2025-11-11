from django.urls import include
from django.urls import path
from wagtail import hooks

from .panels import StationActivityPanel
from .views import (
    task_monitor,
    get_active_tasks_by_network
)
from .viewsets import MonitoringViewSetGroup


@hooks.register('register_admin_urls')
def urlconf_adl_monitoring():
    return [
        path('events/', include('django_eventstream.urls')),
        path('monitoring/', include('adl.monitoring.urls')),
        path('tasks/active/', get_active_tasks_by_network, name='active_tasks'),
        path('tasks/active/network/<int:network_id>/', get_active_tasks_by_network, name='active_tasks_by_network'),
    ]


@hooks.register('construct_homepage_panels')
def add_plugin_monitoring_panels(request, panels):
    panels.append(StationActivityPanel())


@hooks.register("register_admin_viewset")
def register_viewset():
    return MonitoringViewSetGroup()
