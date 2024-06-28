import csv
import json

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from wagtail.admin import messages

from .forms import StationLoaderForm, StationsCSVTemplateDownloadForm, OSCARStationImportForm
from .constants import STATION_ATTRIBUTES
from .models import Station, AdlSettings
from .utils import get_stations_for_country, get_wigos_id_parts


def load_stations_csv(request):
    from .wagtail_hooks import StationViewSet
    stations_url = StationViewSet().menu_url

    template_name = "wis2box_adl/load_stations_csv.html"
    context = {}

    if request.POST:
        form = StationLoaderForm(request.POST, files=request.FILES)

        if form.is_valid():
            network = form.cleaned_data["network"]
            stations_data = form.cleaned_data["stations_data"]
            update_existing = form.cleaned_data["update_existing"]

            for data in stations_data:
                new_station = {
                    "network": network,
                    **data,
                }

                existing_station = Station.objects.filter(network=network, station_id=new_station["station_id"]).first()

                if existing_station:
                    if not update_existing:
                        form.add_error(None, f"Station with ID {new_station['station_id']} already "
                                             f"exists for network {network.name}. Check the 'update existing' option "
                                             f"if you wish update the existing record.")

                        context.update({"form": form})

                        return render(request, template_name=template_name, context=context)
                    else:
                        for attr, value in new_station.items():
                            setattr(existing_station, attr, value)

                        existing_station.save()
                else:
                    station = Station.objects.create(**new_station)

            messages.success(request, _("Stations loaded successfully."))

            return redirect(stations_url)
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

        form = StationLoaderForm()
        context["form"] = form

        station_fields = []

        for name, value in STATION_ATTRIBUTES.items():
            station_fields.append({
                "name": name,
                "type": value.get("type"),
                "required": value.get("required")
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

    oscar_stations = cache.get(f"{iso}_oscar_stations")
    if not oscar_stations:
        oscar_stations = get_stations_for_country(country)
        # cache for 20 minutes
        cache.set(f"{iso}_oscar_stations", oscar_stations, timeout=60 * 20)

    for station in oscar_stations:
        station.update({
            "import_url": reverse("import_oscar_station", args=[station.get("wigos_id")])
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
            station_data = json.loads(station_data)

            wigos_id = station_data.get("wigos_id")
            wigos_id_parts = get_wigos_id_parts(wigos_id)

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
        iso = country.alpha3

        oscar_stations = cache.get(f"{iso}_oscar_stations_dict")
        if not oscar_stations:
            oscar_stations = get_stations_for_country(country, as_dict=True)
            # cache for 20 minutes
            cache.set(f"{iso}_oscar_stations_dict", oscar_stations, timeout=60 * 20)

        station = oscar_stations.get(wigos_id)

        if not station:
            context.update({
                "oscar_error": _("Station not found in OSCAR database.")
            })
            return render(request, template_name=template_name, context=context)

        form = OSCARStationImportForm(initial={"oscar_data": json.dumps(station), "station_id": wigos_id})
        context.update({
            "form": form,
            "station": station
        })

    return render(request, template_name=template_name, context=context)
