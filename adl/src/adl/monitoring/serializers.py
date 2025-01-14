import json

from django_celery_results.models import TaskResult
from rest_framework import serializers


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
