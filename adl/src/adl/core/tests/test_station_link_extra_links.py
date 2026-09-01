"""
StationLink.get_extra_model_admin_links() — the per-station-link hook a
plugin overrides to offer extra admin pages. Core renders it in two places:
the index-row "more" menu (ListingButton) and the inspect page header
(HeaderButton). Both are built from the same helper so the two surfaces can
never disagree about which links exist.
"""
from django.test import SimpleTestCase, TestCase
from wagtail.admin.widgets import HeaderButton, ListingButton

from adl.core.models import StationLink
from adl.core.tests.factories import StationLinkFactory
from adl.core.utils import (
    get_extra_model_admin_header_buttons,
    get_extra_model_admin_link_buttons,
    get_station_link_list_more_buttons,
    get_station_link_view_data_url,
)
from adl.core.viewsets import StationLinkInspectView


class _LinkWithPages:
    id = 7
    network_connection_id = 3

    def get_extra_model_admin_links(self):
        return [
            {"label": "Direct fetch files", "url": "/x/files/",
             "icon_name": "doc-full", "kwargs": {"attrs": {"target": "_blank"}}},
            {"label": "No url — skipped"},
            {"url": "/no-label/"},
        ]


class _LinkWithoutPages:
    id = 7
    network_connection_id = 3

    def get_extra_model_admin_links(self):
        return []


class _LinkWithoutHook:
    pass


class ExtraModelAdminLinkHelpersTests(SimpleTestCase):
    def test_row_buttons_are_listing_buttons_built_from_usable_entries_only(self):
        buttons = get_extra_model_admin_link_buttons(_LinkWithPages())
        self.assertEqual(len(buttons), 1)
        self.assertIsInstance(buttons[0], ListingButton)
        self.assertEqual(buttons[0].label, "Direct fetch files")
        self.assertEqual(buttons[0].url, "/x/files/")
        self.assertEqual(buttons[0].icon_name, "doc-full")
        self.assertEqual(buttons[0].attrs.get("target"), "_blank")

    def test_header_buttons_mirror_row_buttons(self):
        row = get_extra_model_admin_link_buttons(_LinkWithPages())
        header = get_extra_model_admin_header_buttons(_LinkWithPages())
        self.assertEqual([b.label for b in header], [b.label for b in row])
        self.assertEqual([b.url for b in header], [b.url for b in row])
        self.assertIsInstance(header[0], HeaderButton)

    def test_empty_and_missing_hook_yield_no_buttons(self):
        for instance in (_LinkWithoutPages(), _LinkWithoutHook()):
            self.assertEqual(get_extra_model_admin_link_buttons(instance), [])
            self.assertEqual(get_extra_model_admin_header_buttons(instance), [])


class StationLinkHookDefaultTests(TestCase):
    def test_base_station_link_offers_no_extra_pages(self):
        link = StationLinkFactory()
        self.assertEqual(link.get_extra_model_admin_links(), [])
        self.assertTrue(hasattr(StationLink, "get_extra_model_admin_links"))


class StationLinkInspectHeaderTests(SimpleTestCase):
    def _view_for(self, obj):
        view = StationLinkInspectView()
        view.object = obj
        # get_edit_url/get_delete_url need a viewset; the "more" dropdown
        # is not what this test is about, so stub them out
        view.get_edit_url = lambda: None
        view.get_delete_url = lambda: None
        return view

    def test_plugin_links_render_as_header_buttons(self):
        buttons = self._view_for(_LinkWithPages()).get_header_buttons()
        labels = [getattr(b, "label", None) for b in buttons]
        self.assertIn("Direct fetch files", labels)

    def test_view_data_is_the_only_header_button_without_plugin_links(self):
        view = self._view_for(_LinkWithoutPages())
        header_buttons = [
            b for b in view.get_header_buttons() if isinstance(b, HeaderButton)
        ]
        self.assertEqual([b.label for b in header_buttons], ["View Data"])
        self.assertEqual(header_buttons[0].url, get_station_link_view_data_url(_LinkWithoutPages()))


class ViewDataLinkTests(SimpleTestCase):
    def test_url_deep_links_the_viewer_table(self):
        self.assertEqual(
            get_station_link_view_data_url(_LinkWithPages()),
            "/viewer/table/?connection=3&station=7",
        )

    def test_row_menu_offers_view_data_before_plugin_links(self):
        buttons = get_station_link_list_more_buttons(_LinkWithPages())
        self.assertEqual(
            [b.label for b in buttons], ["View Data", "Direct fetch files"]
        )
        self.assertIsInstance(buttons[0], ListingButton)
