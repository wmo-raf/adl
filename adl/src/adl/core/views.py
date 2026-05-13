import json
from collections import defaultdict

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.paginator import Paginator, InvalidPage
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import (
    require_http_methods,
    require_POST
)
from wagtail.admin import messages
from wagtail.admin.paginator import WagtailPaginator
from wagtail.admin.ui.tables import (
    Table,
    TitleColumn,
    BooleanColumn,
    ButtonsColumnMixin
)
from wagtail.admin.widgets import (
    HeaderButton,
    ListingButton,
    ButtonWithDropdown
)

from .constants import (
    OSCAR_SURFACE_REQUIRED_CSV_COLUMNS,
    PREDEFINED_DATA_PARAMETERS
)
from .forms import (
    StationLoaderForm,
    OSCARStationImportForm,
    CreatePredefinedDataParametersForm,
    StationIncludeForm
)
from .models import (
    Station,
    AdlSettings,
    OscarSurfaceStationLocal,
    NetworkConnection,
    DispatchChannel,
    DataParameter,
    Unit,
    DispatchChannelStationLink,
    StationLink, Network
)
from .plugin_utils import get_plugin_metadata
from .registries import (
    dispatch_channel_viewset_registry,
    connection_viewset_registry,
    plugin_registry
)
from .table import LinkColumnWithIcon
from .tasks import process_station_link_batch, perform_channel_dispatch
from .utils import (
    get_stations_for_country_live,
    get_stations_for_country_local,
    get_wigos_id_parts,
    extract_digits,
    get_all_child_models,
    get_child_model_by_name,
    get_connection_station_link_url,
    get_connection_list_more_buttons,
    get_dispatch_channel_more_buttons
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper — shared between import_oscar_station and bulk import
# ─────────────────────────────────────────────────────────────────────────────

def _derive_wigos_id_parts(wigos_id: str) -> dict:
    """
    Extract wsi_* parts and, for traditional WMO stations (wsi_issuer==20000),
    auto-derive wmo_block_number and wmo_station_number from wsi_local.
 
    wsi_series / wsi_issuer / wsi_issue_number are PositiveIntegerFields on
    Station — cast them to int here so Station.objects.create() never receives
    strings for those columns.
    wmo_block_number is also a PositiveIntegerField — cast to int.
    wmo_station_number is a CharField — keep as string.
    """
    wigos_id_parts = get_wigos_id_parts(wigos_id)
    
    # Cast the three integer WSI components
    for int_field in ("wsi_series", "wsi_issuer", "wsi_issue_number"):
        raw = wigos_id_parts.get(int_field)
        if raw is not None:
            try:
                wigos_id_parts[int_field] = int(raw)
            except (ValueError, TypeError):
                pass  # leave as-is; DB will raise a clear error
    
    wsi_issuer = wigos_id_parts.get("wsi_issuer")
    
    if wsi_issuer == 20000:
        wsi_local = wigos_id_parts.get("wsi_local", "")
        raw_block = wsi_local[:2]
        raw_station = wsi_local[2:]
        
        def _coerce_block(raw):
            try:
                return int(raw)  # wmo_block_number is PositiveIntegerField
            except (ValueError, TypeError):
                digits = extract_digits(raw)
                return int(digits) if digits else None
        
        def _coerce_station(raw):
            try:
                int(raw)  # validate it is numeric
                return raw  # wmo_station_number is CharField
            except (ValueError, TypeError):
                return extract_digits(raw) or None
        
        block = _coerce_block(raw_block)
        number = _coerce_station(raw_station)
        
        if block is not None:
            wigos_id_parts["wmo_block_number"] = block
        if number is not None:
            wigos_id_parts["wmo_station_number"] = number
    
    return wigos_id_parts


def _get_oscar_stations_dict(use_local_copy: bool, country) -> tuple[dict, str | None]:
    """
    Returns (stations_dict_keyed_by_wigos_id, error_string_or_None).
    Handles both local and live paths with caching.
    """
    if use_local_copy:
        return get_stations_for_country_local(as_dict=True), None
    
    iso = country.alpha3
    cache_key = f"{iso}_oscar_stations_dict"
    stations = cache.get(cache_key)
    
    if not stations:
        try:
            stations = get_stations_for_country_live(country, as_dict=True)
            cache.set(cache_key, stations, timeout=60 * 20)
        except Exception as e:
            return {}, str(e)
    
    return stations, None


def load_stations_csv(request):
    from .viewsets import StationViewSet
    stations_url = StationViewSet().menu_url
    
    template_name = "adl/load_stations_csv.html"
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


def load_stations_oscar(request):
    template_name = "adl/load_stations_oscar.html"
    context = {}
    
    use_local_copy = request.GET.get("use_local", '').lower() in ('1', 'true')
    
    from .viewsets import StationViewSet
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
        "using_local_copy": use_local_copy,
    })
    
    settings = AdlSettings.for_request(request)
    if not settings.country:
        context.update({
            "country_set": False,
            "settings_url": reverse(
                "wagtailsettings:edit",
                args=[AdlSettings._meta.app_label, AdlSettings._meta.model_name],
            )
        })
        return render(request, template_name=template_name, context=context)
    
    country = settings.country
    iso = country.alpha3
    
    # ── Fetch station list ──────────────────────────────────────────────────
    if use_local_copy:
        # .values() returns dicts — convert to list so we can mutate entries below
        oscar_stations = list(get_stations_for_country_local())
    else:
        oscar_stations = cache.get(f"{iso}_oscar_stations")
        if not oscar_stations:
            try:
                oscar_stations = get_stations_for_country_live(country)
                cache.set(f"{iso}_oscar_stations", oscar_stations, timeout=60 * 20)
            except Exception as e:
                oscar_stations = []
                context.update({
                    "error_getting_stations": True,
                    "error": str(e),
                })
    
    context.update({
        "load_live_from_oscar_url": reverse("load_stations_oscar"),
        "load_from_csv_url": reverse("load_stations_oscar_csv"),
    })
    
    # ── Annotate with DB status ─────────────────────────────────────────────
    db_stations_by_wigos_id = {s.station_id: s for s in Station.objects.all()}
    
    for station in oscar_stations:
        wigos_id = station.get("wigos_id")
        import_url = reverse("import_oscar_station", args=[wigos_id])
        if use_local_copy:
            import_url += "?use_local=1"
        station["import_url"] = import_url
        
        db_station = db_stations_by_wigos_id.get(wigos_id)
        if db_station:
            station.update({
                "added_to_db": True,
                "db_station": db_station,
                "edit_url": reverse(station_edit_url_name, args=[db_station.pk]),
            })
    
    # Sort: already-added first, then alphabetically by name within each group
    oscar_stations = sorted(
        oscar_stations,
        key=lambda x: (not x.get("added_to_db", False), (x.get("name") or "").lower()),
    )
    
    # ── Stats bar ───────────────────────────────────────────────────────────
    total_oscar = len(oscar_stations)
    total_imported = sum(1 for s in oscar_stations if s.get("added_to_db"))
    
    # Count imported stations grouped by their assigned network name
    imported_by_network = defaultdict(int)
    for s in oscar_stations:
        if s.get("added_to_db"):
            network_name = s["db_station"].network.name
            imported_by_network[network_name] += 1
    # Sort by count descending so the busiest network appears first
    imported_by_network = sorted(imported_by_network.items(), key=lambda x: x[1], reverse=True)
    
    # ── Bulk import context ─────────────────────────────────────────────────
    # Reuse OSCARStationImportForm field definitions so choices stay in sync.
    # We only need an unbound form to read field choices from.
    _import_form = OSCARStationImportForm()
    networks = _import_form.fields["network"].queryset
    station_type_choices = _import_form.fields["station_type"].choices
    
    context.update({
        "oscar_stations": oscar_stations,
        "country": country,
        "networks": networks,
        "station_type_choices": station_type_choices,
        "total_oscar": total_oscar,
        "total_imported": total_imported,
        "total_pending": total_oscar - total_imported,
        "imported_by_network": imported_by_network,
    })
    
    return render(request, template_name=template_name, context=context)


