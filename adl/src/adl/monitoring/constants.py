from django.db import models
from django.utils.translation import gettext_lazy as _

NETWORK_PLUGIN_TASK_NAME = "adl.core.tasks.run_network_plugin"
NETWORK_DISPATCH_TASK_NAME = "adl.core.tasks.perform_channel_dispatch"


class CheckState(models.TextChoices):
    """
    The full reporting vocabulary of the ingestion diagnostic — every
    per-check state and every stored headline status draws from this one
    definition.

    Only ``OK``/``WARNING``/``FAILED`` are verdicts about severity; the other
    five are statements of epistemic status (what the diagnostic could or
    could not have observed) and must render grey, distinguished by wording.
    """

    OK = "OK", _("OK")
    WARNING = "WARNING", _("Warning")
    FAILED = "FAILED", _("Failed")
    # A prior failure makes this check meaningless — the diagnostic never
    # claims to know something it could not have observed
    SKIPPED = "SKIPPED", _("Skipped")
    # The observation exists but is older than its freshness window; the
    # resting state of the on-demand layers 4-5
    STALE = "STALE", _("Stale")
    # The plugin does not implement this contract, or the underlying library
    # API is not the tested one
    UNSUPPORTED = "UNSUPPORTED", _("Unsupported")
    DISABLED = "DISABLED", _("Disabled")
    MISCONFIGURED = "MISCONFIGURED", _("Misconfigured")


# The six pipeline layers, in the order a failure propagates. Stable string
# identifiers, never ordinals — splitting or reordering a layer later must
# not silently rewrite the meaning of stored history.
LAYER_SCHEDULER = "scheduler"
LAYER_WORKER = "worker"
LAYER_LOCKS = "locks"
LAYER_NETWORK = "network"
LAYER_SOURCE = "source"
LAYER_DATA = "data"

# Probe steps stamp their layer as the classification ints (4 = network
# path, 5 = source); stored rows carry the stable string identifiers
PROBE_LAYER_IDS = {
    4: LAYER_NETWORK,
    5: LAYER_SOURCE,
}

# Provenance of the single evidence slot each external layer holds: who
# produced the winning observation. INTERNAL is core's own trusted record
# (a scheduled run, or a write-time-stamped failure); LOG_CLASSIFICATION is
# the read-time text-rule fallback over unstamped rows.
PROVENANCE_INTERNAL = "INTERNAL"
PROVENANCE_PROBE = "PROBE"
PROVENANCE_LOG_CLASSIFICATION = "LOG_CLASSIFICATION"

PROVENANCE_LABELS = {
    PROVENANCE_INTERNAL: _("scheduled-run evidence"),
    PROVENANCE_PROBE: _("on-demand probe"),
    PROVENANCE_LOG_CLASSIFICATION: _("classified from the run log"),
}

LAYER_LABELS = {
    LAYER_SCHEDULER: _("Scheduler"),
    LAYER_WORKER: _("Worker & queue"),
    LAYER_LOCKS: _("Station locks"),
    LAYER_NETWORK: _("Network path"),
    LAYER_SOURCE: _("Source"),
    LAYER_DATA: _("Data"),
}
