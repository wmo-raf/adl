import json
import math
from collections import defaultdict

import requests
from django.contrib.gis.geos import Point
from django.shortcuts import render, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext as _
from wagtail.admin import messages

from adl.core.forms import OSCARStationImportForm
from adl.core.models import AdlSettings, Station
from adl.core.utils import get_wigos_id_parts, extract_digits

from .export import ELIGIBLE, build_wis2box_station_csv, plan_wis2box_export
from .models import Wis2BoxSettings
from .utils import get_wis2box_stations_cached, get_oscar_station_records, get_wis2box_topics


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
        "export_url":         reverse("export_wis2box_stations"),
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


# ─────────────────────────────────────────────────────────────────────────────
# export_wis2box_stations
# ─────────────────────────────────────────────────────────────────────────────

def _export_rows(plan):
    """Template rows for the export table, initialised for a fresh GET."""
    rows = []
    for planned in plan:
        station = planned.station
        eligible = planned.status == ELIGIBLE
        barometer = station.barometer_height_above_msl
        rows.append({
            "wigos_id":   station.station_id,
            "name":       planned.values["station_name"] if eligible else station.name,
            "network":    station.network.name,
            "eligible":   eligible,
            "status":     planned.status,
            "reason":     planned.reason,
            "elevation":  planned.values.get("elevation"),
            "barometer":  "" if barometer is None else barometer,
            "selected":   eligible,
            "error":      "",
        })
    return rows


def _parse_barometer_height(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _apply_export_post(rows, post):
    """
    Carry the submitted selection and barometer heights into ``rows`` and
    validate them. Returns ``(barometer_heights, valid)``: the heights keyed
    by WIGOS id for the selected rows, and whether every one was valid (an
    invalid row has its ``error`` set).
    """
    selected_ids = set(post.getlist("selected"))
    barometer_heights = {}
    valid = True

    for row in rows:
        raw = post.get(f"barometer_height__{row['wigos_id']}", "").strip()
        row["barometer"] = raw
        row["selected"] = row["eligible"] and row["wigos_id"] in selected_ids

        if not row["selected"]:
            continue

        value = _parse_barometer_height(raw)
        if value is None:
            row["error"] = _("Barometer height is required") if not raw else _("Barometer height must be a number")
            valid = False
            continue

        barometer_heights[row["wigos_id"]] = value

    return barometer_heights, valid


def export_wis2box_stations(request):
    """
    Build a station list CSV for ``wis2box metadata station publish-collection``
    from the ADL stations not yet on wis2box, with OSCAR as the source of
    every value except the WIGOS id and the barometer height.
    """
    template_name = "wis2box/export_wis2box_stations.html"

    context = {
        "breadcrumbs_items": _breadcrumbs({"url": None, "label": _("Export for wis2box bulk insert")}),
        "header_title": _("Export for wis2box bulk insert"),
        "header_icon": "download",
        "retry_url": request.path,
    }

    wis2box_settings = Wis2BoxSettings.for_request(request)
    if not wis2box_settings.wis2box_url:
        messages.warning(request, _("Please configure the wis2box URL in settings."))
        return redirect(reverse("wis2box_stations"))

    country = AdlSettings.for_request(request).country
    if not country:
        context["blocked_error"] = _("Set the country in ADL Settings before exporting stations for wis2box.")
        return render(request, template_name, context)

    base_url = wis2box_settings.wis2box_url

    # A stale or empty wis2box list would make stations already on wis2box look
    # ADL-only, and publishing them would overwrite their metadata — so both
    # opening the page and generating re-fetch, and any failure blocks the export
    wis2box_stations_list, fetch_error = get_wis2box_stations_cached(base_url, refresh=True)
    if fetch_error:
        context["blocked_error"] = _("Could not fetch stations from wis2box: %(error)s") % {"error": fetch_error}
        return render(request, template_name, context)

    try:
        oscar_records = get_oscar_station_records(country)
    except Exception as exc:
        context["blocked_error"] = _("Could not fetch stations from OSCAR: %(error)s") % {"error": exc}
        return render(request, template_name, context)

    plan = plan_wis2box_export(
        Station.objects.select_related("network").order_by("name"),
        {s["wigos_id"] for s in wis2box_stations_list},
        oscar_records,
    )
    rows = _export_rows(plan)

    try:
        topics, topics_error = get_wis2box_topics(base_url), None
    except (requests.RequestException, ValueError) as exc:
        topics, topics_error = [], str(exc)

    can_save_barometer = request.user.has_perm("core.change_station")

    if request.method == "POST":
        topic = request.POST.get("topic", "").strip()
        save_barometer = can_save_barometer and bool(request.POST.get("save_barometer_heights"))
        barometer_heights, barometer_valid = _apply_export_post(rows, request.POST)
        eligible_ids = {r["wigos_id"] for r in rows if r["eligible"]}
        unexportable = set(request.POST.getlist("selected")) - eligible_ids

        if unexportable:
            # OSCAR or wis2box changed between opening the page and generating
            context["form_error"] = _(
                "%(count)s selected station(s) are no longer exportable: %(ids)s. Review the list and generate again."
            ) % {"count": len(unexportable), "ids": ", ".join(sorted(unexportable))}
        elif not barometer_valid:
            context["form_error"] = _("Fix the highlighted stations before generating the CSV.")
        elif not barometer_heights:
            context["form_error"] = _("Select at least one station to export.")
        elif not topic or (topics and topic not in topics):
            context["form_error"] = _("Choose the wis2box topic the stations publish to.")
        else:
            selected_plan = [p for p in plan if p.station.station_id in barometer_heights]

            if save_barometer:
                for planned in selected_plan:
                    planned.station.barometer_height_above_msl = barometer_heights[planned.station.station_id]
                    planned.station.save(update_fields=["barometer_height_above_msl"])

            csv_filename = f"adl_wis2box_stations_{country.alpha3}_{dj_timezone.localdate():%Y%m%d}.csv"
            context.update({
                "csv_text":     build_wis2box_station_csv(selected_plan, barometer_heights),
                "csv_filename": csv_filename,
                "csv_count":    len(selected_plan),
                "barometer_saved": save_barometer,
            })

        context["topic"] = topic
        context["save_barometer"] = save_barometer
    else:
        context["topic"] = topics[0] if len(topics) == 1 else ""
        context["save_barometer"] = can_save_barometer

    context.update({
        "rows":           rows,
        "total_eligible": sum(1 for r in rows if r["eligible"]),
        "total_excluded": sum(1 for r in rows if not r["eligible"]),
        "country":        country,
        "topics":         topics,
        "topics_error":   topics_error,
        "can_save_barometer": can_save_barometer,
        "ground_clearance":   wis2box_settings.barometer_ground_clearance,
        "settings_url":       _settings_url(),
    })

    return render(request, template_name, context)