def import_oscar_station(request, wigos_id):
    from .viewsets import StationViewSet
    
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
    
    template_name = "adl/import_oscar_surface_station.html"
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


@require_POST
def bulk_import_oscar_stations(request):
    """
    Handles the bulk import POST from the action bar in load_stations_oscar.html.
 
    Expected POST fields:
        selected_wigos_ids   – repeated field, one value per selected station
        network              – pk of the NetworkConnection to assign
        station_type         – station_type value (must match Station.station_type choices)
 
    Add to urls.py:
        path("oscar/bulk-import/", bulk_import_oscar_stations, name="bulk_import_oscar_stations"),
    """
    use_local_copy = request.GET.get("use_local", "").lower() in ("1", "true")
    redirect_url = reverse("load_stations_oscar")
    if use_local_copy:
        redirect_url += "?use_local=1"
    
    # ── Validate POST inputs ────────────────────────────────────────────────
    selected_wigos_ids = request.POST.getlist("selected_wigos_ids")
    network_pk = request.POST.get("network", "").strip()
    station_type_raw = request.POST.get("station_type", "").strip()
    
    if not selected_wigos_ids:
        messages.warning(request, _("No stations were selected for import."))
        return redirect(redirect_url)
    
    # station_type "0" is falsy — check for empty string explicitly
    if not network_pk or station_type_raw == "":
        messages.warning(request, _("Please select a network and station type before importing."))
        return redirect(redirect_url)
    
    # Coerce to int and validate directly against the form's STATION_TYPE_CHOICES
    valid_station_type_values = [v for v, _ in OSCARStationImportForm.STATION_TYPE_CHOICES]
    try:
        station_type = int(station_type_raw)
        if station_type not in valid_station_type_values:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, _("Invalid station type selected."))
        return redirect(redirect_url)
    
    try:
        network = Network.objects.get(pk=network_pk)
    except Network.DoesNotExist:
        messages.error(request, _("The selected network no longer exists."))
        return redirect(redirect_url)
    
    # ── Resolve country ─────────────────────────────────────────────────────
    adl_settings = AdlSettings.for_request(request)
    country = adl_settings.country
    if not country:
        messages.warning(request, _("Please set the country in the settings."))
        return redirect(redirect_url)
    
    # ── Fetch OSCAR data dict ───────────────────────────────────────────────
    oscar_stations_dict, fetch_error = _get_oscar_stations_dict(use_local_copy, country)
    if fetch_error:
        messages.error(
            request,
            _("Could not fetch OSCAR station data: %(error)s") % {"error": fetch_error},
        )
        return redirect(redirect_url)
    
    # ── Skip already-imported stations ──────────────────────────────────────
    already_imported = set(
        Station.objects.filter(station_id__in=selected_wigos_ids)
        .values_list("station_id", flat=True)
    )
    to_import = [w for w in selected_wigos_ids if w not in already_imported]
    
    if not to_import:
        messages.info(request, _("All selected stations are already in the database."))
        return redirect(redirect_url)
    
    # ── Import inside a single transaction ─────────────────────────────────
    imported_names = []
    not_found = []
    
    try:
        with transaction.atomic():
            for wigos_id in to_import:
                station_data = oscar_stations_dict.get(wigos_id)
                
                if not station_data:
                    not_found.append(wigos_id)
                    continue
                
                longitude = station_data.get("longitude")
                latitude = station_data.get("latitude")
                
                if longitude is None or latitude is None:
                    not_found.append(wigos_id)
                    continue
                
                location = Point(x=longitude, y=latitude)
                wigos_id_parts = _derive_wigos_id_parts(wigos_id)
                
                new_station_data = {
                    "station_id": wigos_id,
                    "name": station_data.get("name"),
                    "network": network,
                    "station_type": station_type,
                    "location": location,
                    **wigos_id_parts,
                }
                
                elevation = station_data.get("elevation")
                if elevation is not None:
                    new_station_data["station_height_above_msl"] = elevation
                
                Station.objects.create(**new_station_data)
                imported_names.append(station_data.get("name") or wigos_id)
    
    except Exception as e:
        messages.error(
            request,
            _("Import failed: %(error)s") % {"error": str(e)},
        )
        return redirect(redirect_url)
    
    # ── User feedback ───────────────────────────────────────────────────────
    if imported_names:
        messages.success(
            request,
            _("Successfully imported %(count)d station(s).") % {"count": len(imported_names)},
        )
    
    if already_imported:
        messages.info(
            request,
            _("%(count)d station(s) skipped — already in the database.")
            % {"count": len(already_imported)},
        )
    
    if not_found:
        messages.warning(
            request,
            _("%(count)d station(s) could not be found in OSCAR data and were skipped: %(ids)s")
            % {"count": len(not_found), "ids": ", ".join(not_found)},
        )
    
    return redirect(redirect_url)


