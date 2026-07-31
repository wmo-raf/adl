from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils import timezone as dj_timezone
from wagtail.admin.ui.components import Component

from adl.core.source_checks import CHECK_STATION_SOURCE
from adl.monitoring.health import configuration_drift, probe_age_minutes
from adl.monitoring.models import SourceProbeResult, StationLinkActivityLog


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


class StationLinkSourceCheckPanel(Component):
    """
    The station-scope source check on the station-link inspect page: the
    on-demand check button, this station's own latest stored result, and
    the advisory configuration-drift notice.

    The button is hidden, not disabled, when the user lacks the probe
    permission or the plugin does not implement the contract. Only rows
    carrying this station link's FK are shown — a connection-scope probe
    result is never presented as this station's answer.
    """

    template_name = 'core/panels/sl_source_check.html'

    def get_context_data(self, parent_context):
        # Imported here, not at module level: the views module imports core
        # models and utils, which import back into this app at startup
        from adl.monitoring.views.health import PROBE_PERMISSION

        context = super().get_context_data(parent_context)
        station_link = parent_context.get('station_link')
        request = parent_context.get('request')

        # Filtered on the check id as well as the FK, so only a
        # station-scope check's own row can ever be presented as this
        # station's answer — by construction, not by convention
        latest = (SourceProbeResult.objects
                  .filter(station_link=station_link,
                          check_id=CHECK_STATION_SOURCE)
                  .order_by('-at')
                  .first())
        if latest is not None:
            latest.age_minutes = probe_age_minutes(dj_timezone.now(), latest.at)

        drift = configuration_drift(station_link)

        context['station_link'] = station_link
        context['latest_result'] = latest
        context['configuration_drift'] = drift if drift.drifted else None
        context['show_check_button'] = (
            request is not None
            and request.user.has_perm(PROBE_PERMISSION)
            and station_link.station_source_check_supported
        )
        context['check_source_url'] = reverse('station_link_check_source',
                                              args=[station_link.id])

        if request is not None:
            context['request'] = request
            context['csrf_token'] = get_token(request)

        return context
