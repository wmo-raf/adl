import json

from django.shortcuts import render
from django.urls import reverse
from wagtail.api.v2.utils import get_full_url

from adl.core.models import AdlSettings


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


def data_availability_summary_view(request):
    context = {
        "api_url": get_full_url(request, "/api"),
    }
    
    return render(request, 'viewer/data_availability_summary.html', context)
