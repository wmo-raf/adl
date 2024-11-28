from django.forms import Media
from django.urls import reverse
from wagtail.admin.site_summary import SummaryItem
from wagtail.admin.ui.components import Component
from wagtail.api.v2.utils import get_full_url

from adl.core.models import Network, Station
from adl.core.registries import plugin_registry


class NetworksSummaryItem(SummaryItem):
    order = 100
    template_name = "adl/home/adl_summary/adl_summary_networks.html"

    def get_context_data(self, parent_context):
        networks_count = Network.objects.count()

        context = {
            "total_networks": networks_count,
        }

        return context

    def is_shown(self):
        return True


class StationsSummaryItem(SummaryItem):
    order = 200
    template_name = "adl/home/adl_summary/adl_summary_stations.html"

    def get_context_data(self, parent_context):
        stations_count = Station.objects.count()

        context = {
            "total_stations": stations_count,
        }

        return context

    def is_shown(self):
        return True


class PluginsSummaryItem(SummaryItem):
    order = 300
    template_name = "adl/home/adl_summary/adl_summary_plugins.html"

    def get_context_data(self, parent_context):
        plugins = [plugin.label for plugin in plugin_registry.registry.values()]

        context = {
            "total_plugins": len(plugins),
        }

        return context

    def is_shown(self):
        return True


class PluginMonitoringPanel(Component):
    name = "plugin_monitoring"
    template_name = "adl/home/plugin_monitoring_panel.html"
    order = 100

    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        data_url = reverse("plugin_events_data")

        context["data_url"] = get_full_url(None, data_url)

        return context

    @property
    def media(self):
        media = Media(
            js=[
                "vendor/js/date-fns.min.js",
                "vendor/js/highstock.js",
                "vendor/js/highcharts-exporting.js",
                "vendor/js/highcharts-accessibility.js",
            ]
        )

        return media
