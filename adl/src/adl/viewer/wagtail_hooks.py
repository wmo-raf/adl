from django.urls import include, path, reverse
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem
from django.utils.translation import gettext_lazy as _


@hooks.register('register_admin_urls')
def urlconf_adl_viewer():
    return [
        path('viewer/', include('adl.viewer.urls')),
    ]


@hooks.register('register_admin_menu_item')
def register_viewer_menu_item():
    submenu = Menu(items=[
        MenuItem(_('Table'), reverse('viewer_table'), icon_name='table'),
        MenuItem(_('Map'), "#", icon_name='site'),
    ])
    
    return SubmenuMenuItem(_("Data Viewer"), submenu, icon_name='site')
