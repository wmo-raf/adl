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
    # Force UTC "Z" format for start_date
    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    dispatch_channel = serializers.SerializerMethodField()
    
    # Optional: include a stable station id
    # station_id = serializers.SerializerMethodField()
    
    class Meta:
        model = StationLinkActivityLog
        fields = (
            "id",
            "station",
            # "station_id",  # optional
            "direction",
            "success",
            "message",
            "duration_ms",
            "records_count",
            "messages_count",
            "start_date",
            "end_date",
            "dispatch_channel",
        )
        read_only_fields = ("id",)
    
    def _to_utc_z(self, dt):
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    
    def get_station(self, obj):
        return obj.station_link.station.name
    
    # Optional
    # def get_station_id(self, obj):
    #     return obj.station_link.station_id
    
    def get_start_date(self, obj):
        return self._to_utc_z(obj.time)
    
    def get_end_date(self, obj):
        if obj.time and obj.duration_ms is not None:
            end_dt = obj.time + timedelta(milliseconds=obj.duration_ms)
            return self._to_utc_z(end_dt)
        return None
    
    def get_dispatch_channel(self, obj):
        dc = obj.dispatch_channel
        if not dc:
            return None
        return {"id": str(dc.id), "name": dc.name, "public_url": dc.public_url}
