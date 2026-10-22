from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as dj_tz

from adl.core.models import StationChannelDispatchStatus
from adl.monitoring.models import StationLinkActivityLog
from .factories import StationLinkFactory, Wis2BoxUploadFactory

# Wagtail's post_save handler looks the task up as a module global. The task
# itself is a frozen dataclass, so its enqueue can't be patched in place
TASK = "wagtail.signal_handlers.update_reference_index_task"


class ReferenceIndexIgnoreTests(TestCase):
    """
    Dispatch writes these rows for every station on every run. Each save of an
    indexed model runs a reference-index task inline in the dispatch worker,
    so these high-churn models must opt out of the index.
    """

    def setUp(self):
        self.link = StationLinkFactory()
        self.channel = Wis2BoxUploadFactory()

    def test_indexed_model_save_enqueues_task(self):
        # Guards the patch target: if this stops firing, the tests below
        # would pass for the wrong reason
        with patch(TASK) as task:
            self.channel.save()

        task.enqueue.assert_called()

    def test_activity_log_save_enqueues_no_task(self):
        with patch(TASK) as task:
            log = StationLinkActivityLog.objects.create(
                time=dj_tz.now(),
                station_link=self.link,
                direction="push",
                dispatch_channel=self.channel,
            )
            log.success = True
            log.save()

        task.enqueue.assert_not_called()

    def test_dispatch_status_save_enqueues_no_task(self):
        with patch(TASK) as task:
            status = StationChannelDispatchStatus.objects.create(
                channel=self.channel,
                station=self.link.station,
                last_sent_obs_time=dj_tz.now(),
            )
            status.save()

        task.enqueue.assert_not_called()
