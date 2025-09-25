from django import template
from django.template.loader import render_to_string
from django_celery_results.models import TaskResult

from adl.core.models import DispatchChannel
from adl.monitoring.constants import NETWORK_DISPATCH_TASK_NAME
from adl.monitoring.serializers import TaskResultSerializer

register = template.Library()


@register.simple_tag
def render_network_dispatch_channel_status(network_connection_id):
    dispatch_channels = DispatchChannel.objects.filter(network_connections=network_connection_id)
    
    network_dispatch_channels_task_results = []
    
    for channel in dispatch_channels:
        periodic_task_name = f"{NETWORK_DISPATCH_TASK_NAME}({channel.id})"
        
        latest_task_result = TaskResult.objects.filter(
            periodic_task_name=periodic_task_name
        ).order_by("-date_done").first()
        
        latest_station_dispatch_obs = channel.dispatch_statuses.order_by("-last_sent_obs_time").first()
        
        network_dispatch_channels_task_results.append({
            "channel": channel,
            "latest_task_result": latest_task_result,
            "latest_task_result_dict": TaskResultSerializer(latest_task_result).data if latest_task_result else None,
            "latest_station_dispatch_obs": latest_station_dispatch_obs,
        })
    
    return render_to_string("monitoring/dispatch_channel_status.html", {
        "network_dispatch_channels_task_results": network_dispatch_channels_task_results
    })
