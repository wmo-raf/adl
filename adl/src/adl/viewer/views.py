import json

from django.conf import settings
from django.shortcuts import render
from wagtail.api.v2.utils import get_full_url

from adl.core.models import AdlSettings

ADL_PG_TILESERV_BASE_URL = getattr(settings, "ADL_PG_TILESERV_BASE_URL", "")
ADL_PG_TILESERV_BASEPATH = getattr(settings, "ADL_PG_TILESERV_BASEPATH", "")


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
    
    country = adl_settings.country
    
    tileserv_base_url = ADL_PG_TILESERV_BASE_URL
    tileserv_basepath = ADL_PG_TILESERV_BASEPATH
    
    if not tileserv_base_url:
        tileserv_base_url = get_full_url(request, tileserv_basepath)
    
    context = {
        "api_url": get_full_url(request, "/api"),
        "tileserv_base_url": tileserv_base_url,
    }
    
    if country:
        context.update({
            "bounds": json.dumps(country.geo_extent)
        })
    
    return render(request, 'viewer/map.html', context)
