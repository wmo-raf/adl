import json
from collections import defaultdict

from django.contrib.gis.geos import Point
from django.shortcuts import render, redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from wagtail.admin import messages

from adl.core.forms import OSCARStationImportForm
from adl.core.models import Station
from adl.core.utils import get_wigos_id_parts, extract_digits

from .models import Wis2BoxSettings
from .utils import get_wis2box_stations_cached


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _derive_wigos_id_parts(wigos_id: str) -> dict:
    """
    Cast wsi_series / wsi_issuer / wsi_issue_number to int (PositiveIntegerField).
    Auto-derive wmo_block_number (int) and wmo_station_number (str) for
    traditional WMO stations (wsi_issuer == 20000).
    """
    parts = get_wigos_id_parts(wigos_id)

    for int_field in ("wsi_series", "wsi_issuer", "wsi_issue_number"):
        raw = parts.get(int_field)
        if raw is not None:
            try:
                parts[int_field] = int(raw)
            except (ValueError, TypeError):
                pass

    wsi_issuer = parts.get("wsi_issuer")

    if wsi_issuer == 20000:
        wsi_local   = parts.get("wsi_local", "")
        raw_block   = wsi_local[:2]
        raw_station = wsi_local[2:]

        def _to_int(raw):
            try:
                return int(raw)
            except (ValueError, TypeError):
                digits = extract_digits(raw)
                return int(digits) if digits else None

        def _to_str(raw):
            try:
                int(raw)
                return raw
            except (ValueError, TypeError):
                return extract_digits(raw) or None

        block  = _to_int(raw_block)
        number = _to_str(raw_station)

        if block is not None:
            parts["wmo_block_number"] = block
        if number is not None:
            parts["wmo_station_number"] = number

    return parts


def _breadcrumbs(extra=None):
    crumbs = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("wis2box_stations"),  "label": _("Wis2Box Stations")},
    ]
    if extra:
        crumbs.append(extra)
    return crumbs


def _settings_url():
    return reverse(
        "wagtailsettings:edit",
        args=[Wis2BoxSettings._meta.app_label, Wis2BoxSettings._meta.model_name],
    )


# ─────────────────────────────────────────────────────────────────────────────
# wis2box_stations
# ─────────────────────────────────────────────────────────────────────────────

def wis2box_stations(request):
    template_name = "wis2box/wis2box_stations.html"

    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": "", "label": _("Wis2Box Stations")},
    ]

    context = {
        "breadcrumbs_items": breadcrumbs_items,
    }

    # ── Guard: wis2box URL must be configured ───────────────────────────────
    settings = Wis2BoxSettings.for_request(request)
    if not settings.wis2box_url:
        context["wis2box_url_not_set"] = True
        context["settings_url"] = _settings_url()
        return render(request, template_name, context)

    base_url = settings.wis2box_url
    refresh  = request.GET.get("refresh", "").lower() in ("1", "true")

    # ── Fetch wis2box stations ───────────────────────────────────────────────
    wis2box_stations_list, fetch_error = get_wis2box_stations_cached(base_url, refresh=refresh)

    if fetch_error:
        # Surface the error but still show whatever is in cache (may be empty)
        messages.error(
            request,
            _("Could not fetch stations from wis2box: %(error)s") % {"error": fetch_error},
        )

    wis2box_by_wigos = {s["wigos_id"]: s for s in wis2box_stations_list}

    # ── Load ADL stations ────────────────────────────────────────────────────
    adl_stations     = Station.objects.select_related("network").all()
    adl_by_wigos     = {s.station_id: s for s in adl_stations}

    wis2box_wigos_ids = set(wis2box_by_wigos.keys())
    adl_wigos_ids     = set(adl_by_wigos.keys())

    # ── Three-way join ───────────────────────────────────────────────────────
    matched_ids     = wis2box_wigos_ids & adl_wigos_ids
    adl_only_ids    = adl_wigos_ids - wis2box_wigos_ids
    wis2box_only_ids = wis2box_wigos_ids - adl_wigos_ids

    matched = sorted(
        [
            {
                "wigos_id":   wid,
                "adl":        adl_by_wigos[wid],
                "wis2box":    wis2box_by_wigos[wid],
            }
            for wid in matched_ids
        ],
        key=lambda x: (x["adl"].network.name, x["adl"].name),
    )

    adl_only = sorted(
        [
            {
                "wigos_id": wid,
                "adl":      adl_by_wigos[wid],
            }
            for wid in adl_only_ids
        ],
        key=lambda x: x["adl"].name,
    )

    wis2box_only = sorted(
        [
            {
                "wigos_id":   wid,
                "wis2box":    wis2box_by_wigos[wid],
                "import_url": reverse("import_wis2box_station", args=[wid]),
            }
            for wid in wis2box_only_ids
        ],
        key=lambda x: x["wis2box"].get("name") or x["wigos_id"],
    )

    # ── Stats ────────────────────────────────────────────────────────────────
    imported_by_network = defaultdict(int)
    for row in matched:
        imported_by_network[row["adl"].network.name] += 1
    imported_by_network = sorted(imported_by_network.items(), key=lambda x: x[1], reverse=True)

    context.update({
        "wis2box_url":        base_url,
        "refresh_url":        reverse("wis2box_stations") + "?refresh=1",
        "matched":            matched,
        "adl_only":           adl_only,
        "wis2box_only":       wis2box_only,
        "total_wis2box":      len(wis2box_wigos_ids),
        "total_adl":          len(adl_wigos_ids),
        "total_matched":      len(matched_ids),
        "total_adl_only":     len(adl_only_ids),
        "total_wis2box_only": len(wis2box_only_ids),
        "imported_by_network": imported_by_network,
        "fetch_error":        fetch_error,
    })

    return render(request, template_name, context)


