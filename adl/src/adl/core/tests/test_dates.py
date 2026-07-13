from django.test import TestCase

from .factories import StationLinkFactory
from .helpers import make_test_plugin


class DatesWindowTests(TestCase):
    def test_dates_window_latest(self):
        plugin = make_test_plugin()
        link = StationLinkFactory()
        start, end = plugin.get_dates_for_station(link, latest=True)
        self.assertEqual((end - start).total_seconds(), 3600)
        self.assertEqual((start.minute, start.second), (0, 0))
        self.assertEqual((end.minute, end.second), (0, 0))
