from django.urls import include
from django.urls import path
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from .panels import StationActivityPanel
from .views import (
    get_active_tasks_by_network
)


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


@hooks.register('register_admin_menu_item')
def register_monitoring_menu_item():
    submenu = Menu(items=[
        MenuItem(_('Data availability'), reverse_lazy('data_availability'), icon_name='table'),
    ])
    return SubmenuMenuItem(_('Monitoring'), submenu, icon_name='desktop', order=450)
