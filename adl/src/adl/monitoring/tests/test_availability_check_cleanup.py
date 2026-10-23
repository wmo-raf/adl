"""The daily monitoring cleanup prunes availability checks with the activity-log cutoff."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from adl.core.availability_checks import TIER_FETCH
from adl.core.source_checks import SourceCheckStatus
from adl.core.tests.factories import StationLinkFactory
from adl.monitoring.models import AvailabilityCheck
from adl.monitoring.tasks import run_station_link_activity_log_cleanup


class AvailabilityCheckCleanupTests(TestCase):
    def make_check(self, link, age):
        now = timezone.now()
        return AvailabilityCheck.objects.create(
            station_link=link, window_start=now - age, window_end=now - age + timedelta(hours=1),
            created_at=now - age, tier=TIER_FETCH, status=SourceCheckStatus.OK)

    def test_old_checks_are_pruned_and_recent_ones_kept(self):
        link = StationLinkFactory()
        old = self.make_check(link, timedelta(days=8))
        recent = self.make_check(link, timedelta(days=6))

        run_station_link_activity_log_cleanup()

        self.assertEqual(list(AvailabilityCheck.objects.values_list("id", flat=True)), [recent.id])
        self.assertFalse(AvailabilityCheck.objects.filter(id=old.id).exists())
