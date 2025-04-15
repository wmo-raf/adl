from django.urls import reverse, path
from django.urls.exceptions import NoReverseMatch
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.admin.widgets import HeaderButton
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet, IndexView
from wagtail_modeladmin.helpers import AdminURLHelper, ButtonHelper
from wagtail_modeladmin.options import ModelAdmin, modeladmin_register

from .constants import PREDEFINED_DATA_PARAMETERS
from .home import (
    NetworksSummaryItem,
    StationsSummaryItem,
    PluginsSummaryItem
)
from .models import (
    Network,
    Station,
    DataParameter,
    NetworkConnection,
    DispatchChannel,
    Unit
)
from .utils import (
    get_all_child_models,
    get_model_by_string_label
)
from .views import (
    load_stations_csv,
    load_stations_oscar,
    import_oscar_station,
    connections_list,
    connection_add_select,
    dispatch_channels_list,
    dispatch_channel_add_select,
    create_predefined_data_parameters
)

adl_register_plugin_menu_items_hook_name = "register_adl_plugin_menu_items"


@hooks.register('register_admin_urls')
def urlconf_adl():
    return [
        path('adl/load-stations-oscar-csv/', load_stations_csv, name='load_stations_oscar_csv'),
        path('adl/load-stations-oscar/', load_stations_oscar, name='load_stations_oscar'),
        path('adl/import-oscar-station/<str:wigos_id>', import_oscar_station, name='import_oscar_station'),
        path('adl/create-predefined-data-parameters', create_predefined_data_parameters,
             name='create_predefined_data_parameters'),
        path('adl/connections/', connections_list, name="connections_list"),
        path('adl/connections/select', connection_add_select, name="connections_add_select"),
        path('adl/dispatch-channels', dispatch_channels_list, name="dispatch_channels_list"),
        path('adl/dispatch-channels/select', dispatch_channel_add_select, name="dispatch_channel_add_select"),
    ]


class NetworkAdmin(ModelAdmin):
    model = Network
    base_url_path = "network"
    menu_icon = "circle-nodes"
    add_to_admin_menu = True
    menu_order = 100


modeladmin_register(NetworkAdmin)


class StationLinkButtonHelper(ButtonHelper):
    def get_buttons_for_obj(self, obj, exclude=None, classnames_add=None, classnames_exclude=None):
        buttons = super().get_buttons_for_obj(obj, exclude, classnames_add, classnames_exclude)
        
        classnames = self.edit_button_classnames + classnames_add
        cn = self.finalise_classname(classnames, classnames_exclude)
        
        if hasattr(obj, "get_extra_model_admin_buttons"):
            buttons.extend(obj.get_extra_model_admin_buttons(classname=cn))
        
        return buttons


# Register all NetworkConnection models
def register_network_connections_models():
    connection_model_cls = get_all_child_models(NetworkConnection)
    
    for model_cls in connection_model_cls:
        station_link_admin = None
        station_link_model = None
        
        if hasattr(model_cls, "station_link_model_string_label"):
            station_link_model = get_model_by_string_label(model_cls.station_link_model_string_label)
            
            if station_link_model:
                class StationLinkAdmin(ModelAdmin):
                    model = station_link_model
                    add_to_admin_menu = False
                    list_filter = ["network_connection"]
                    button_helper_class = StationLinkButtonHelper
                    
                    # add extra list display fields if defined in the model
                    list_display = (["__str__", "enabled"] +
                                    list(getattr(station_link_model, "extra_list_display", [])))
                    
                    def get_queryset(self, request):
                        qs = super().get_queryset(request)
                        
                        network_connection = request.GET.get("network_connection")
                        
                        if network_connection:
                            qs = qs.filter(network_connection=network_connection)
                        
                        return qs
                
                station_link_admin = StationLinkAdmin
        
        class ConnectionAdmin(ModelAdmin):
            model = model_cls
            add_to_admin_menu = False
            
            # add extra list display fields if defined in the model
            list_display = (["__str__", "plugin_processing_enabled"] +
                            list(getattr(model_cls, "extra_list_display", [])))
            
            def __init__(self, parent=None):
                super().__init__(parent)
                
                self.list_display = (list(self.list_display) or []) + ['get_station_link']
                self.get_station_link.__func__.short_description = _('Station Link')
            
            def get_station_link(self, obj):
                station_link_url = None
                
                if hasattr(obj, "get_station_link_url"):
                    station_link_url = obj.get_station_link_url()
                else:
                    if station_link_admin and station_link_model:
                        url_helper = AdminURLHelper(station_link_model)
                        try:
                            station_link_url = url_helper.index_url
                            station_link_url += f"?network_connection={obj.id}"
                        except NoReverseMatch:
                            pass
                
                if station_link_url is None:
                    return None
                
                label = _("Stations Link")
                button_html = f"""
                        <a href="{station_link_url}" class="button button-small button--icon button-secondary">
                            <span class="icon-wrapper">
                                <svg class="icon icon-map-pin icon" aria-hidden="true">
                                    <use href="#icon-map-pin"></use>
                                </svg>
                            </span>
                            {label}
                        </a>
                    """
                return mark_safe(button_html)
        
        # register connection admin
        modeladmin_register(ConnectionAdmin)
        
        # register station link admin
        if station_link_admin:
            modeladmin_register(station_link_admin)


