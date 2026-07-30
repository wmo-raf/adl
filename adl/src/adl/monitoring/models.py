from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from timescale.db.models.models import TimescaleModel
from wagtail.snippets.models import register_snippet

from adl.core.classification import FAILURE_CATEGORIES

from .constants import CheckState


@register_snippet
class StationLinkActivityLog(TimescaleModel):
    DIRECTION_CHOICES = (
        ("pull", "Pull"),
        ("push", "Push"),
    )
    
    class ActivityStatus(models.TextChoices):
        STARTED = "STARTED"
        IN_PROGRESS = "IN_PROGRESS"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"
        SKIPPED = "SKIPPED"
    
    # time field is inherited from TimescaleModel. We use it to store the start time of the activity
    station_link = models.ForeignKey('core.StationLink', on_delete=models.CASCADE)
    direction = models.CharField(max_length=255, choices=DIRECTION_CHOICES)
    success = models.BooleanField(default=False)
    status = models.CharField(max_length=50, choices=ActivityStatus, default="STARTED")
    message = models.TextField(blank=True, null=True)
    duration_ms = models.IntegerField(blank=True, null=True)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    records_count = models.PositiveIntegerField(default=0, null=True, blank=True)
    # Tri-state: NULL = the plugin did not report how many candidate source
    # items it resolved; 0 = it looked and found nothing; n = it found n.
    sources_count = models.PositiveIntegerField(default=None, null=True, blank=True)
    messages_count = models.PositiveIntegerField(default=0)
    obs_start_time = models.DateTimeField(blank=True, null=True, verbose_name="Observation Start Time")
    obs_end_time = models.DateTimeField(blank=True, null=True, verbose_name="Observation End Time")
    dispatch_channel = models.ForeignKey('core.DispatchChannel', on_delete=models.CASCADE, related_name='activity_logs',
                                         blank=True, null=True)
    # Write-time failure classification (see adl.core.classification).
    # error_category: NULL = core declined or the row is not a failure.
    # error_layer: 4 = network path, 5 = source; NULL = producer declined.
    # exception_class: the raw fact, recorded even when core declines.
    error_category = models.CharField(
        max_length=50, blank=True, null=True,
        choices=[(c, c) for c in FAILURE_CATEGORIES],
    )
    error_layer = models.PositiveSmallIntegerField(blank=True, null=True)
    exception_class = models.CharField(max_length=255, blank=True, null=True)
    
    class Meta:
        indexes = [
            # "latest per station" & station timelines
            models.Index(
                fields=["station_link", "time"],
                name="sta_station_time_idx",
            ),
            
            # filter by direction as well
            models.Index(
                fields=["station_link", "direction", "time"],
                name="sta_station_dir_time_idx",
            ),
            
            # “recent failures” (partial index)
            models.Index(
                fields=["time"],
                name="sta_failed_time_idx",
                condition=Q(success=False),
            ),
            
            # For push filtered by dispatch channel
            models.Index(
                fields=["dispatch_channel", "time"],
                name="sta_channel_time_idx",
            ),
        ]
    
    def __str__(self):
        return f"{self.station_link} - {self.direction} - {self.time}"
    
    def duration_seconds(self):
        if self.duration_ms is not None:
            return self.duration_ms / 1000.0
        return None
    
    @property
    def complete(self):
        return self.success and self.status == self.ActivityStatus.COMPLETED


class NetworkConnectionHealth(models.Model):
    """
    The current stored verdict of the ingestion diagnostic for one
    connection — one overwritten row per connection of headline-only
    normalised columns, no JSON blob.

    The full checklist is computed on read in :mod:`adl.monitoring.health`;
    only change is persisted. ``status`` carries ``DISABLED`` (and later
    ``MISCONFIGURED``) as well as the ladder verdicts; ``first_failing_layer``
    is ``NULL`` for both, because no layer failed.

    ``since`` moves on ``(status, first_failing_layer)`` only. The category
    behind a failure flaps; a flapping ``since`` would destroy the field's
    only claim — how long the connection has been in its current state.
    """

    connection = models.OneToOneField('core.NetworkConnection', on_delete=models.CASCADE,
                                      related_name="health", verbose_name=_("Connection"))
    status = models.CharField(max_length=20, choices=CheckState.choices, verbose_name=_("Status"))
    first_failing_layer = models.CharField(max_length=32, blank=True, null=True,
                                           verbose_name=_("First Failing Layer"))
    headline_check_id = models.CharField(max_length=64, blank=True, null=True,
                                         verbose_name=_("Headline Check"))
    headline_message = models.TextField(blank=True, default="", verbose_name=_("Headline Message"))
    since = models.DateTimeField(verbose_name=_("Since"))
    evaluated_at = models.DateTimeField(verbose_name=_("Evaluated At"))

    class Meta:
        verbose_name = _("Network Connection Health")
        verbose_name_plural = _("Network Connection Health")

    def __str__(self):
        return f"{self.connection} - {self.status}"


class NetworkConnectionHealthTransition(models.Model):
    """
    Append-only record of each ``(status, first_failing_layer)`` change —
    alerting queries transitions, not states, and repeated flapping surfaces
    as a count of rows. Rows older than 90 days are dropped by the daily
    monitoring cleanup task.
    """

    RETENTION_DAYS = 90

    connection = models.ForeignKey('core.NetworkConnection', on_delete=models.CASCADE,
                                   related_name="health_transitions", verbose_name=_("Connection"))
    at = models.DateTimeField(verbose_name=_("At"))
    from_status = models.CharField(max_length=20, choices=CheckState.choices,
                                   blank=True, null=True, verbose_name=_("From Status"))
    from_first_failing_layer = models.CharField(max_length=32, blank=True, null=True,
                                                verbose_name=_("From First Failing Layer"))
    to_status = models.CharField(max_length=20, choices=CheckState.choices, verbose_name=_("To Status"))
    to_first_failing_layer = models.CharField(max_length=32, blank=True, null=True,
                                              verbose_name=_("To First Failing Layer"))

    class Meta:
        verbose_name = _("Network Connection Health Transition")
        verbose_name_plural = _("Network Connection Health Transitions")
        indexes = [
            models.Index(fields=["connection", "at"], name="health_trans_conn_at_idx"),
        ]

    def __str__(self):
        return f"{self.connection} - {self.from_status} -> {self.to_status} at {self.at}"
