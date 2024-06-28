from django.urls import reverse, path
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.admin.widgets import HeaderButton
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup, IndexView

from .models import Network, Station, AdlSettings, DataParameter
from .views import (
    load_stations_csv,
    load_stations_oscar,
    download_stations_csv_template,
    import_oscar_station
)

wis2box_adl_register_menu_items_hook_name = "register_wis2box_adl_menu_items"


@hooks.register('register_admin_urls')
def urlconf_wis2box_adl():
    return [
        path('wis2box-adl/load-stations-csv/', load_stations_csv, name='load_stations_csv'),
        path('wis2box-adl/stations-template/', download_stations_csv_template, name='download_stations_csv_template'),
        path('wis2box-adl/load-stations-oscar/', load_stations_oscar, name='load_stations_oscar'),
        path('wis2box-adl/import-oscar-station/<str:wigos_id>', import_oscar_station, name='import_oscar_station'),
    ]


class NetworkViewSet(SnippetViewSet):
    model = Network


class StationIndexView(IndexView):
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


class DataParameterViewSet(SnippetViewSet):
    model = DataParameter


class WIS2BoxAdlViewSetGroup(SnippetViewSetGroup):
    items = (NetworkViewSet, StationViewSet,)
    menu_label = _('WIS2Box ADL')
    menu_name = "wis2box_adl"

    def get_submenu_items(self):
        menu_items = super().get_submenu_items()

        try:
            settings_url = reverse(
                "wagtailsettings:edit",
                args=[AdlSettings._meta.app_label, AdlSettings._meta.model_name, ],
            )
            gm_settings_menu = MenuItem(label=_("Settings"), url=settings_url, icon_name="cog")
            menu_items.append(gm_settings_menu)
        except Exception:
            pass

        for fn in hooks.get_hooks(wis2box_adl_register_menu_items_hook_name):
            hook_menu_items = fn()
            if isinstance(hook_menu_items, list):
                menu_items.extend(hook_menu_items)

        return menu_items


register_snippet(WIS2BoxAdlViewSetGroup)


@hooks.register('construct_settings_menu')
def hide_settings_menu_item(request, menu_items):
    hidden_settings = ["adl-settings", ]
    menu_items[:] = [item for item in menu_items if item.name not in hidden_settings]
