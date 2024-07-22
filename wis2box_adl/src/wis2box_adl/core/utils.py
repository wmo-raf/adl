import logging
import re

from django.contrib.gis.geos import Polygon, Point
from pyoscar import OSCARClient

from .constants import DATA_PARAMETERS_DICT

logger = logging.getLogger(__name__)


def get_data_parameters_as_choices():
    return [(key, value["name"]) for key, value in DATA_PARAMETERS_DICT.items()]


def create_default_data_parameters():
    from .models import DataParameter

    logger.info("Creating default data parameters")

    for key, value in DATA_PARAMETERS_DICT.items():
        data = {
            "name": value.get("name"),
            "parameter": key,
            "unit": value.get("unit"),
            "description": value.get("description"),
        }

        if DataParameter.objects.filter(parameter=key).exists():
            logger.info(f"Data parameter with parameter {key} already exists")
            continue

        logger.info(f"Creating data parameter with parameter {key} ...")
        DataParameter.objects.create(**data)

    logger.info("Default data parameters created successfully")


def is_valid_wigos_id(wigos_id):
    """
    Validates if the given string is a valid WMO WIGOS ID.

    Args:
    wigos_id (str): The WIGOS ID to validate.

    Returns:
    bool: True if the WIGOS ID is valid, False otherwise.
    """
    # Define the regular expression pattern for a valid WIGOS ID
    pattern = r"^\d+-\d+-\d+-\d+$"

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
    wmo_block_number = wsi_local[:2]
    wmo_station_number = wsi_local[2:]

    return {
        "wsi_series": wsi_series,
        "wsi_issuer": wsi_issuer,
        "wsi_issue_number": wsi_issue_number,
        "wsi_local": wsi_local,
        "wmo_block_number": wmo_block_number,
        "wmo_station_number": wmo_station_number
    }


def get_stations_for_country(country, as_dict=False):
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


def get_object_or_none(model_class, **kwargs):
    try:
        return model_class.objects.get(**kwargs)
    except model_class.DoesNotExist:
        return None
