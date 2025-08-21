from django.db import models
from django.db.models import Q
from timescale.db.models.models import TimescaleModel
from wagtail.snippets.models import register_snippet


@register_snippet
class StationLinkActivityLog(TimescaleModel):
    DIRECTION_CHOICES = (
        ("pull", "Pull"),
        ("push", "Push"),
    )
    
    # time field is inherited from TimescaleModel. We use it to store the start time of the activity
    station_link = models.ForeignKey('core.StationLink', on_delete=models.CASCADE)
    direction = models.CharField(max_length=255, choices=DIRECTION_CHOICES)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True, null=True)
    duration_ms = models.IntegerField(blank=True, null=True)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    records_count = models.PositiveIntegerField(default=0, null=True, blank=True)
    messages_count = models.PositiveIntegerField(default=0)
    obs_start_time = models.DateTimeField(blank=True, null=True, verbose_name="Observation Start Time")
    obs_end_time = models.DateTimeField(blank=True, null=True, verbose_name="Observation End Time")
    dispatch_channel = models.ForeignKey('core.DispatchChannel', on_delete=models.CASCADE, related_name='activity_logs',
                                         blank=True, null=True)
    
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
