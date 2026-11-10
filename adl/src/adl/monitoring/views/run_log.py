"""
Reading per-run logs (see :mod:`adl.core.run_log`) from the admin.

A station run's log is fetched when its row is expanded on the station-link
monitoring page, rather than rendered with the listing: a page of twenty
runs could otherwise carry thousands of lines nobody opened. A run still in
progress also gets its live SSE channel, so the page can follow it.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext as _

from adl.core.run_log import activity_channel

from ..models import IngestionBatchLog, StationLinkActivityLog


def activity_log_lines(request, log_id):
    activity = get_object_or_404(
        StationLinkActivityLog.objects.only("id", "status", "task_id", "log_lines"),
        id=log_id,
    )
    running = activity.status == StationLinkActivityLog.ActivityStatus.STARTED

    batch_url = None
    if activity.task_id and IngestionBatchLog.objects.filter(task_id=activity.task_id).exists():
        batch_url = reverse("batch_log", args=[activity.task_id])

    return JsonResponse({
        "lines": activity.log_lines or [],
        "captured": activity.log_lines is not None,
        "status": activity.status,
        "running": running,
        "channel": activity_channel(activity.id) if running else None,
        "task_id": activity.task_id,
        "batch_url": batch_url,
    })


def batch_log(request, task_id):
    batch = get_object_or_404(
        IngestionBatchLog.objects.select_related("network_connection"), task_id=task_id,
    )
    runs = (
        StationLinkActivityLog.objects.filter(task_id=task_id)
        .defer("log_lines")
        .select_related("station_link")
        .order_by("time")
    )

    label = _("Batch log %(task_id)s") % {"task_id": task_id}
    context = {
        "breadcrumbs_items": [
            {"url": reverse("wagtailadmin_home"), "label": _("Home")},
            {"url": None, "label": label},
        ],
        "header_title": label,
        "header_icon": "list-ul",
        "batch": batch,
        "lines": batch.log_lines or [],
        "runs": runs,
    }
    return render(request, "monitoring/batch_log.html", context)
