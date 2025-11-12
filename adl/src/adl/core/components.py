from django.middleware.csrf import get_token
from wagtail.admin.ui.components import Component

from adl.monitoring.models import StationLinkActivityLog


class StationLinkCollectionStatusPanel(Component):
    template_name = 'core/panels/sl_collection_status.html'
    
    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        station_link = parent_context.get('station_link')
        
        # get latest log entry for this station link
        latest_pull_log = StationLinkActivityLog.objects.filter(
            station_link=station_link, direction="pull"
        ).order_by('-time').first()
        
        dispatch_channels = station_link.get_dispatch_channels()
        
        if dispatch_channels:
            for dispatch_channel in dispatch_channels:
                latest_push_log = StationLinkActivityLog.objects.filter(
                    station_link=station_link,
                    direction="push",
                    dispatch_channel=dispatch_channel
                ).order_by('-time').first()
                dispatch_channel.latest_push_log = latest_push_log
        
        station_link.latest_pull_log = latest_pull_log
        station_link.dispatch_channels = dispatch_channels
        context['station_link'] = station_link
        
        if 'request' in parent_context:
            context['request'] = parent_context['request']
            context['csrf_token'] = get_token(parent_context['request'])
        
        return context
