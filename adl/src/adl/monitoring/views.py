from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime
from django_celery_results.models import TaskResult
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .constants import NETWORK_PLUGIN_TASK_NAME
from .serializers import TaskResultSerializer


@api_view()
def get_network_conn_plugin_task_results_since(request, network_conn_id, from_date=None):
    if from_date:
        from_date = parse_datetime(from_date)
        
        if not from_date:
            return Response({"error": "Invalid date format. Please provide a valid date format."}, status=400)
        
        if dj_timezone.is_naive(from_date):
            from_date = dj_timezone.make_aware(from_date)
    else:
        # use the beginning of today
        from_date = dj_timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    
    network_conn_task_name = f"{NETWORK_PLUGIN_TASK_NAME}({network_conn_id})"
    
    queryset = TaskResult.objects.filter(
        periodic_task_name=network_conn_task_name,
        date_done__gte=from_date
    )
    
    latest_record = queryset.last()
    
    serialized_data = TaskResultSerializer(queryset, many=True).data
    
    response = {
        "latest_record": TaskResultSerializer(latest_record).data if latest_record else None,
        "data": serialized_data
    }
    
    return Response(response)
