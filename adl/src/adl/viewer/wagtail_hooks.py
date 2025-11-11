from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from rest_framework.reverse import reverse_lazy
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from .views import pg_tileserver_settings


@hooks.register("register_icons")
def register_icons(icons):
    return icons + [
        'wagtailfontawesomesvg/solid/chart-line.svg',
    ]


@hooks.register('register_admin_urls')
def urlconf_adl_viewer():
    return [
        path('viewer/', include('adl.viewer.urls')),
        path('pg-tileserv-settings/', pg_tileserver_settings, name='pg_tileserver_settings'),
    ]


@hooks.register('register_admin_menu_item')
def register_viewer_menu_item():
    settings_submenu = Menu(items=[
        MenuItem(_('TileServer'), reverse_lazy("pg_tileserver_settings"), icon_name='site'),
    ])
    
    submenu = Menu(items=[
        MenuItem(_('Table'), reverse_lazy('viewer_table'), icon_name='table'),
        MenuItem(_('Chart'), reverse_lazy('viewer_chart'), icon_name='chart-line'),
        MenuItem(_('Map'), reverse_lazy("viewer_map"), icon_name='site'),
        SubmenuMenuItem(_('Settings'), settings_submenu, icon_name='cog'),
    ])
    
    return SubmenuMenuItem(_("Data Viewer"), submenu, icon_name='site')
