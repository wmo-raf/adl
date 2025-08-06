from django.db import models
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
    
    def __str__(self):
        return f"{self.station_link} - {self.direction} - {self.time}"
