"""Shared per-station status computation.

The pull-side (network connection) and push-side (dispatch channel) activity
views both render a per-station pipeline status and data status. This module
is the one computation both consume — and the seam anything else that needs
the same verdict (the per-connection diagnostic) should read from, so they
cannot disagree about the same station.

Everything here works on plain domain objects and timestamps — no view, no
request — so it is callable from tasks, management commands and templates.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import OuterRef, Subquery
from django.utils import timezone as dj_timezone

ACTIVE = "active"
WARNING = "warning"
ERROR = "error"


def annotate_station_pull_activity(station_links):
    """Annotate a StationLink queryset with the three timestamps
    :func:`compute_station_status` consumes on the pull side: ``last_check``
    and ``last_log_success`` from the latest pull activity log, and
    ``last_collected`` from the latest stored observation.

    The activity view and the connection diagnostic both read from here, so
    they cannot disagree about the same station.
    """
    from adl.core.models import ObservationRecord

    from .models import StationLinkActivityLog

    latest_log_sq = StationLinkActivityLog.objects.filter(
        station_link=OuterRef('pk'),
        direction='pull'
    ).order_by('-time')

    # Filtering by connection utilises the composite index on
    # ObservationRecord ['connection', 'station', '-time']
    latest_obs_sq = ObservationRecord.objects.filter(
        station=OuterRef('station'),
        connection=OuterRef('network_connection')
    ).order_by('-time')

    return station_links.annotate(
        last_check=Subquery(latest_log_sq.values('time')[:1]),
        last_log_success=Subquery(latest_log_sq.values('success')[:1]),
        last_collected=Subquery(latest_obs_sq.values('time')[:1])
    )


@dataclass(frozen=True)
class StatusThresholds:
    """Time budgets a station is judged against.

    ``pipeline_tolerance`` is how long we tolerate silence from the scheduled
    job before it counts as stopped. The two freshness limits bound how old
    the station's most recent data may be before it degrades.
    """

    pipeline_tolerance: timedelta
    freshness_warning_limit: timedelta
    freshness_error_limit: timedelta


@dataclass(frozen=True)
class StationStatus:
    pipeline_status: str
    data_status: str

    @property
    def overall_status(self):
        """Worst of the two axes — what the summary counters roll up."""
        if self.pipeline_status == ERROR or self.data_status == ERROR:
            return ERROR
        if self.pipeline_status == WARNING or self.data_status == WARNING:
            return WARNING
        return ACTIVE


def connection_thresholds(connection):
    """Thresholds for a pull-side (ingestion) connection."""
    pipeline_tolerance = timedelta(minutes=connection.interval * 3)

    if connection.is_daily_data:
        # Daily: Active < 26h, Warning < 48h, Error > 48h
        freshness_warning_limit = timedelta(hours=26)
        freshness_error_limit = timedelta(hours=48)
    else:
        # High Frequency: Active < 4x interval, Warning < 12x interval
        freshness_warning_limit = timedelta(minutes=connection.interval * 4)
        freshness_error_limit = timedelta(minutes=connection.interval * 12)

    return StatusThresholds(
        pipeline_tolerance=pipeline_tolerance,
        freshness_warning_limit=freshness_warning_limit,
        freshness_error_limit=freshness_error_limit,
    )


def dispatch_channel_thresholds(channel):
    """Thresholds for a push-side (dispatch) channel.

    Aggregating channels are inherently behind by the size of their window,
    so that window (plus processing slack) is added to the freshness limits.
    """
    check_interval = channel.data_check_interval

    # 3 missed cycles means the scheduler is stuck
    pipeline_tolerance = timedelta(minutes=check_interval * 3)

    base_warning_minutes = check_interval * 4
    base_error_minutes = check_interval * 12

    aggregation_offset = timedelta(0)
    if channel.send_aggregated_data:
        if channel.aggregation_period == "hourly":
            aggregation_offset = timedelta(hours=2)
        elif channel.aggregation_period == "daily":  # Future proofing
            aggregation_offset = timedelta(days=1)

        # Extra buffer: aggregation runs *after* the period closes.
        aggregation_offset += timedelta(minutes=5)

    return StatusThresholds(
        pipeline_tolerance=pipeline_tolerance,
        freshness_warning_limit=timedelta(minutes=base_warning_minutes) + aggregation_offset,
        freshness_error_limit=timedelta(minutes=base_error_minutes) + aggregation_offset,
    )


def compute_station_status(last_check, last_check_success, last_data_time, thresholds, now=None):
    """Status of one station from its latest activity.

    ``last_check`` / ``last_check_success`` describe the most recent run of the
    scheduled job for this station (a pull collection or a push attempt);
    ``last_data_time`` is the timestamp of its most recent data (an observation
    collected, or an observation sent). Any of them may be ``None``.
    """
    now = now or dj_timezone.now()

    pipeline_status = WARNING  # Default if never checked
    if last_check:
        if not last_check_success:
            pipeline_status = ERROR  # Last run crashed
        elif now - last_check > thresholds.pipeline_tolerance:
            pipeline_status = WARNING  # Last run ok, but scheduler stopped
        else:
            pipeline_status = ACTIVE  # Healthy

    data_status = WARNING  # Default if no data
    if last_data_time:
        data_age = now - last_data_time
        if data_age <= thresholds.freshness_warning_limit:
            data_status = ACTIVE
        elif data_age <= thresholds.freshness_error_limit:
            data_status = WARNING
        else:
            data_status = ERROR  # Data is stale

    return StationStatus(pipeline_status=pipeline_status, data_status=data_status)
