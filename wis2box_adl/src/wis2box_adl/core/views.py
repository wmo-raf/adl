import csv
import json

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from wagtail.admin import messages

from .constants import STATION_ATTRIBUTES, OSCAR_SURFACE_REQUIRED_CSV_COLUMNS
from .forms import StationLoaderForm, StationsCSVTemplateDownloadForm, OSCARStationImportForm
from .models import Station, AdlSettings, PluginExecutionEvent, OscarSurfaceStationLocal
from .serializers import PluginExecutionEventSerializer
from .utils import (
    get_stations_for_country_live,
    get_stations_for_country_local,
    get_wigos_id_parts,
    extract_digits
)


def load_stations_csv(request):
    from .wagtail_hooks import StationViewSet
    stations_url = StationViewSet().menu_url

    template_name = "wis2box_adl/load_stations_csv.html"
    context = {}

    overwrite = request.GET.get("overwrite", '').lower()
    overwrite = overwrite in ['1', 'true']

    if request.POST:
        form = StationLoaderForm(request.POST, files=request.FILES)

        if form.is_valid():
            stations_data = form.cleaned_data["stations_data"]

            for data in stations_data:
                new_local_copy_station = {
                    **data,
                }

                wigos_id = new_local_copy_station.get("wigos_id")
                existing_station = OscarSurfaceStationLocal.objects.filter(wigos_id=wigos_id).first()

                if existing_station:
                    for attr, value in new_local_copy_station.items():
                        setattr(existing_station, attr, value)
                    existing_station.save()
                else:
                    station = OscarSurfaceStationLocal.objects.create(**new_local_copy_station)

            messages.success(request, _("Stations loaded successfully."))

            loader_url = reverse("load_stations_oscar") + '?use_local=1'

            return redirect(loader_url)
        else:
            context.update({"form": form})
            return render(request, template_name, context)
    else:
        from .wagtail_hooks import StationViewSet
        stations_url = StationViewSet().menu_url

        breadcrumbs_items = [
            {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
            {"url": reverse_lazy("wagtailsnippets:index"), "label": _("Snippets")},
            {"url": stations_url, "label": _("Stations")},
            {"url": "", "label": _("Load Stations from CSV")},
        ]

        context.update({
            "breadcrumbs_items": breadcrumbs_items,
            "header_icon": "icon-snippet",
        })

        if not overwrite:
            exists = OscarSurfaceStationLocal.objects.exists()
            if exists:
                context.update({
                    "loader_url": reverse("load_stations_oscar") + '?use_local=1',
                    "found_existing_local": True,
                    "overwrite_url": reverse("load_stations_oscar_csv") + '?overwrite=1'
                })

        form = StationLoaderForm()
        context["form"] = form

        station_fields = []

        for station_col in OSCAR_SURFACE_REQUIRED_CSV_COLUMNS:
            station_fields.append({
                "name": station_col.get("name"),
                "type": station_col.get("type"),
                "required": True,
            })

        context["station_fields_json"] = json.dumps(station_fields)

        context["stations_csv_template_url"] = reverse_lazy("download_stations_csv_template")

    return render(request, template_name=template_name, context=context)


def download_stations_csv_template(request):
    template_name = "wis2box_adl/stations_csv_template.html"

    context = {}

    if request.POST:
        form = StationsCSVTemplateDownloadForm(request.POST)

        if form.is_valid():
            network = form.cleaned_data["network"]
            filename = f"{network.name}_stations_csv_template.csv"

            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'

            col_headers = []
            for name, value in STATION_ATTRIBUTES.items():
                col_headers.append(name)

            writer = csv.writer(response)
            writer.writerow(col_headers)

            return response
        else:
            context.update({"form": form})
    else:
        from .wagtail_hooks import StationViewSet
        station_attributes = STATION_ATTRIBUTES
        stations_url = StationViewSet().menu_url

        breadcrumbs_items = [
            {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
            {"url": reverse_lazy("wagtailsnippets:index"), "label": _("Snippets")},
            {"url": stations_url, "label": _("Stations")},
            {"url": "", "label": _("Stations CSV Template")},
        ]

        form = StationsCSVTemplateDownloadForm()
        context.update({
            "breadcrumbs_items": breadcrumbs_items,
            "form": form,
            "station_attributes": station_attributes
        })

    return render(request, template_name=template_name, context=context)


def load_stations_oscar(request):
    template_name = "wis2box_adl/load_stations_oscar.html"
    context = {}

    use_local_copy = request.GET.get("use_local", '').lower()
    use_local_copy = use_local_copy in ['1', 'true']

    from .wagtail_hooks import StationViewSet
    stations_url = StationViewSet().menu_url
    station_edit_url_name = StationViewSet().get_url_name("edit")

    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("wagtailsnippets:index"), "label": _("Snippets")},
        {"url": stations_url, "label": _("Stations")},
        {"url": "", "label": _("Load Stations from OSCAR Surface")},
    ]

    context.update({
        "breadcrumbs_items": breadcrumbs_items,
        "using_local_copy": use_local_copy
    })

    settings = AdlSettings.for_request(request)
    if not settings.country:
        context.update({
            "country_set": False,
            "settings_url": reverse(
                "wagtailsettings:edit",
                args=[AdlSettings._meta.app_label, AdlSettings._meta.model_name, ],
            )
        })

        return render(request, template_name=template_name, context=context)

    country = settings.country
    iso = country.alpha3

    db_stations = Station.objects.all()
    db_stations_by_wigos_id = {}
    for station in db_stations:
        db_stations_by_wigos_id[station.wigos_id] = station

    if use_local_copy:
        oscar_stations = get_stations_for_country_local()
    else:
        oscar_stations = cache.get(f"{iso}_oscar_stations")
        if not oscar_stations:
            try:
                oscar_stations = get_stations_for_country_live(country)
                # cache for 20 minutes
                cache.set(f"{iso}_oscar_stations", oscar_stations, timeout=60 * 20)
            except Exception as e:
                oscar_stations = []
                context.update({
                    "error_getting_stations": True,
                    "error": str(e),
                })

    context.update({
        "load_live_from_oscar_url": reverse("load_stations_oscar"),
        "load_from_csv_url": reverse("load_stations_oscar_csv")
    })

    for station in oscar_stations:
        import_url = reverse("import_oscar_station", args=[station.get("wigos_id")])

        if use_local_copy:
            import_url = import_url + "?use_local=1"

        station.update({
            "import_url": import_url
        })
        db_station = db_stations_by_wigos_id.get(station.get("wigos_id"))
        if db_station:
            station.update({
                "added_to_db": True,
                "db_station": db_station,
                "edit_url": reverse(station_edit_url_name, args=[db_station.pk])
            })

    # sort by added_to_db first then alphabetically
    oscar_stations = sorted(oscar_stations, key=lambda x: (x.get("added_to_db", False)), reverse=True)

    context["oscar_stations"] = oscar_stations
    context["country"] = country

    return render(request, template_name=template_name, context=context)