# ─────────────────────────────────────────────────────────────────────────────
# import_wis2box_station
# ─────────────────────────────────────────────────────────────────────────────

def import_wis2box_station(request, wigos_id):
    template_name = "wis2box/import_wis2box_station.html"

    breadcrumbs_items = _breadcrumbs({"url": "", "label": _("Import Wis2Box Station")})

    context = {
        "breadcrumbs_items": breadcrumbs_items,
    }

    settings = Wis2BoxSettings.for_request(request)
    if not settings.wis2box_url:
        messages.warning(request, _("Please configure the wis2box URL in settings."))
        return redirect(reverse("wis2box_stations"))

    base_url = settings.wis2box_url

    # ── Guard: already imported ──────────────────────────────────────────────
    if Station.objects.filter(station_id=wigos_id).exists():
        messages.info(
            request,
            _("Station %(wigos_id)s is already in the database.") % {"wigos_id": wigos_id},
        )
        return redirect(reverse("wis2box_stations"))

    # ── Fetch station data from cache/live ───────────────────────────────────
    wis2box_dict, fetch_error = get_wis2box_stations_cached(base_url, as_dict=True)

    if fetch_error and not wis2box_dict:
        messages.error(
            request,
            _("Could not fetch stations from wis2box: %(error)s") % {"error": fetch_error},
        )
        return redirect(reverse("wis2box_stations"))

    station_data = wis2box_dict.get(wigos_id)
    if not station_data:
        context["wis2box_error"] = _("Station not found in wis2box.")
        return render(request, template_name, context)

    # ── POST: create the station ─────────────────────────────────────────────
    if request.method == "POST":
        form = OSCARStationImportForm(request.POST)

        if form.is_valid():
            network      = form.cleaned_data["network"]
            station_type = form.cleaned_data["station_type"]
            wmo_block_number   = form.cleaned_data.get("wmo_block_number")
            wmo_station_number = form.cleaned_data.get("wmo_station_number")

            longitude = station_data.get("longitude")
            latitude  = station_data.get("latitude")
            location  = Point(x=longitude, y=latitude)

            wigos_id_parts = _derive_wigos_id_parts(wigos_id)

            if wmo_block_number:
                wigos_id_parts["wmo_block_number"] = int(wmo_block_number)
            if wmo_station_number:
                wigos_id_parts["wmo_station_number"] = wmo_station_number

            new_station = {
                "station_id":   wigos_id,
                "name":         station_data.get("name"),
                "network":      network,
                "station_type": station_type,
                "location":     location,
                **wigos_id_parts,
            }

            elevation = station_data.get("elevation")
            if elevation is not None:
                new_station["station_height_above_msl"] = elevation

            Station.objects.create(**new_station)

            messages.success(request, _("Station imported successfully."))
            return redirect(reverse("wis2box_stations"))

        context["form"] = form
        context["station"] = station_data
        return render(request, template_name, context)

    # ── GET: pre-fill form from wis2box data ─────────────────────────────────
    initial = {
        "oscar_data": json.dumps(station_data),
        "station_id": wigos_id,
    }

    wigos_id_parts = _derive_wigos_id_parts(wigos_id)

    if wigos_id_parts.get("wsi_issuer") == 20000:
        if wigos_id_parts.get("wmo_block_number") is not None:
            initial["wmo_block_number"] = wigos_id_parts["wmo_block_number"]
        if wigos_id_parts.get("wmo_station_number"):
            initial["wmo_station_number"] = wigos_id_parts["wmo_station_number"]

    form = OSCARStationImportForm(initial=initial)

    context.update({
        "form":    form,
        "station": station_data,
    })

    return render(request, template_name, context)
