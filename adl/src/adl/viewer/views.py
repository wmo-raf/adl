from django.shortcuts import render
from wagtail.api.v2.utils import get_full_url


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