def connections_list(request):
    connections = NetworkConnection.objects.all().order_by("name")
    
    # Group connections by plugin
    grouped_connections = defaultdict(list)
    for conn in connections:
        grouped_connections[conn.plugin].append(conn)
    
    def get_url(instance):
        return instance.edit_url
    
    # Prepare data for each plugin group
    data = []
    
    class ConnectionButtonsColumn(ButtonsColumnMixin, TitleColumn):
        def get_buttons(self, instance, parent_context):
            more_buttons = []
            buttons = []
            if edit_url := instance.edit_url:
                more_buttons.append(
                    ListingButton(
                        _("Edit"),
                        url=edit_url,
                        icon_name="edit",
                        attrs={
                            "aria-label": _("Edit '%(title)s'") % {"title": str(instance)}
                        },
                        priority=10,
                    )
                )
            
            if delete_url := instance.delete_url:
                more_buttons.append(
                    ListingButton(
                        _("Delete"),
                        url=delete_url,
                        icon_name="bin",
                        attrs={
                            "aria-label": _("Delete '%(title)s'") % {"title": str(instance)}
                        },
                        priority=30,
                    )
                )
            
            extra_buttons = get_connection_list_more_buttons(instance)
            if extra_buttons:
                more_buttons.extend(extra_buttons)
            
            if more_buttons:
                buttons.append(
                    ButtonWithDropdown(
                        buttons=more_buttons,
                        icon_name="dots-horizontal",
                        attrs={
                            "aria-label": _("More options for '%(title)s'")
                                          % {"title": str(instance)},
                        },
                    )
                )
            
            return buttons
    
    for plugin, conns in grouped_connections.items():
        plugin_obj = plugin_registry.get(plugin)
        
        columns = [
            ConnectionButtonsColumn("name", label=_("Station Link"), get_url=get_url),
            BooleanColumn("plugin_processing_enabled", label=_("Enabled")),
            LinkColumnWithIcon("stations_link", label=_("Stations Link"), icon_name="map-pin",
                               get_url=get_connection_station_link_url),
        ]
        
        data.append({
            "plugin": {"name": plugin_obj.label},
            "connections_table": Table(columns, conns),
        })
    
    context = {
        "breadcrumbs_items": [
            {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
            {"url": "", "label": _("Network Connections")},
        ],
        "header_buttons": [
            HeaderButton(
                label=_('Add Connection'),
                url=reverse("connections_add_select"),
                icon_name="plus",
            ),
        ],
        "plugin_connections": data,  # Optional: pass it to template if needed
    }
    
    return render(request, "core/connection_list.html", context)


def connection_add_select(request):
    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("connections_list"), "label": _("Network Connections")},
        {"url": "", "label": _("Select Connection Type")},
    ]
    
    connection_types = get_all_child_models(NetworkConnection)
    items = [{"name": cls.__name__, "verbose_name": cls._meta.verbose_name} for cls in connection_types]
    count = len(items)
    
    # Get search parameters from the query string.
    try:
        page_num = int(request.GET.get("p", 0))
    except ValueError:
        page_num = 0
    
    user = request.user
    paginator = Paginator(items, 20)
    
    try:
        page_obj = paginator.page(page_num + 1)
    except InvalidPage:
        page_obj = paginator.page(1)
    
    def get_url(instance):
        model_cls = get_child_model_by_name(NetworkConnection, instance["name"])
        model_name = model_cls._meta.model_name
        
        viewset = connection_viewset_registry.get(model_name)
        create_url = reverse(viewset.get_url_name("add"))
        return create_url
    
    columns = [
        TitleColumn("verbose_name", label=_("Name"), get_url=get_url),
    ]
    
    context = {
        "breadcrumbs_items": breadcrumbs_items,
        "all_count": count,
        "result_count": count,
        "paginator": paginator,
        "page_obj": page_obj,
        "object_list": page_obj.object_list,
        "table": Table(columns, page_obj.object_list),
    }
    
    return render(request, "core/connection_add_select.html", context)


