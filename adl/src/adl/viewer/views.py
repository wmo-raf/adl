import json

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from rest_framework.decorators import permission_classes
from wagtail.admin import messages
from wagtail.api.v2.utils import get_full_url

from adl.api.auth import HasAPIKeyOrIsAuthenticated
from adl.core.models import AdlSettings
from adl.viewer.utils import _fetch_pg_tileserv_mvt_tile, reload_pg_tileserv_index


@permission_classes([HasAPIKeyOrIsAuthenticated])
def latest_records_mvt(request, z, x, y):
    """
    Serve latest observation records as MVT tiles
    Query params: connection_id, parameter_id
    Example: /tiles/latest/10/512/512.pbf?connection_id=123&parameter_id=456
    """
    connection_id = request.GET.get('connection_id')
    parameter_id = request.GET.get('parameter_id')
    
    # Validate required parameters
    if not connection_id or not parameter_id:
        return JsonResponse({
            'error': 'Missing required parameters: connection_id, parameter_id'
        }, status=400)
    
    params = {
        'in_connection_id': connection_id,
        'in_parameter_id': parameter_id,
    }
    return _fetch_pg_tileserv_mvt_tile('public.obs_latest_records_mvt', z, x, y, params)


@permission_classes([HasAPIKeyOrIsAuthenticated])
def nearest_records_mvt(request, z, x, y):
    """
    Serve nearest observation records at given time as MVT tiles
    Query params: connection_id, parameter_id, at_time
    Example: /tiles/nearest/10/512/512.pbf?connection_id=123&parameter_id=456&at_time=2024-10-28T12:00:00
    """
    connection_id = request.GET.get('connection_id')
    parameter_id = request.GET.get('parameter_id')
    at_time = request.GET.get('at_time')
    
    # Validate required parameters
    if not connection_id or not parameter_id or not at_time:
        return JsonResponse({
            'error': 'Missing required parameters: connection_id, parameter_id, at_time'
        }, status=400)
    
    params = {
        'in_connection_id': connection_id,
        'in_parameter_id': parameter_id,
        'in_datetime': at_time,
    }
    return _fetch_pg_tileserv_mvt_tile('public.obs_nearest_records_mvt', z, x, y, params)


def table_view(request):
    context = {
        "api_url": get_full_url(request, "/api"),
    }
    
    return render(request, 'viewer/table.html', context)


def chart_view(request):
    context = {
        "api_url": get_full_url(request, "/api"),
    }
    
    return render(request, 'viewer/chart.html', context)


def map_view(request):
    adl_settings = AdlSettings.for_request(request)
    
    latest_records_mvt_path = reverse("latest_records_mvt", args=(0, 0, 0)).replace('/0/0/0', '/{z}/{x}/{y}')
    latest_records_mvt_url = get_full_url(request, latest_records_mvt_path)
    
    nearest_records_mvt_path = reverse("nearest_records_mvt", args=(0, 0, 0)).replace('/0/0/0', '/{z}/{x}/{y}')
    nearest_records_mvt_url = get_full_url(request, nearest_records_mvt_path)
    
    context = {
        "api_url": get_full_url(request, "/api"),
        "latest_records_mvt_url": latest_records_mvt_url,
        "nearest_records_mvt_url": nearest_records_mvt_url,
    }
    
    country = adl_settings.country
    if country:
        context.update({
            "bounds": json.dumps(country.geo_extent)
        })
    
    return render(request, 'viewer/map.html', context)


def pg_tileserver_settings(request):
    breadcrumb_items = [
        {"url": reverse("wagtailadmin_home"), "label": "Home"},
        {"url": "", "label": "PgTileServ Settings"},
    ]
    
    context = {
        "page_title": "PgTileServ Settings",
        "breadcrumbs_items": breadcrumb_items,
    }
    
    if request.method == "POST":
        reload_pg_tileserv_index()
        messages.success(request, "PgTileServ settings updated.")
    
    return render(request, 'viewer/tileserver_settings.html', context)
