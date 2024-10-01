from rest_framework import serializers

from wis2box_adl.core.models import DataIngestionRecord, PluginExecutionEvent


class DataIngestionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataIngestionRecord
        fields = ["time", "created_at"]


class PluginExecutionEventSerializer(serializers.ModelSerializer):
    records_count = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()

    class Meta:
        model = PluginExecutionEvent
        fields = ["plugin", "timestamp", "success", "records_count"]

    def get_records_count(self, obj):
        return obj.get_data_ingestion_count()

    def get_timestamp(self, obj):
        return obj.finished_at_utc_timestamp() * 1000