def dispatch_channels_list(request):
    dispatch_channels = DispatchChannel.objects.all().order_by("name")
    
    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": "", "label": _("Dispatch Channels")},
    ]
    
    channel_types = get_all_child_models(DispatchChannel)
    
    data = {}
    
    def get_channel_edit_url(instance):
        return instance.edit_url
    
    def get_station_links_url(instance):
        url = reverse("dispatch_channel_station_links", args=[instance.id])
        return url
    
    dispatch_channels_by_model_name = {}
    for channel in dispatch_channels:
        model_name = channel.__class__._meta.model_name
        
        if not model_name in dispatch_channels_by_model_name:
            dispatch_channels_by_model_name[model_name] = []
        dispatch_channels_by_model_name[model_name].append(channel)
        
        class ChannelButtonsColumn(ButtonsColumnMixin, TitleColumn):
            def get_buttons(self, instance, parent_context):
                more_buttons = []
                buttons = []
                if edit_url := instance.edit_url:
                    more_buttons.append(
                        ListingButton(
                            _("Edit"),
                            url=edit_url,
                            icon_name="edit",
                            attrs={
                                "aria-label": _("Edit '%(title)s'") % {"title": str(instance)}
                            },
                            priority=10,
                        )
                    )
                
                if delete_url := instance.delete_url:
                    more_buttons.append(
                        ListingButton(
                            _("Delete"),
                            url=delete_url,
                            icon_name="bin",
                            attrs={
                                "aria-label": _("Delete '%(title)s'") % {"title": str(instance)}
                            },
                            priority=30,
                        )
                    )
                
                extra_buttons = get_dispatch_channel_more_buttons(instance)
                if extra_buttons:
                    more_buttons.extend(extra_buttons)
                
                if more_buttons:
                    buttons.append(
                        ButtonWithDropdown(
                            buttons=more_buttons,
                            icon_name="dots-horizontal",
                            attrs={
                                "aria-label": _("More options for '%(title)s'")
                                              % {"title": str(instance)},
                            },
                        )
                    )
                
                return buttons
    
    for channel_type in channel_types:
        model_name = channel_type._meta.model_name
        viewset = dispatch_channel_viewset_registry.get(model_name)
        index_url = reverse(viewset.get_url_name("index"))
        
        if not model_name in dispatch_channels_by_model_name:
            continue
        
        columns = [
            ChannelButtonsColumn("name", get_url=get_channel_edit_url),
            BooleanColumn("enabled"),
            LinkColumnWithIcon("stations_link", label=_("Stations Link"), icon_name="map-pin",
                               get_url=get_station_links_url),
        ]
        
        data[model_name] = {
            "name": channel_type._meta.verbose_name,
            "index_url": index_url,
            "channels_table": Table(columns, dispatch_channels_by_model_name[model_name]),
        }
    
    context = {
        "breadcrumbs_items": breadcrumbs_items,
        "header_buttons": [
            HeaderButton(
                label=_('Add Dispatch Channel'),
                url=reverse("dispatch_channel_add_select"),
                icon_name="plus",
            ),
        ],
        "dispatch_channels": data,
    }
    
    return render(request, "core/dispatch_channel_list.html", context)


