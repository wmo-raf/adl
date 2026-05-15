from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from rest_framework.reverse import reverse_lazy
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from adl.core.table import LinkColumn
from adl.core.viewsets import AdletViewSet
from .models import WidgetDisplay
from .views import pg_tileserver_settings


@hooks.register("register_icons")
def register_icons(icons):
    return icons + [
        'wagtailfontawesomesvg/solid/chart-line.svg',
        'wagtailfontawesomesvg/solid/clipboard-check.svg',
        'wagtailfontawesomesvg/solid/desktop.svg',
    ]


@hooks.register('register_admin_urls')
def urlconf_adl_viewer():
    return [
        path('viewer/', include('adl.viewer.urls')),
        path('pg-tileserv-settings/', pg_tileserver_settings, name='pg_tileserver_settings'),
    ]


def get_widget_display_url(widget):
    return widget.display_url


class WidgetDisplayViewSet(AdletViewSet):
    model = WidgetDisplay
    icon = "desktop"
    menu_label = "Display Widgets"
    add_to_admin_menu = False
    list_display = [
        "name",
        "default_view",
        "rotation_interval",
        "poll_interval",
        LinkColumn("display_url", label=_("Display URL"), get_url=get_widget_display_url,
                   link_attrs={"target": "_blank"}),
    ]


@hooks.register("register_admin_viewset")
def register_viewer_viewsets():
    return WidgetDisplayViewSet("widget_display_viewset")


@hooks.register('register_admin_menu_item')
def register_viewer_menu_item():
    settings_submenu = Menu(items=[
        MenuItem(_('TileServer'), reverse_lazy("pg_tileserver_settings"), icon_name='site'),
    ])
    
    submenu = Menu(items=[
        MenuItem(_('Table'), reverse_lazy('viewer_table'), icon_name='table'),
        MenuItem(_('Chart'), reverse_lazy('viewer_chart'), icon_name='chart-line'),
        MenuItem(_('Map'), reverse_lazy("viewer_map"), icon_name='site'),
        MenuItem(_('Quality Control'), reverse_lazy("qc_view"), icon_name='clipboard-check'),
        MenuItem(_('Display Widgets'), reverse_lazy("widget_display_viewset:index"), icon_name='desktop'),
        SubmenuMenuItem(_('Settings'), settings_submenu, icon_name='cog'),
    ])
    
    return SubmenuMenuItem(_("Data"), submenu, icon_name='site')
