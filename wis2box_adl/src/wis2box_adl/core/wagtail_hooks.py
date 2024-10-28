from django.urls import reverse, path
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.widgets import HeaderButton
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup, IndexView

from .home import NetworksSummaryItem, StationsSummaryItem, PluginsSummaryItem
from .models import Network, Station, DataParameter
from .views import (
    load_stations_csv,
    load_stations_oscar,
    download_stations_csv_template,
    import_oscar_station, plugin_events_data
)

wis2box_adl_register_plugin_menu_items_hook_name = "register_wis2box_adl_plugin_menu_items"


@hooks.register('register_admin_urls')
def urlconf_wis2box_adl():
    return [
        path('wis2box-adl/load-stations-csv/', load_stations_csv, name='load_stations_csv'),
        path('wis2box-adl/stations-template/', download_stations_csv_template, name='download_stations_csv_template'),
        path('wis2box-adl/load-stations-oscar/', load_stations_oscar, name='load_stations_oscar'),
        path('wis2box-adl/import-oscar-station/<str:wigos_id>', import_oscar_station, name='import_oscar_station'),
        path('wis2box-adl/plugin-events-data', plugin_events_data, name='plugin_events_data'),
    ]


class NetworkViewSet(SnippetViewSet):
    model = Network
    menu_icon = "circle-nodes"
    add_to_admin_menu = True


register_snippet(NetworkViewSet)


class StationIndexView(IndexView):
    list_display = ["name", "network", "station_id", "wigos_id"]
    list_filter = ["network", ]

    @cached_property
    def header_buttons(self):
        buttons = super().header_buttons

        buttons.extend([
            HeaderButton(
                label=_('Load Stations from CSV'),
                url=reverse("load_stations_csv"),
                icon_name="plus",
            ),
            HeaderButton(
                label=_('Load Stations from OSCAR Surface'),
                url=reverse("load_stations_oscar"),
                icon_name="plus",
            )]
        )

        return buttons


class StationViewSet(SnippetViewSet):
    model = Station
    index_view_class = StationIndexView
    menu_icon = "map-pin"
    add_to_admin_menu = True


register_snippet(StationViewSet)


class DataParameterViewSet(SnippetViewSet):
    model = DataParameter


class PluginsViewSetGroup(SnippetViewSetGroup):
    menu_label = _('Plugins')
    menu_name = "wis2box_adl_plugins"
    menu_icon = "plug"

    def get_submenu_items(self):
        menu_items = super().get_submenu_items()

        for fn in hooks.get_hooks(wis2box_adl_register_plugin_menu_items_hook_name):
            hook_menu_items = fn()
            if isinstance(hook_menu_items, list):
                menu_items.extend(hook_menu_items)

        return menu_items


register_snippet(PluginsViewSetGroup)


@hooks.register('construct_main_menu')
def hide_some_menus(request, menu_items):
    hidden_menus = ["explorer", "documents", "images", "help", "snippets"]

    menu_items[:] = [item for item in menu_items if item.name not in hidden_menus]


# @hooks.register('construct_homepage_panels')
# def add_plugin_monitoring_panel(request, panels):
#     plugin_monitoring_panel = PluginMonitoringPanel()
#     panels.append(plugin_monitoring_panel)


@hooks.register('construct_homepage_summary_items')
def construct_homepage_summary_items(request, summary_items):
    hidden_summary_items = ["PagesSummaryItem", "DocumentsSummaryItem", "ImagesSummaryItem"]

    summary_items[:] = [item for item in summary_items if item.__class__.__name__ not in hidden_summary_items]

    summary_items.extend([
        NetworksSummaryItem(request),
        StationsSummaryItem(request),
        PluginsSummaryItem(request),
    ])


@hooks.register("register_icons")
def register_icons(icons):
    return icons + [
        'wagtailfontawesomesvg/solid/circle-nodes.svg',
        'wagtailfontawesomesvg/solid/map-pin.svg',
        'wagtailfontawesomesvg/solid/location-pin.svg',
        'wagtailfontawesomesvg/solid/location-dot.svg',
        'wagtailfontawesomesvg/solid/plug.svg',
    ]