register_network_connections_models()


def register_dispatch_channels_models():
    dispatch_channels_model_cls = get_all_child_models(DispatchChannel)
    
    for model_cls in dispatch_channels_model_cls:
        class DispatchChannelAdmin(ModelAdmin):
            model = model_cls
            add_to_admin_menu = False
        
        modeladmin_register(DispatchChannelAdmin)


register_dispatch_channels_models()


class StationIndexView(IndexView):
    list_display = ["name", "network", "station_id", "wigos_id"]
    list_filter = ["network", ]
    
    @cached_property
    def header_buttons(self):
        buttons = super().header_buttons
        
        buttons.extend([
            HeaderButton(
                label=_('Load Stations from OSCAR Surface'),
                url=reverse("load_stations_oscar"),
                icon_name="plus",
            ),
        ])
        
        return buttons


class StationViewSet(SnippetViewSet):
    model = Station
    base_url_path = "station"
    index_view_class = StationIndexView
    menu_icon = "map-pin"
    add_to_admin_menu = True
    menu_order = 200


register_snippet(StationViewSet)


class UnitViewSet(SnippetViewSet):
    model = Unit
    menu_icon = "list-ul"
    add_to_settings_menu = True
    add_to_admin_menu = False
    list_display = ["name", "symbol", "get_registry_unit"]
    menu_order = 700


register_snippet(UnitViewSet)


class DataParameterIndexView(IndexView):
    @cached_property
    def header_buttons(self):
        buttons = super().header_buttons
        
        has_existing_objects = self.get_queryset().exists()
        
        if not has_existing_objects:
            buttons.extend([
                HeaderButton(
                    label=_('Create from Predefined Data Parameters'),
                    url=reverse("create_predefined_data_parameters"),
                    icon_name="plus",
                ),
            ])
        
        return buttons
    
    def get_context_data(self):
        context = super().get_context_data()
        context["create_predefined_data_parameters_url"] = reverse("create_predefined_data_parameters")
        
        items_count = context.get("items_count")
        
        if items_count == 0:
            context["predefined_data_parameters"] = PREDEFINED_DATA_PARAMETERS
        
        return context


class DataParameterViewSet(SnippetViewSet):
    index_results_template_name = "core/data_parameter_index_results.html"
    model = DataParameter
    index_view_class = DataParameterIndexView
    add_to_settings_menu = True
    menu_order = 800
    menu_icon = "form"


register_snippet(DataParameterViewSet)


@hooks.register('construct_main_menu')
def hide_some_menus(request, menu_items):
    hidden_menus = ["explorer", "documents", "images", "help", "snippets", "reports"]
    
    menu_items[:] = [item for item in menu_items if item.name not in hidden_menus]


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
        'wagtailfontawesomesvg/solid/hourglass-start.svg',
        'wagtailfontawesomesvg/solid/hourglass-end.svg',
        'wagtailfontawesomesvg/solid/hourglass-half.svg',
        'wagtailfontawesomesvg/solid/paper-plane.svg',
    ]


@hooks.register('construct_reports_menu')
def hide_some_report_menu_items(request, menu_items):
    visible_items = ['site-history']
    menu_items[:] = [item for item in menu_items if item.name in visible_items]


@hooks.register('construct_settings_menu')
def hide_some_setting_menu_items(request, menu_items):
    hidden_items = ['workflows', 'workflow-tasks', 'collections', 'redirects']
    
    menu_items[:] = [item for item in menu_items if item.name not in hidden_items]


@hooks.register('register_admin_menu_item')
def register_connections_menu():
    list_url = reverse('connections_list')
    label = _("Connections")
    return MenuItem(label, list_url, icon_name='plug', order=500)


@hooks.register('register_admin_menu_item')
def register_dispatch_channels_menu():
    list_url = reverse('dispatch_channels_list')
    label = _("Dispatch Channels")
    
    return MenuItem(label, list_url, icon_name='resubmit', order=600)
