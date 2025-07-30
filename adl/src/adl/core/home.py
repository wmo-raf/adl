from django.urls import reverse
from wagtail.admin.site_summary import SummaryItem

from adl.core.models import (
    Network,
    Station,
    NetworkConnection,
    DispatchChannel
)
from adl.core.registries import plugin_registry
from adl.core.viewsets import NetworkViewSet, StationViewSet


class NetworksSummaryItem(SummaryItem):
    order = 100
    template_name = "adl/home/adl_summary/adl_summary_networks.html"
    
    def get_context_data(self, parent_context):
        networks_count = Network.objects.count()
        index_url = reverse(NetworkViewSet().get_url_name("index"))
        
        context = {
            "total_networks": networks_count,
            "link": index_url
        }
        
        return context


class StationsSummaryItem(SummaryItem):
    order = 200
    template_name = "adl/home/adl_summary/adl_summary_stations.html"
    
    def get_context_data(self, parent_context):
        stations_count = Station.objects.count()
        index_url = reverse(StationViewSet().get_url_name("index"))
        
        context = {
            "total_stations": stations_count,
            "link": index_url
        }
        
        return context


class ConnectionsSummaryItem(SummaryItem):
    order = 300
    template_name = "adl/home/adl_summary/adl_summary_connections.html"
    
    def get_context_data(self, parent_context):
        connections_count = NetworkConnection.objects.count()
        url = reverse("connections_list")
        
        context = {
            "total_connections": connections_count,
            "link": url
        }
        
        return context


class DispatchChannelsSummaryItem(SummaryItem):
    order = 400
    template_name = "adl/home/adl_summary/adl_summary_dispatch_channels.html"
    
    def get_context_data(self, parent_context):
        dispatch_channels_count = DispatchChannel.objects.count()
        url = reverse("dispatch_channels_list")
        
        context = {
            "total_dispatch_channels": dispatch_channels_count,
            "link": url
        }
        
        return context


class PluginsSummaryItem(SummaryItem):
    order = 500
    template_name = "adl/home/adl_summary/adl_summary_plugins.html"
    
    def get_context_data(self, parent_context):
        plugins = plugin_registry.get_all()
        url = reverse("plugins_list")
        
        context = {
            "total_plugins": len(plugins),
            "link": url,
        }
        
        return context
