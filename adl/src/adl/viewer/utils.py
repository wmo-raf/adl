import requests
from django.conf import settings
from django.http import HttpResponse
from requests.adapters import HTTPAdapter

_session = None

ADL_PG_TILESERV_BASE_URL = getattr(settings, "ADL_PG_TILESERV_BASE_URL", "")


def get_tileserv_session():
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=50)
        _session.mount('http://', adapter)
    return _session


def _fetch_pg_tileserv_mvt_tile(url_path, z, x, y, params):
    """
    Internal helper to fetch MVT tiles from pg_tileserv
    """
    if not ADL_PG_TILESERV_BASE_URL:
        return HttpResponse("No tileserv base url set", status=500)
    
    session = get_tileserv_session()
    url = f"{ADL_PG_TILESERV_BASE_URL}/{url_path}/{z}/{x}/{y}.pbf"
    
    response = session.get(url, params=params)
    return HttpResponse(response.content, content_type='application/vnd.mapbox-vector-tile')
