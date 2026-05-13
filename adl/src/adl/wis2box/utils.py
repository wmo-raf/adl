import logging

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = "wis2box_stations"
CACHE_TTL = 60 * 10  # 10 minutes


def _stations_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/oapi/collections/stations/items?f=json"


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
