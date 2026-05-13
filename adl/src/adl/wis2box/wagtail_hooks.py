from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.admin.viewsets import ViewSetGroup
from wagtail.admin.viewsets.base import ViewSet

from . import views


@hooks.register("register_admin_urls")
def register_wis2box_urls():
    return [
        path("wis2box/stations/", views.wis2box_stations, name="wis2box_stations"),
        path("wis2box/stations/import/<str:wigos_id>/", views.import_wis2box_station, name="import_wis2box_station"),
    ]


@hooks.register('construct_settings_menu')
def hide_some_setting_menu_items(request, menu_items):
    hidden_items = ['wis2box-settings', ]
    
    menu_items[:] = [item for item in menu_items if item.name not in hidden_items]


class Wis2boxStationsViewSet(ViewSet):
    menu_label = _("Stations")
    icon = "cog"
    name = "wis2box/stations"
    
    def get_urlpatterns(self):
        return [
            path('', views.wis2box_stations, name='wis2box_stations'),
        ]


class Wis2BoxSettingsViewSetGroup(ViewSetGroup):
    menu_label = _("WIS2Box Stations")
    menu_icon = "cog"
    add_to_settings_menu = True
    menu_order = 900
    
    def get_submenu_items(self):
        menu_items = super(Wis2BoxSettingsViewSetGroup, self).get_submenu_items()
        
        wis2box_menus = [
            MenuItem(
                _("Settings"),
                reverse("wagtailsettings:edit", args=[
                    "wis2box", "wis2boxsettings",
                ]),
                icon_name="cog",
                order=100,
            ),
            MenuItem(
                _("Stations"),
                reverse("wis2box_stations"),
                icon_name="map-pin",
                order=200,
            )
        ]
        
        menu_items.extend(wis2box_menus)
        
        return menu_items


@hooks.register("register_admin_viewset")
def register_viewsets():
    return [
        Wis2BoxSettingsViewSetGroup()
    ]
