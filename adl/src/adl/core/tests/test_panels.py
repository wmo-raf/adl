from django.test import RequestFactory, TestCase
from wagtail.admin.panels import ObjectList

from adl.core.models import NetworkConnection
from adl.core.panels import IngestTimeoutBudgetPanel
from .factories import NetworkConnectionFactory


class IngestTimeoutBudgetPanelTests(TestCase):
    """The admin's rendering of the effective per-station timeout (#153 §2).

    Rendered through the real panel + template rather than asserting on the
    helper alone, since the point of the ticket is that operators can *see*
    the clamp.
    """

    def setUp(self):
        self.request = RequestFactory().get("/")
        self.panel = IngestTimeoutBudgetPanel().bind_to_model(NetworkConnection)

    def render_for(self, connection):
        bound = self.panel.get_bound_panel(
            instance=connection, request=self.request, form=None, prefix="panel"
        )
        return bound, bound.render_html()

    def test_clamped_connection_shows_the_shortened_share(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=15, ingest_timeout_seconds=300, batch_size=10
        )

        bound, html = self.render_for(connection)

        self.assertTrue(bound.is_shown())
        # the configured 300s is really 90s a station at stock defaults
        self.assertIn("90 seconds", html)
        self.assertIn("300 seconds", html)
        self.assertIn("help-warning", html)

    def test_unclamped_connection_says_the_full_timeout_applies(self):
        connection = NetworkConnectionFactory(
            plugin_processing_interval=30, ingest_timeout_seconds=300, batch_size=2
        )

        bound, html = self.render_for(connection)

        self.assertIn("full 300 seconds", html)
        self.assertIn("help-info", html)
        self.assertNotIn("help-warning", html)

    def test_renders_inside_the_real_connection_edit_form(self):
        """The panel sits in a MultiFieldPanel on a live edit form; rendering it
        standalone would not catch a break in that path."""
        connection = NetworkConnectionFactory(
            plugin_processing_interval=15, ingest_timeout_seconds=300, batch_size=10
        )

        edit_handler = ObjectList(NetworkConnection.panels).bind_to_model(NetworkConnection)
        form = edit_handler.get_form_class()(instance=connection)
        bound = edit_handler.get_bound_panel(
            instance=connection, request=self.request, form=form
        )

        html = bound.render_html()

        self.assertIn("90 seconds", html)
        # the field's own help text must no longer promise a per-station cut-off
        self.assertIn("Time budgeted per station", html)
        self.assertNotIn("before it is terminated", html)

    def test_hidden_before_the_connection_is_saved(self):
        # an unsaved instance would show numbers the operator never chose
        bound = self.panel.get_bound_panel(
            instance=NetworkConnection(), request=self.request, form=None, prefix="panel"
        )

        self.assertFalse(bound.is_shown())
