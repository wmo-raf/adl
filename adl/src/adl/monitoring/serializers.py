import json
from datetime import timedelta

from django_celery_results.models import TaskResult
from rest_framework import serializers

from .models import StationLinkActivityLog


class TaskResultSerializer(serializers.ModelSerializer):
    result = serializers.SerializerMethodField()
    
    class Meta:
        model = TaskResult
        fields = ("date_created", "date_done", "status", "result", "traceback",)
    
    def get_result(self, obj):
        try:
            result = json.loads(obj.result)
        except json.JSONDecodeError:
            result = obj.result
        
        return result


class StationLinkActivityLogSerializer(serializers.ModelSerializer):
    station = serializers.SerializerMethodField()
    start_date = serializers.DateTimeField(source='time', format="%Y-%m-%dT%H:%M:%S.%fZ", read_only=True)
    end_date = serializers.SerializerMethodField()
    
    class Meta:
        model = StationLinkActivityLog
        fields = (
            "id",
            "station",
            "direction",
            "success",
            "message",
            "duration_ms",
            "records_count",
            "messages_count",
            "message",
            "start_date",
            "end_date",
            # Assuming 'time' is the inherited field from TimescaleModel
        )
        read_only_fields = ("id", "time",)
    
    def get_station(self, obj):
        return obj.station_link.station.name
    
    def get_end_date(self, obj):
        start_date = obj.time
        duration_ms = obj.duration_ms
        
        if start_date and duration_ms is not None:
            end_date = start_date + timedelta(milliseconds=duration_ms)
            
            return end_date.isoformat()
        
        return None