def import_oscar_station(request, wigos_id):
    from .wagtail_hooks import StationViewSet

    use_local_copy = request.GET.get("use_local", '').lower()
    use_local_copy = use_local_copy in ['1', 'true']

    stations_url = StationViewSet().menu_url

    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("wagtailsnippets:index"), "label": _("Snippets")},
        {"url": stations_url, "label": _("Stations")},
        {"url": reverse_lazy("load_stations_oscar"), "label": _("OSCAR Stations")},
        {"url": "", "label": _("Import OSCAR Station")},
    ]

    template_name = "wis2box_adl/import_oscar_surface_station.html"
    context = {
        "breadcrumbs_items": breadcrumbs_items,
    }

    settings = AdlSettings.for_request(request)
    country = settings.country

    if not country:
        messages.warning(request, _("Please set the country in the settings."))
        return redirect(reverse("load_stations_oscar"))

    if request.POST:
        form = OSCARStationImportForm(request.POST)

        if form.is_valid():
            network = form.cleaned_data["network"]
            station_type = form.cleaned_data["station_type"]
            station_data = form.cleaned_data["oscar_data"]
            wmo_block_number = form.cleaned_data.get("wmo_block_number")
            wmo_station_number = form.cleaned_data.get("wmo_station_number")
            station_data = json.loads(station_data)

            wigos_id = station_data.get("wigos_id")
            wigos_id_parts = get_wigos_id_parts(wigos_id)

            if wmo_block_number:
                wigos_id_parts["wmo_block_number"] = wmo_block_number

            if wmo_station_number:
                wigos_id_parts["wmo_station_number"] = wmo_station_number

            longitude = station_data.get("longitude")
            latitude = station_data.get("latitude")
            location = Point(x=longitude, y=latitude)

            new_station_data = {
                "station_id": wigos_id,
                "name": station_data.get("name"),
                "network": network,
                "station_type": station_type,
                "location": location,
                **wigos_id_parts,
            }

            elevation = station_data.get("elevation")
            if elevation:
                new_station_data["station_height_above_msl"] = elevation

            Station.objects.create(**new_station_data)

            messages.success(request, _("Station imported successfully."))
            return redirect(reverse("load_stations_oscar"))

        else:
            context.update({"form": form})
            return render(request, template_name=template_name, context=context)
    else:

        if use_local_copy:
            oscar_stations = get_stations_for_country_local(as_dict=True)
        else:
            iso = country.alpha3

            oscar_stations = cache.get(f"{iso}_oscar_stations_dict")
            if not oscar_stations:
                oscar_stations = get_stations_for_country_live(country, as_dict=True)
                # cache for 20 minutes
                cache.set(f"{iso}_oscar_stations_dict", oscar_stations, timeout=60 * 20)

        station = oscar_stations.get(wigos_id)

        if not station:
            context.update({
                "oscar_error": _("Station not found in OSCAR database.")
            })
            return render(request, template_name=template_name, context=context)

        initial_data = {
            "oscar_data": json.dumps(station),
            "station_id": wigos_id,
        }

        wigos_id_parts = get_wigos_id_parts(wigos_id)
        wsi_issuer = wigos_id_parts.get("wsi_issuer")

        # try to extract wmo_block_number and wmo_station_number from wsi_local for traditional WMO wsi format
        if str(wsi_issuer) == "20000":
            wsi_local = wigos_id_parts.get("wsi_local")
            wmo_block_number = wsi_local[:2]
            wmo_station_number = wsi_local[2:]

            try:
                # check if station number is a number
                int(wmo_block_number)
            except ValueError:
                digits = extract_digits(wmo_block_number)
                if digits:
                    wmo_block_number = digits
                else:
                    wmo_block_number = None

            try:
                # check if station number is a number
                int(wmo_station_number)
            except ValueError:
                digits = extract_digits(wmo_station_number)
                if digits:
                    wmo_station_number = digits
                else:
                    wmo_station_number = None

            if wmo_block_number:
                initial_data["wmo_block_number"] = wmo_block_number

            if wmo_station_number:
                initial_data["wmo_station_number"] = wmo_station_number

        form = OSCARStationImportForm(initial=initial_data)

        context.update({
            "form": form,
            "station": station
        })

    return render(request, template_name=template_name, context=context)


def plugin_events_data(request):
    events = PluginExecutionEvent.objects.filter(finished_at__isnull=False)

    later_than = request.GET.get("later_than")

    if later_than:
        events = events.filter(finished_at__gt=later_than)

    serializer = PluginExecutionEventSerializer(events, many=True)

    return JsonResponse(serializer.data, safe=False)
