from wagtail.admin.panels import Panel


class IngestTimeoutBudgetPanel(Panel):
    """
    Shows the per-station ingestion timeout an operator actually gets, once the
    batch soft limit is clamped to the connection's beat interval.

    Three fields — ``ingest_timeout_seconds``, ``batch_size`` and
    ``plugin_processing_interval`` — combine into one effective figure that
    matches none of them, and at stock defaults the configured 300s is really
    90s. Decision #153 settled that the admin displays the computed number
    rather than leaving operators to derive it.

    The figure is computed from the *saved* instance, so it lags the form until
    the next save; the template says so rather than implying it is live.
    """

    class BoundPanel(Panel.BoundPanel):
        template_name = "core/panels/ingest_timeout_budget.html"

        def is_shown(self):
            # Nothing meaningful to compute before the first save, and an
            # unsaved instance would show numbers the operator never chose.
            return self.instance is not None and self.instance.pk is not None

        def get_context_data(self, parent_context=None):
            context = super().get_context_data(parent_context)

            from adl.core.tasks import (
                effective_ingest_batch_size,
                effective_ingest_station_seconds,
                ingest_batch_soft_limit_seconds,
            )

            connection = self.instance
            batch_size = effective_ingest_batch_size(connection)
            configured = connection.ingest_timeout_seconds
            effective = effective_ingest_station_seconds(connection)

            context.update({
                "batch_size": batch_size,
                "interval_minutes": connection.plugin_processing_interval,
                "configured_seconds": configured,
                "effective_seconds": effective,
                "batch_limit_seconds": ingest_batch_soft_limit_seconds(connection, batch_size),
                # Only a full batch that would outrun the interval gets cut back
                "is_clamped": effective < configured,
            })

            return context
