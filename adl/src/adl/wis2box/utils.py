import logging

import requests
from django.core.cache import cache
from pyoscar import OSCARClient

logger = logging.getLogger(__name__)

CACHE_KEY = "wis2box_stations"
CACHE_TTL = 60 * 10  # 10 minutes

OSCAR_RECORDS_CACHE_TTL = 60 * 20  # 20 minutes, as for the OSCAR station loader

# wis2box's pygeoapi pages at 500 items unless asked for more (max 10000);
# a truncated station list would make stations already on wis2box look ADL-only
WIS2BOX_ITEMS_LIMIT = 10000


def _stations_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + f"/oapi/collections/stations/items?f=json&limit={WIS2BOX_ITEMS_LIMIT}"


def _discovery_metadata_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + f"/oapi/collections/discovery-metadata/items?f=json&limit={WIS2BOX_ITEMS_LIMIT}"


def _normalize_feature(feature: dict) -> dict:
    """
    Flatten a single GeoJSON feature from the wis2box station endpoint
    into a plain dict with consistent keys.
    """
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []

    longitude = coords[0] if len(coords) > 0 else None
    latitude  = coords[1] if len(coords) > 1 else None
    elevation = coords[2] if len(coords) > 2 else None

    return {
        "wigos_id":      props.get("wigos_station_identifier") or feature.get("id"),
        "name":          props.get("name"),
        "longitude":     longitude,
        "latitude":      latitude,
        "elevation":     elevation,
        "territory":     props.get("territory_name"),
        "status":        props.get("status"),
        "facility_type": props.get("facility_type"),
        "topics":        props.get("topics") or [],
        "oscar_url":     props.get("url"),
    }


def get_stations_from_wis2box(base_url: str, as_dict: bool = False):
    """
    Fetch all stations from the wis2box OGC API Features endpoint.

    Returns a list of normalised station dicts, or a dict keyed by
    wigos_id when ``as_dict=True``.

    Raises ``requests.RequestException`` on network or HTTP failure so
    the caller can handle and surface the error message.
    """
    url = _stations_endpoint(base_url)
    response = requests.get(url, timeout=15)
    response.raise_for_status()

    data     = response.json()
    features = data.get("features") or []
    stations = [_normalize_feature(f) for f in features]

    # Drop any entries where we could not resolve a wigos_id
    stations = [s for s in stations if s["wigos_id"]]

    if as_dict:
        return {s["wigos_id"]: s for s in stations}

    return stations


def get_wis2box_stations_cached(base_url: str, refresh: bool = False, as_dict: bool = False):
    """
    Wrapper around ``get_stations_from_wis2box`` that adds a 10-minute
    Django cache layer.

    Pass ``refresh=True`` to bypass the cache, re-fetch, and re-prime it.

    Returns ``(stations, error_string_or_None)``.
    """
    if not refresh:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            if as_dict:
                return {s["wigos_id"]: s for s in cached}, None
            return cached, None

    try:
        stations = get_stations_from_wis2box(base_url)
        cache.set(CACHE_KEY, stations, timeout=CACHE_TTL)
    except Exception as exc:
        logger.exception("Failed to fetch wis2box stations from %s", base_url)
        # Return whatever is still in cache (may be stale) rather than nothing
        stale = cache.get(CACHE_KEY) or []
        if as_dict:
            return {s["wigos_id"]: s for s in stale}, str(exc)
        return stale, str(exc)

    if as_dict:
        return {s["wigos_id"]: s for s in stations}, None
    return stations, None


def get_wis2box_topics(base_url: str):
    """
    The topic hierarchies of the datasets configured on wis2box, the only
    topics ``wis2box metadata station publish-collection`` accepts.

    Raises ``requests.RequestException`` on network or HTTP failure.
    """
    response = requests.get(_discovery_metadata_endpoint(base_url), timeout=15)
    response.raise_for_status()

    features = response.json().get("features") or []
    topics = {(f.get("properties") or {}).get("wmo:topicHierarchy") for f in features}
    return sorted(t for t in topics if t)


def get_oscar_station_records(country):
    """
    Raw OSCAR station-search records for ``country``, with a 20-minute cache.

    Unlike ``adl.core.utils.get_stations_for_country_live`` this keeps the
    whole record, including the region, territory and station type labels
    that wis2box station metadata needs. Raises on OSCAR failure.
    """
    cache_key = f"{country.alpha3}_oscar_station_records"
    records = cache.get(cache_key)

    if records is None:
        results = OSCARClient().get_stations(country=country.alpha3)
        records = results.get("stationSearchResults") or []
        cache.set(cache_key, records, timeout=OSCAR_RECORDS_CACHE_TTL)

    return records
