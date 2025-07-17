import importlib
import logging
import re

import pandas as pd
from django.apps import apps
from django.contrib.gis.geos import Polygon, Point
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils.translation import gettext
from pyoscar import OSCARClient
from wagtail.admin.views import generic
from wagtail.admin.viewsets.model import ModelViewSet
from wagtail.admin.widgets import ListingButton

from adl.core.registries import station_link_viewset_registry
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


def make_registrable_viewset(model_cls, icon="snippet", list_display=None, list_filter=None):
    model_name = model_cls._meta.model_name
    viewset_name = f"{model_name.title()}ViewSet"
    
    attrs = {
        "model": model_cls,
        "add_to_admin_menu": False,
        "type": model_name,
        "icon": icon,
    }
    
    if list_display:
        attrs["list_display"] = list_display
    
    if list_filter:
        attrs["list_filter"] = list_filter
    
    # Dynamically create the subclass
    ViewSetCls = type(viewset_name, (ModelViewSet, Instance), attrs)
    
    return ViewSetCls()


class ConnectionIndexView(generic.IndexView):
    def get_list_more_buttons(self, instance):
        buttons = super().get_list_more_buttons(instance)
        if hasattr(instance, "get_extra_model_admin_links"):
            extra_links = instance.get_extra_model_admin_links()
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
    
    def get_table_kwargs(self):
        table_kwargs = super().get_table_kwargs()
        table_kwargs["template_name"] = "core/card_view.html"
        return table_kwargs


def make_registrable_connection_viewset(model_cls, icon="snippet", station_link_model=None, list_filter=None):
    model_name = model_cls._meta.model_name
    viewset_name = f"{model_name.title()}ViewSet"
    
    def get_station_link_url(obj):
        if hasattr(obj, "get_station_link_url"):
            station_link_url = obj.get_station_link_url()
        else:
            station_link_viewset = station_link_viewset_registry.get(station_link_model._meta.model_name)
            station_link_url = reverse(station_link_viewset.get_url_name("index"))
        
        return station_link_url
    
    column = LinkColumnWithIcon("stations_link", label=gettext("Stations Link"), icon_name="map-pin",
                                get_url=get_station_link_url)
    list_display = ["__str__", column, "plugin_processing_enabled", "plugin_processing_interval"] + list(
        getattr(model_cls, "extra_list_display", []))
    
    attrs = {
        "model": model_cls,
        "add_to_admin_menu": False,
        "type": model_name,
        "icon": icon,
        "list_display": list_display,
        "index_view_class": ConnectionIndexView,
    }
    
    if list_filter:
        attrs["list_filter"] = list_filter
    
    # Dynamically create the subclass
    ViewSetCls = type(viewset_name, (ModelViewSet, Instance), attrs)
    
    return ViewSetCls()
