from django.shortcuts import render
from django.utils.translation import gettext as _
from wagtail.api.v2.utils import get_full_url


def table_view(request):
    context = {
        "page_title": _("Table View"),
        "api_url": get_full_url(request, "/api"),
    }
    
    return render(request, 'viewer/table.html', context)