def dispatch_channel_add_select(request):
    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("wagtailsnippets:index"), "label": _("Snippets")},
        {"url": reverse_lazy("dispatch_channels_list"), "label": _("Dispatch Channels")},
        {"url": "", "label": _("Select Dispatch Channel Type")},
    ]
    
    channel_types = get_all_child_models(DispatchChannel)
    
    items = [{"name": cls._meta.verbose_name} for cls in channel_types]
    count = len(items)
    
    # Get search parameters from the query string.
    try:
        page_num = int(request.GET.get("p", 0))
    except ValueError:
        page_num = 0
    
    user = request.user
    paginator = Paginator(items, 20)
    
    try:
        page_obj = paginator.page(page_num + 1)
    except InvalidPage:
        page_obj = paginator.page(1)
    
    def get_url(instance):
        model_cls = get_child_model_by_name(DispatchChannel, instance["name"])
        model_name = model_cls._meta.model_name
        
        viewset = dispatch_channel_viewset_registry.get(model_name)
        create_url = reverse(viewset.get_url_name("add"))
        return create_url
    
    columns = [
        TitleColumn("name", label=_("Name"), get_url=get_url),
    ]
    
    context = {
        "breadcrumbs_items": breadcrumbs_items,
        "all_count": count,
        "result_count": count,
        "paginator": paginator,
        "page_obj": page_obj,
        "object_list": page_obj.object_list,
        "table": Table(columns, page_obj.object_list),
    }
    
    return render(request, "core/dispatch_channel_add_select.html", context)


