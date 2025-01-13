from rest_framework import serializers

from adl.core.models import (
    Network,
    Station,
    NetworkConnection,
    ObservationRecord,
    HourlyAggregatedObservationRecord,
    DailyAggregatedObservationRecord
)

from collections import defaultdict


class ReadOnlyModelSerializer(serializers.ModelSerializer):
    def get_fields(self, *args, **kwargs):
        fields = super().get_fields(*args, **kwargs)
        for field in fields:
            fields[field].read_only = True
        return fields


class NetworkSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = Network
        fields = ("id", "name",)


class StationSerializer(ReadOnlyModelSerializer):
    location = serializers.SerializerMethodField()
    
    class Meta:
        model = Station
        fields = ("id", "name", "network", "wigos_id", "location", "station_height_above_msl",)
    
    def get_location(self, obj):
        return {"latitude": obj.location.y, "longitude": obj.location.x}


class NetworkConnectionSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = NetworkConnection
        fields = ("id", "name", "network", "plugin", "plugin_processing_enabled", "plugin_processing_interval")


class ObservationRecordSerializer(ReadOnlyModelSerializer):
    class Meta:
        model = ObservationRecord
        fields = ("parameter_id", "connection_id", "time", "value")
