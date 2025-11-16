import importlib
import logging
import re

import pandas as pd
from django.apps import apps
from django.contrib.gis.geos import Polygon, Point
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext
from pyoscar import OSCARClient
from wagtail.admin.viewsets.model import ModelViewSet
from wagtail.admin.widgets import ListingButton

from adl.core.registries import (
    station_link_viewset_registry,
    connection_viewset_registry,
    dispatch_channel_viewset_registry
)
from adl.core.registry import Instance
from adl.core.table import LinkColumnWithIcon

logger = logging.getLogger(__name__)


def is_valid_wigos_id(wigos_id):
    """
    Validates if the given string is a valid WMO WIGOS ID.

    Args:
    wigos_id (str): The WIGOS ID to validate.

    Returns:
    bool: True if the WIGOS ID is valid, False otherwise.
    """
    # Define the regular expression pattern for a valid WIGOS ID
    pattern = r"^\d+-\d+-\d+-\w+$"
    
    # Use the re.match function to check if the input string matches the pattern
    if re.match(pattern, wigos_id):
        return True
    else:
        return False


def get_wigos_id_parts(wigos_id):
    parts = wigos_id.split("-")
    
    wsi_series = parts[0]
    wsi_issuer = parts[1]
    wsi_issue_number = parts[2]
    wsi_local = parts[3]
    
    return {
        "wsi_series": wsi_series,
        "wsi_issuer": wsi_issuer,
        "wsi_issue_number": wsi_issue_number,
        "wsi_local": wsi_local,
    }


def get_stations_for_country_live(country, as_dict=False):
    client = OSCARClient()
    iso = country.alpha3
    
    stations = client.get_stations(country=iso)
    results = stations.get("stationSearchResults")
    
    stations = []
    
    bounds = country.geo_extent
    bounds_polygon = Polygon.from_bbox(bounds)
    
    for station in results:
        wigos_id = station.get("wigosId")
        longitude = station.get("longitude")
        latitude = station.get("latitude")
        
        wigos_station_identifiers = station.get("wigosStationIdentifiers")
        
        if not wigos_id and wigos_station_identifiers:
            wigos_id = wigos_station_identifiers[0].get("wigosStationIdentifier")
        
        if not wigos_id and not longitude and latitude:
            continue
        
        station_data = {
            "wigos_id": wigos_id,
            "name": station.get("name"),
            "elevation": station.get("elevation"),
            "longitude": station.get("longitude"),
            "latitude": station.get("latitude"),
        }
        
        point = Point(x=longitude, y=latitude)
        if not bounds_polygon.contains(point):
            station_data["out_of_bounds"] = True
        
        stations.append(station_data)
    
    if as_dict:
        stations = {station["wigos_id"]: station for station in stations}
    
    return stations


def get_stations_for_country_local(as_dict=False):
    from .models import OscarSurfaceStationLocal
    
    stations = OscarSurfaceStationLocal.objects.all().values()
    
    if as_dict:
        stations = {station.get("wigos_id"): station for station in stations}
    
    return stations


def get_object_or_none(model_class, **kwargs):
    try:
        return model_class.objects.get(**kwargs)
    except model_class.DoesNotExist:
        return None


def get_station_directory_path(ingestion_record, filename):
    wigos_id = ingestion_record.station.wigos_id
    date = ingestion_record.utc_time.strftime("%Y/%m/%d")
    
    return f"station_data/{wigos_id}/{date}/{filename}"


def extract_digits(s):
    # Regular expression to match the first continuous digits
    match = re.match(r"(\d+)", s)
    if match:
        return match.group(0)
    return None


def validate_as_integer(value):
    try:
        int(value)
    except ValueError:
        raise ValidationError("The value must be an integer")


def create_ingestion_file_with_hourly_time(ingestion_record):
    df = pd.read_csv(ingestion_record.file.path)
    
    new_time = ingestion_record.next_top_of_hour
    
    # Update the observation year, month, day, hour, and minute
    df["year"] = new_time.year
    df["month"] = new_time.month
    df["day"] = new_time.day
    df["hour"] = new_time.hour
    df["minute"] = new_time.minute
    
    csv_content = df.to_csv(index=False)
    file = ContentFile(csv_content, ingestion_record.filename)
    
    return file


def get_all_child_models(base_model):
    """
    Get all child models of a polymorphic base model.
    """
    # Get all models in the current project
    all_models = apps.get_models()
    
    # Filter models that inherit from the base_model
    child_models = [
        model for model in all_models if issubclass(model, base_model) and model is not base_model
    ]
    return child_models


def get_child_model_by_name(base_model, model_name):
    """
    Get a child model of a polymorphic base model by name.
    """
    child_models = get_all_child_models(base_model)
    
    for model in child_models:
        verbose_name = model._meta.verbose_name
        
        # try with the model name
        if model.__name__.lower() == model_name.lower():
            return model
        
        # try with the verbose name
        if verbose_name.lower() == model_name.lower():
            return model
    
    return None


def get_model_by_string_label(model_string_label):
    """
    Get a model by its string label.
    """
    
    try:
        model = apps.get_model(model_string_label)
    except LookupError:
        return None
    
    return model


def get_custom_unit_context_entries():
    from adl.core.registries import custom_unit_context_registry
    
    return custom_unit_context_registry.get_choices()


