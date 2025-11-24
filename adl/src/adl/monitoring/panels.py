from django.forms import Media
from wagtail.admin.ui.components import Component

from adl.core.models import NetworkConnection


class PluginMonitoringPanel(Component):
    name = "plugin_monitoring"
    template_name = "monitoring/plugin_monitoring_panel.html"
    order = 100
    
    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        
        network_connections = NetworkConnection.objects.all().order_by("-plugin_processing_enabled", "network_id",
                                                                       "name")
        context["network_connections"] = network_connections
        data_api_base_url = "/monitoring/plugin-processing-results"
        context["data_api_base_url"] = data_api_base_url
        
        return context
    
    @property
    def media(self):
        media = Media(
            js=[
                "js/vendor/date-fns.min.js",
                "js/vendor/highcharts.js",
                "js/vendor/highcharts-exporting.js",
                "js/vendor/highcharts-accessibility.js",
                "js/monitoring.js",
            ]
        )
        
        return media


class StationActivityPanel(Component):
    name = "station_activity"
    template_name = "monitoring/station_activity_panel.html"
    order = 200
    
    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        
        network_connections = NetworkConnection.objects.all().order_by("network_id")
        context["network_connections"] = network_connections
        
        context["data_api_base_url"] = "/monitoring/station-activity"
        return context
    
    @property
    def media(self):
        media = Media(
            css={
                "all": [
                    "css/vendor/vis-timeline-graph2d.min.css",
                ]
            },
            js=[
                "js/vendor/vis-timeline-graph2d.min.js",
                "js/monitoring.js",
            
            ]
        )
        
        return media
