from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from wagtail.admin.ui.tables import BulkActionsCheckboxColumn
from wagtail.admin.views import generic
from wagtail.admin.viewsets.chooser import ChooserViewSet
from wagtail.admin.viewsets.model import ModelViewSet
from wagtail.admin.widgets import HeaderButton, ListingButton

from .constants import PREDEFINED_DATA_PARAMETERS
from .models import (
    Network,
    Station,
    DataParameter,
    Unit
)

ADLET_MODELS = []


class AdletViewSet(ModelViewSet):
    def on_register(self):
        super().on_register()
        
        # Register the model in the global ADLET_MODELS list
        ADLET_MODELS.append(self.model)
        
        self.model.adlet_viewset = self


class AdletIndexView(generic.IndexView):
    template_name = "core/viewset_index.html"
    
    @cached_property
    def columns(self):
        columns = super().columns
        
        # Add a checkbox column for bulk actions
        columns = [
            BulkActionsCheckboxColumn("bulk_actions", obj_type="adlet"),
            *columns,
        ]
        
        return columns


class DispatchChannelIndexView(AdletIndexView):
    def get_list_more_buttons(self, instance):
        buttons = super().get_list_more_buttons(instance)
        
        label = _("Station Links")
        url = reverse("dispatch_channel_station_links", args=[instance.id])
        icon_name = "map-pin"
        attrs = {"target": "_blank"}
        if label and url:
            buttons.append(
                ListingButton(
                    label,
                    url=url,
                    icon_name=icon_name,
                    attrs=attrs,
                )
            )
        
        return buttons


class NetworkViewSet(AdletViewSet):
    model = Network
    base_url_path = "network"
    icon = "circle-nodes"
    index_view_class = AdletIndexView
    add_to_admin_menu = True
    menu_order = 100


class NetworkChooserViewSet(ChooserViewSet):
    model = Network
    icon = "circle-nodes"
    choose_one_text = "Choose Network"
    choose_another_text = "Choose different Network"
    edit_item_text = "Edit this Network"


class StationIndexView(AdletIndexView):
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
    
    def get_table_kwargs(self):
        table_kwargs = super().get_table_kwargs()
        # table_kwargs["template_name"] = "core/station_index_table.html"
        return table_kwargs


class StationViewSet(AdletViewSet):
    model = Station
    index_view_class = StationIndexView
    icon = "map-pin"
    add_to_admin_menu = True
    menu_order = 200
    list_per_page = 50


class StationChooserViewSet(ChooserViewSet):
    model = Station
    icon = "map-pin"
    choose_one_text = "Choose Station"
    choose_another_text = "Choose different Station"
    edit_item_text = "Edit this Station"
    list_per_page = 50


class UnitViewSet(AdletViewSet):
    model = Unit
    icon = "list-ul"
    index_view_class = AdletIndexView
    add_to_settings_menu = True
    list_display = ["name", "symbol", "get_registry_unit"]
    menu_order = 700
    list_per_page = 50


class UnitChooserViewSet(ChooserViewSet):
    model = Unit
    icon = "list-ul"
    index_view_class = AdletIndexView
    choose_one_text = "Choose Unit"
    choose_another_text = "Choose different Unit"
    edit_item_text = "Edit this unit"
    per_page = 50


class DataParameterIndexView(AdletIndexView):
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


class DataParameterViewSet(AdletViewSet):
    model = DataParameter
    index_results_template_name = "core/data_parameter_index_results.html"
    index_view_class = DataParameterIndexView
    add_to_settings_menu = True
    menu_order = 800
    icon = "form"
    list_per_page = 50


class DataParameterChooserViewSet(ChooserViewSet):
    model = DataParameter
    icon = "form"
    choose_one_text = "Choose DataParameter"
    choose_another_text = "Choose different DataParameter"
    edit_item_text = "Edit this DataParameter"
    per_page = 50


admin_viewsets = [
    NetworkViewSet(),
    NetworkChooserViewSet("network_chooser"),
    StationViewSet(),
    StationChooserViewSet("station_chooser"),
    UnitViewSet(),
    UnitChooserViewSet("unit_chooser"),
    DataParameterViewSet(),
    DataParameterChooserViewSet("data_parameter_chooser"),
]
