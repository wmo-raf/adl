import calendar
import json
from datetime import datetime, timezone

from django.db.models import Count, Case, When, IntegerField, Max
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from wagtail.admin import messages
from wagtail.api.v2.utils import get_full_url

from adl.api.auth import HasAPIKeyOrIsAuthenticated
from adl.core.models import AdlSettings
from adl.core.models import ObservationRecord, QCStatus
from adl.core.models import QCMessage, QCBits
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_qc_summary(request):
    """
    Returns QC stats grouped by station.
    Defaults to the most recent month with data if no params are provided.
    """
    # 1. Parse Request Parameters
    req_month = request.GET.get('month')
    req_year = request.GET.get('year')
    
    target_month = None
    target_year = None
    
    # 2. Validate User Input
    if req_month and req_year:
        try:
            m = int(req_month)
            y = int(req_year)
            if 1 <= m <= 12 and 1900 <= y <= 2100:
                target_month = m
                target_year = y
        except (ValueError, TypeError):
            pass  # Fall through to default logic on error
    
    # 3. Default Logic: Find "Latest Data" if input is missing or invalid
    if target_month is None or target_year is None:
        # Efficiently find the latest timestamp in the database
        latest_obs = ObservationRecord.objects.aggregate(latest=Max('time'))['latest']
        
        if latest_obs:
            # Convert to local time to ensure we get the correct "month" for the user
            # (Database stores UTC, but users think in local time)
            local_latest = dj_timezone.localtime(latest_obs)
            target_month = local_latest.month
            target_year = local_latest.year
        else:
            # Edge case: Database is completely empty
            now = dj_timezone.localtime()
            target_month = now.month
            target_year = now.year
    
    # 4. Perform Aggregation
    # We filter by the determined month/year and group by station
    summary_qs = ObservationRecord.objects.filter(
        time__year=target_year,
        time__month=target_month
    ).values(
        'station__id',
        'station__name',
        'connection__name'
    ).annotate(
        # Count total records for this station in this month
        total=Count('id'),
        
        # Count specific statuses using Case/When conditional logic
        pass_count=Count(Case(
            When(qc_status=QCStatus.PASS, then=1),
            output_field=IntegerField()
        )),
        suspect_count=Count(Case(
            When(qc_status=QCStatus.SUSPECT, then=1),
            output_field=IntegerField()
        )),
        fail_count=Count(Case(
            When(qc_status=QCStatus.FAIL, then=1),
            output_field=IntegerField()
        )),
        not_evaluated_count=Count(Case(
            When(qc_status=QCStatus.NOT_EVALUATED, then=1),
            output_field=IntegerField()
        )),
    ).order_by('connection__name', 'station__name')
    
    # 5. Format Response (Calculate Percentages)
    results = []
    for entry in summary_qs:
        total = entry['total']
        if total > 0:
            # Calculate simple percentages for the UI bars
            pass_pct = round((entry['pass_count'] / total) * 100, 1)
            suspect_pct = round((entry['suspect_count'] / total) * 100, 1)
            fail_pct = round((entry['fail_count'] / total) * 100, 1)
            not_evaluated_pct = round((entry['not_evaluated_count'] / total) * 100, 1)
        else:
            pass_pct = suspect_pct = fail_pct = not_evaluated_pct = 0
        
        station_id = entry['station__id']
        
        results.append({
            'station_id': station_id,
            'station_name': entry['station__name'],
            'connection_name': entry['connection__name'],
            'record_count': total,
            'pass_pct': pass_pct,
            'pass_count': entry['pass_count'],
            'suspect_pct': suspect_pct,
            'suspect_count': entry['suspect_count'],
            'fail_pct': fail_pct,
            'fail_count': entry['fail_count'],
            'not_evaluated_pct': not_evaluated_pct,
            'not_evaluated_count': entry['not_evaluated_count'],
            "inspection_url": reverse("qc_inspect", args=[station_id])
        })
    
    return Response({
        'month': target_month,
        'year': target_year,
        'data': results
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_station_qc_inspection(request, station_id):
    """
    Returns detailed time-series and QC flags for a specific station/month.
    """
    # 1. Parse Dates
    try:
        # Use query_params in DRF, it's more robust than GET
        year_param = request.query_params.get('year')
        month_param = request.query_params.get('month')
        
        if year_param is None or month_param is None:
            raise ValueError("Missing year or month parameters")
        
        year = int(year_param)
        month = int(month_param)
        
        # Calculate range for the whole month
        last_day = calendar.monthrange(year, month)[1]
        
        # Ensure we use the datetime CLASS here, not the module
        start_date = datetime(year, month, 1, tzinfo=timezone.utc)
        end_date = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    
    except (ValueError, TypeError) as e:
        # This print statement in your console holds the truth.
        # If it says "'module' object is not callable", it's the import issue.
        return Response({"error": "Invalid month/year"}, status=400)
    
    # 2. Fetch Observations
    records_qs = ObservationRecord.objects.filter(
        station_id=station_id,
        time__range=(start_date, end_date)
    ).values('time', 'value', 'qc_status').order_by('time')
    
    # 3. Fetch QC Messages
    messages_qs = QCMessage.objects.filter(
        station_id=station_id,
        obs_time__range=(start_date, end_date)
    ).values('obs_time', 'check_type', 'message')
    
    # 4. Format for Frontend
    chart_data = []
    for r in records_qs:
        chart_data.append({
            'x': r['time'].timestamp() * 1000,
            'y': r['value'],
            'status': r['qc_status']
        })
    
    # [cite_start]Map QC bits to readable names [cite: 342]
    qc_bit_map = {b.value: b.name for b in QCBits}
    
    flags_data = []
    for m in messages_qs:
        flags_data.append({
            'x': m['obs_time'].timestamp() * 1000,
            'title': qc_bit_map.get(m['check_type'], 'ERR')[0],
            'type': qc_bit_map.get(m['check_type'], 'Unknown'),
            'text': m['message']
        })
    
    return Response({
        'station_id': station_id,
        'records': chart_data,
        'flags': flags_data
    })


def qc_status_view(request):
    context = {
        "api_url": get_full_url(request, "/api"),
    }
    
    return render(request, 'viewer/quality_control.html', context)


def qc_inspect_view(request, station_id):
    context = {
        "api_url": get_full_url(request, "/api"),
        "station_id": station_id,
    }
    
    year = int(request.GET.get('year'))
    month = int(request.GET.get('month'))
    
    context.update({
        "api_year": year,
        "api_month": month,
    })
    
    return render(request, 'viewer/quality_control_inspect.html', context)
