from django.templatetags.static import static
from django.urls import reverse, path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import MenuItem

from .bulk_actions import AdletDeleteBulkAction
from .home import (
    NetworksSummaryItem,
    StationsSummaryItem,
    ConnectionsSummaryItem,
    DispatchChannelsSummaryItem,
    PluginsSummaryItem,
)
from .models import (
    NetworkConnection,
    DispatchChannel
)
from .registries import (
    dispatch_channel_viewset_registry,
    station_link_viewset_registry,
    connection_viewset_registry
)
from .utils import (
    get_all_child_models,
    get_model_by_string_label,
    make_registrable_viewset,
    make_registrable_connection_viewset
)
from .views import (
    load_stations_csv,
    load_stations_oscar,
    import_oscar_station,
    connections_list,
    connection_add_select,
    dispatch_channels_list,
    dispatch_channel_add_select,
    create_predefined_data_parameters,
    get_plugin_list,
    dispatch_channel_station_links
)
from .viewsets import admin_viewsets, DispatchChannelIndexView

adl_register_plugin_menu_items_hook_name = "register_adl_plugin_menu_items"


@hooks.register('register_admin_urls')
def urlconf_adl():
    return [
        path('load-stations-oscar-csv/', load_stations_csv, name='load_stations_oscar_csv'),
        path('load-stations-oscar/', load_stations_oscar, name='load_stations_oscar'),
        path('import-oscar-station/<str:wigos_id>', import_oscar_station, name='import_oscar_station'),
        path('create-predefined-data-parameters/', create_predefined_data_parameters,
             name='create_predefined_data_parameters'),
        path('connections/', connections_list, name="connections_list"),
        path('connections/select/', connection_add_select, name="connections_add_select"),
        path('dispatch-channels/', dispatch_channels_list, name="dispatch_channels_list"),
        path('dispatch-channels/select/', dispatch_channel_add_select, name="dispatch_channel_add_select"),
        path('dispatch-channel/<int:channel_id>/station-links', dispatch_channel_station_links,
             name="dispatch_channel_station_links"),
        path('plugins/', get_plugin_list, name="plugins_list"),
    ]


@hooks.register("insert_editor_js")
def insert_editor_js():
    return format_html(
        '<script src="{}"></script>', static("adl/js/conditional_fields.js"),
    )


# Register all NetworkConnection models
def get_connection_viewsets():
    connection_model_cls = get_all_child_models(NetworkConnection)
    
    station_link_viewsets = []
    connection_viewsets = []
    
    for model_cls in connection_model_cls:
        station_link_model = None
        if hasattr(model_cls, "station_link_model_string_label"):
            station_link_model = get_model_by_string_label(model_cls.station_link_model_string_label)
            if station_link_model:
                station_link_viewset = make_registrable_viewset(station_link_model, list_filter=["network_connection"])
                station_link_viewset_registry.register(station_link_viewset)
                station_link_viewsets.append(station_link_viewset)
        
        connection_viewset = make_registrable_connection_viewset(model_cls, station_link_model=station_link_model,
                                                                 list_filter=["network"])
        connection_viewset_registry.register(connection_viewset)
        connection_viewsets.append(connection_viewset)
    
    return station_link_viewsets + connection_viewsets


def get_dispatch_channels_viewsets():
    dispatch_channels_model_cls = get_all_child_models(DispatchChannel)
    viewsets = []
    
    for model_cls in dispatch_channels_model_cls:
        viewset = make_registrable_viewset(model_cls, index_view_class=DispatchChannelIndexView)
        
        # add this viewset to a local registry so that
        # we can refer to it later
        dispatch_channel_viewset_registry.register(viewset)
        
        viewsets.append(viewset)
    
    return viewsets


@hooks.register("register_admin_viewset")
def register_viewsets():
    connection_viewsets = get_connection_viewsets()
    dispatch_channels_viewsets = get_dispatch_channels_viewsets()
    
    return admin_viewsets + connection_viewsets + dispatch_channels_viewsets


@hooks.register('construct_main_menu')
def hide_some_menus(request, menu_items):
    hidden_menus = ["explorer", "documents", "images", "help", "snippets", "reports"]
    
    menu_items[:] = [item for item in menu_items if item.name not in hidden_menus]


@hooks.register('construct_homepage_summary_items')
def construct_homepage_summary_items(request, summary_items):
    hidden_summary_items = ["PagesSummaryItem", "DocumentsSummaryItem", "ImagesSummaryItem"]
    
    summary_items[:] = [item for item in summary_items if item.__class__.__name__ not in hidden_summary_items]
    
    summary_items[:] = [
        NetworksSummaryItem(request),
        StationsSummaryItem(request),
        ConnectionsSummaryItem(request),
        DispatchChannelsSummaryItem(request),
        PluginsSummaryItem(request),
    ]


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
        'wagtailfontawesomesvg/solid/puzzle-piece.svg',
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


hooks.register("register_bulk_action", AdletDeleteBulkAction)