def get_plugin_list(request):
    """
    Returns a list of plugins with their labels and URLs.
    """
    plugins = plugin_registry.get_all()
    plugin_list = []
    
    for plugin in plugins:
        plugin_metadata = get_plugin_metadata(plugin)
        plugin_list.append({
            "label": plugin.label,
            "metadata": plugin_metadata
        })
    
    context = {
        "breadcrumbs_items": [
            {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
            {"url": "", "label": _("Plugins")},
        ],
        "plugins": plugin_list,
    }
    
    return render(request, "core/plugin_list.html", context)


def create_predefined_data_parameters(request):
    from .viewsets import DataParameterViewSet
    
    form = CreatePredefinedDataParametersForm()
    
    if request.method == "POST":
        form = CreatePredefinedDataParametersForm(request.POST)
        if form.is_valid():
            data_parameter_url_name = DataParameterViewSet().get_url_name("index")
            create_conversion_units = form.cleaned_data.get("create_conversion_units")
            
            try:
                with transaction.atomic():
                    for parameter in PREDEFINED_DATA_PARAMETERS:
                        unit = parameter.get("unit")
                        unit_symbol = unit.get("symbol")
                        conversion_context = parameter.get("conversion_context")
                        wis2box_aws_csv_template_unit = parameter.get("wis2box_aws_csv_template_unit")
                        
                        # get or create unit
                        unit, _created = Unit.objects.get_or_create(symbol=unit_symbol, defaults={
                            "name": unit.get("name"),
                            "symbol": unit_symbol,
                        })
                        
                        data_parameter_dict = {
                            "name": parameter.get("name"),
                            "unit": unit,
                        }
                        
                        if conversion_context:
                            data_parameter_dict.update({
                                "custom_unit_context": conversion_context,
                            })
                        
                        DataParameter.objects.create(**data_parameter_dict)
                        
                        if create_conversion_units and wis2box_aws_csv_template_unit:
                            unit_symbol = wis2box_aws_csv_template_unit.get("symbol")
                            unit_name = wis2box_aws_csv_template_unit.get("name")
                            
                            # get or create unit
                            Unit.objects.get_or_create(symbol=unit_symbol, defaults={
                                "name": unit_name,
                                "symbol": unit_symbol,
                            })
                
                messages.success(request, _("Predefined parameters created successfully."))
                return redirect(data_parameter_url_name)
            except Exception as e:
                form.add_error(None, e)
                messages.error(request, _("Error creating predefined parameters: ") + str(e))
    
    data_parameters_exist = DataParameter.objects.exists()
    
    context = {
        "page_title": _("Predefined Data Parameters"),
        "data_parameters_exist": data_parameters_exist,
        "predefined_data_parameters": PREDEFINED_DATA_PARAMETERS,
        "form": form,
    }
    
    return render(request, "core/create_predefined_data_parameters.html", context=context)


def dispatch_channel_station_links(request, channel_id):
    channel = get_object_or_404(DispatchChannel, pk=channel_id)
    
    breadcrumbs_items = [
        {"url": reverse_lazy("wagtailadmin_home"), "label": _("Home")},
        {"url": reverse_lazy("dispatch_channels_list"), "label": _("Dispatch Channels")},
        {"url": "", "label": channel.name},
    ]
    
    # Get station links from ALL network connections
    network_connections = channel.network_connections.all()
    
    if not network_connections.exists():
        messages.error(request, _("No network connections found for this dispatch channel."))
        return redirect("dispatch_channels_list")
    
    # Build queryset from all network connections
    network_connection_ids = list(network_connections.values_list('id', flat=True))
    all_station_links_qs = (
        StationLink.objects
        .filter(network_connection_id__in=network_connection_ids)
        .select_related("station", "network_connection")
        .order_by("network_connection__name", "station__name")
    )
    
    # Current exclusions across ALL pages (rows exist for excluded)
    existing_excluded_ids = set(
        DispatchChannelStationLink.objects
        .filter(dispatch_channel=channel)
        .values_list("station_link_id", flat=True)
    )
    
    # Pagination
    page_number = request.GET.get("p", 1)
    paginator = WagtailPaginator(all_station_links_qs, 50)  # 50 rows per page
    page_obj = paginator.get_page(page_number)
    page_ids = set(page_obj.object_list.values_list("id", flat=True))
    
    #  Group station links by network connection
    stations_by_connection = {}
    for station_link in page_obj.object_list:
        connection_name = station_link.network_connection.name
        connection_id = station_link.network_connection.id
        
        if connection_id not in stations_by_connection:
            stations_by_connection[connection_id] = {
                'connection': station_link.network_connection,
                'station_links': []
            }
        stations_by_connection[connection_id]['station_links'].append(station_link)
    
    if request.method == "POST":
        form = StationIncludeForm(
            request.POST,
            station_links_qs=page_obj.object_list,
            excluded_ids=existing_excluded_ids,
        )
        if form.is_valid():
            included_ids = set(map(int, form.cleaned_data.get("included_ids", [])))
            # Only compute diffs for the CURRENT PAGE
            new_excluded_ids_page = page_ids - included_ids
            
            to_create = new_excluded_ids_page - existing_excluded_ids
            to_delete = (existing_excluded_ids & page_ids) - new_excluded_ids_page
            
            with transaction.atomic():
                if to_create:
                    DispatchChannelStationLink.objects.bulk_create([
                        DispatchChannelStationLink(
                            dispatch_channel=channel,
                            station_link_id=sl_id,
                            disabled=True,
                        ) for sl_id in to_create
                    ], ignore_conflicts=True)
                
                if to_delete:
                    DispatchChannelStationLink.objects.filter(
                        dispatch_channel=channel,
                        station_link_id__in=to_delete
                    ).delete()
            
            if hasattr(channel, "after_update_station_links"):
                channel.after_update_station_links()
            
            messages.success(request, _("Saved changes for this page."))
            # Stay on the same page after save
            return redirect(f"{reverse('dispatch_channel_station_links', args=[channel.id])}?page={page_obj.number}")
    else:
        form = StationIncludeForm(
            station_links_qs=page_obj.object_list,
            excluded_ids=existing_excluded_ids,
        )
    
    elided_page_range = paginator.get_elided_page_range(page_number)
    
    context = {
        "breadcrumbs_items": breadcrumbs_items,
        "channel": channel,
        "form": form,
        "page_obj": page_obj,
        "paginator": paginator,
        "elided_page_range": elided_page_range,
        "page_title": _("Dispatch Channel Station Links"),
        "stations_by_connection": stations_by_connection,
        "network_connections": network_connections,
    }
    return render(request, "core/dispatch_channel_station_links.html", context=context)


@require_http_methods(["POST"])
def trigger_station_collection(request, station_link_id):
    """Manually trigger data collection for a station link"""
    if request.method == 'POST':
        station_link = get_object_or_404(StationLink, id=station_link_id)
        
        try:
            # Trigger the collection task
            process_station_link_batch.delay(station_link.network_connection.id, [station_link.id])
            
            messages.success(
                request,
                _('Data collection triggered for station link: %(station_link)s') % {'station_link': station_link}
            )
        except Exception as e:
            messages.error(
                request,
                _('Failed to trigger collection: %(error)s') % {'error': str(e)}
            )
        
        # Redirect back to the station link detail page
        return redirect(request.META.get('HTTP_REFERER', 'wagtailadmin_home'))
    
    return redirect('wagtailadmin_home')


def trigger_station_dispatch(request, station_link_id, channel_id):
    """Manually trigger data dispatch for a station link to a specific channel"""
    if request.method == 'POST':
        station_link = get_object_or_404(StationLink, id=station_link_id)
        dispatch_channel = get_object_or_404(DispatchChannel, id=channel_id)
        
        try:
            # Get data records for this station
            perform_channel_dispatch.delay(dispatch_channel.id, [station_link.id])
            
            messages.success(
                request,
                _('Dispatch triggered successfully for %(channel)s.') % {
                    'channel': dispatch_channel.name
                }
            )
        except Exception as e:
            messages.error(
                request,
                _('Failed to trigger dispatch: %(error)s') % {'error': str(e)}
            )
        
        # Redirect back to the station link detail page
        return redirect(request.META.get('HTTP_REFERER', 'wagtailadmin_home'))
    
    return redirect('wagtailadmin_home')