def import_class_by_string_label(class_path):
    # Split the string into module and class name
    module_path, class_name = class_path.rsplit('.', 1)
    
    # Import the module
    module = importlib.import_module(module_path)
    
    # Get the class from the module
    return getattr(module, class_name)


def make_registrable_viewset(model_cls, **kwargs):
    from adl.core.viewsets import AdletViewSet, AdletIndexView
    
    icon = kwargs.get("icon", "snippet")
    list_display = kwargs.get("list_display", None)
    list_filter = kwargs.get("list_filter", None)
    index_view_class = kwargs.get("index_view_class", AdletIndexView)
    inspect_view_enabled = kwargs.get("inspect_view_enabled", False)
    inspect_view_class = kwargs.get("inspect_view_class", None)
    inspect_template_name = kwargs.get("inspect_template_name", None)
    add_view_class = kwargs.get("add_view_class", None)
    edit_view_class = kwargs.get("edit_view_class", None)
    delete_view_class = kwargs.get("delete_view_class", None)
    
    model_name = model_cls._meta.model_name
    viewset_name = f"{model_name.title()}ViewSet"
    
    attrs = {
        "model": model_cls,
        "add_to_admin_menu": False,
        "type": model_name,
        "icon": icon,
        "index_view_class": index_view_class or AdletIndexView,
        "inspect_view_enabled": inspect_view_enabled,
    }
    
    if add_view_class:
        attrs["add_view_class"] = add_view_class
    if edit_view_class:
        attrs["edit_view_class"] = edit_view_class
    if delete_view_class:
        attrs["delete_view_class"] = delete_view_class
    
    if list_display:
        attrs["list_display"] = list_display
    
    if list_filter:
        attrs["list_filter"] = list_filter
    
    if inspect_view_enabled and inspect_view_class:
        attrs["inspect_view_class"] = inspect_view_class
        
        if inspect_template_name:
            @cached_property
            def custom_inspect_template_name(self):
                return inspect_template_name
            
            attrs["inspect_template_name"] = custom_inspect_template_name
    
    # Dynamically create the subclass
    ViewSetCls = type(viewset_name, (AdletViewSet, Instance), attrs)
    
    return ViewSetCls()


def get_connection_list_more_buttons(connection):
    buttons = []
    if hasattr(connection, "get_extra_model_admin_links"):
        extra_links = connection.get_extra_model_admin_links()
        for link in extra_links:
            label = link.get("label", None)
            url = link.get("url", None)
            icon_name = link.get("icon_name", "link")
            attrs = link.get("kwargs", {}).get("attrs", {})
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


def get_dispatch_channel_more_buttons(instance):
    buttons = []
    label = gettext("Station Links")
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


def get_connection_station_link_url(connection):
    if hasattr(connection, "get_station_link_url"):
        station_link_url = connection.get_station_link_url()
    else:
        if hasattr(connection, "station_link_model_string_label"):
            station_link_model = get_model_by_string_label(connection.station_link_model_string_label)
            station_link_viewset = station_link_viewset_registry.get(station_link_model._meta.model_name)
            conn_filter_param = f"network_connection={connection.id}"
            station_link_url = reverse(station_link_viewset.get_url_name("index")) + f"?{conn_filter_param}"
        else:
            station_link_url = None
    return station_link_url


def make_registrable_connection_viewset(model_cls, **kwargs):
    from adl.core.viewsets import (
        ConnectionIndexView,
        ConnectionCreateView,
        ConnectionEditView,
        ConnectionDeleteView
    )
    
    icon = kwargs.get("icon", "snippet")
    list_filter = kwargs.get("list_filter", None)
    
    model_name = model_cls._meta.model_name
    viewset_name = f"{model_name.title()}ViewSet"
    
    column = LinkColumnWithIcon("stations_link", label=gettext("Stations Link"), icon_name="map-pin",
                                get_url=get_connection_station_link_url)
    list_display = ["__str__", column, "plugin_processing_enabled", "plugin_processing_interval"] + list(
        getattr(model_cls, "extra_list_display", []))
    
    attrs = {
        "model": model_cls,
        "add_to_admin_menu": False,
        "type": model_name,
        "icon": icon,
        "list_display": list_display,
        "index_view_class": ConnectionIndexView,
        "add_view_class": ConnectionCreateView,
        "edit_view_class": ConnectionEditView,
        "delete_view_class": ConnectionDeleteView,
    }
    
    if list_filter:
        attrs["list_filter"] = list_filter
    
    # Dynamically create the subclass
    ViewSetCls = type(viewset_name, (ModelViewSet, Instance), attrs)
    
    return ViewSetCls()


def get_url_for_connection(connection, view_name, takes_args=False):
    from adl.core.models import NetworkConnection
    model_cls = get_child_model_by_name(NetworkConnection, connection._meta.model_name)
    viewset = connection_viewset_registry.get(model_cls._meta.model_name)
    
    if takes_args:
        return reverse(viewset.get_url_name(view_name), kwargs={"pk": connection.pk})
    
    return reverse(viewset.get_url_name(view_name))


def get_url_for_dispatch_channel(dispatch_channel, view_name, takes_args=False):
    from adl.core.models import DispatchChannel
    model_cls = get_child_model_by_name(DispatchChannel, dispatch_channel._meta.model_name)
    viewset = dispatch_channel_viewset_registry.get(model_cls._meta.model_name)
    
    if takes_args:
        return reverse(viewset.get_url_name(view_name), kwargs={"pk": dispatch_channel.pk})
    
    return reverse(viewset.get_url_name(view_name))
