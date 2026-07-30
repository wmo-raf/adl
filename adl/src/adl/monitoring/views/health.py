from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext as _

from adl.core.models import NetworkConnection

from ..constants import LAYER_LABELS
from ..health import EVALUATED_LAYERS, evaluate_connection_health
from ..models import NetworkConnectionHealth


def connection_health(request, connection_id):
    """
    The per-connection ingestion diagnostic page. The checklist is computed
    on this read, so the page is never staler than the moment it was opened —
    but persisting the verdict belongs to the sweep task alone, so a GET has
    no write side effects. The stored row supplies ``since``; before the
    first sweep there is none, which is the day-one state on every
    deployment, and the page renders regardless.
    """
    connection = get_object_or_404(NetworkConnection, id=connection_id)

    checklist = evaluate_connection_health(connection)
    health = NetworkConnectionHealth.objects.filter(connection=connection).first()

    layer_groups = [
        {
            "layer": layer,
            "label": LAYER_LABELS[layer],
            "checks": checklist.checks_for_layer(layer),
        }
        for layer in EVALUATED_LAYERS
    ]

    context = {
        "breadcrumbs_items": [
            {"url": reverse("wagtailadmin_home"), "label": _("Home")},
            {"url": reverse("connections_list"), "label": _("Network Connections")},
            {"url": None, "label": _("Ingestion Diagnostic — %(name)s") % {"name": connection.name}},
        ],
        "header_title": _("Ingestion Diagnostic — %(name)s") % {"name": connection.name},
        "header_icon": "crosshairs",
        "connection": connection,
        "checklist": checklist,
        "health": health,
        "first_failing_layer_label": LAYER_LABELS.get(checklist.first_failing_layer),
        "layer_groups": layer_groups,
    }
    return render(request, "monitoring/connection_health.html", context=context)
