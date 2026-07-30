"""
Write-time failure classification.

When an ingestion or dispatch run fails, core stamps the activity log with
*what kind* of failure it was — a category from a closed vocabulary, the
diagnostic layer it implicates (4 = network path, 5 = source), and the
fully-qualified exception class. This is the trusted tier of a two-tier
design: the untrusted, read-time regex fallback lives in
``monitoring/classification.py`` and only ever runs on rows the writer did
not stamp.

Classification precedence:

1. A duck-typed ``adl_category`` / ``adl_layer`` attribute on the raised
   exception — how plugins opt in without importing anything from core
   (an import from core would break at import time against older core).
   Values are validated against the closed vocabulary, never trusted.
2. An MRO walk over :data:`EXCEPTION_TYPE_TABLE`, keyed by fully-qualified
   class name **as a string**, so core recognises third-party exception
   types without importing those libraries.
3. Decline — ``(None, None)``. A wrong stamp at write time is permanent
   and would go on to lead a headline, so an ambiguous type is left
   unclassified for the read-time tier rather than guessed at.

The category is matched on the exception's *type*, never its text: a class
is a stable versioned API and its ``str()`` is not.
"""

# The closed failure-category vocabulary, shared with the source-check
# contract. Flat, defined only here; every consumer validates against it.
FAILURE_CATEGORIES = (
    "DNS_FAILURE",
    "TCP_REFUSED",
    "TCP_TIMEOUT",
    "TLS_FAILURE",
    "AUTH_FAILED",
    "PERMISSION_DENIED",
    "PATH_NOT_FOUND",
    "PROTOCOL_ERROR",
    "UNKNOWN",
)

# The only layers a failure category may implicate: 4 = network path,
# 5 = source. The layer is stamped by the producer, not derived from the
# category — the same category can be layer 4 as a connect timeout and
# layer 5 as a read timeout.
FAILURE_LAYERS = (4, 5)

# Fully-qualified class name -> (category, layer_or_None). Walked over the
# exception's MRO, so a subclass of a known base matches the base. String
# keys mean core recognises e.g. requests' exceptions without importing
# requests.
#
# Deliberately absent, because one class covers several categories and a
# wrong write-time stamp is permanent:
# - ftplib.error_perm      (530 bad password / 550 forbidden / 550 missing)
# - psycopg2.OperationalError  (refused / timeout / auth, one class)
# - requests.exceptions.ConnectionError  (DNS / refused / reset, one class)
# - builtins.TimeoutError  (network or not, no way to tell from the type)
EXCEPTION_TYPE_TABLE = {
    "socket.gaierror": ("DNS_FAILURE", 4),
    "builtins.ConnectionRefusedError": ("TCP_REFUSED", 4),
    "requests.exceptions.ConnectTimeout": ("TCP_TIMEOUT", 4),
    "requests.exceptions.ReadTimeout": ("TCP_TIMEOUT", 5),
    # Layer declined: a TLS error is usually handshake (layer 4) but can be
    # raised mid-read (layer 5), and the type alone cannot tell.
    "requests.exceptions.SSLError": ("TLS_FAILURE", None),
    "ssl.SSLError": ("TLS_FAILURE", None),
}


def _qualified_name(klass) -> str:
    return f"{klass.__module__}.{klass.__qualname__}"


def exception_class_name(exc) -> str:
    """The fully-qualified class name of ``exc``, e.g. ``"builtins.RuntimeError"``."""
    return _qualified_name(type(exc))


def classify_failure(exc):
    """
    Classify a caught exception into ``(category, layer)``.

    Returns a category from :data:`FAILURE_CATEGORIES` and a layer from
    :data:`FAILURE_LAYERS`, either of which may be ``None``. ``(None, None)``
    means core declines: the type is ambiguous or unknown, and the row is
    left for the read-time tier.
    """
    category = getattr(exc, "adl_category", None)
    if category in FAILURE_CATEGORIES:
        layer = getattr(exc, "adl_layer", None)
        if layer not in FAILURE_LAYERS:
            layer = None
        return category, layer

    for klass in type(exc).__mro__:
        key = _qualified_name(klass)
        if key in EXCEPTION_TYPE_TABLE:
            return EXCEPTION_TYPE_TABLE[key]

    return None, None


def stamp_failure(activity_log, exc) -> None:
    """
    Stamp an activity log with the classification of ``exc``.

    Sets ``error_category``, ``error_layer`` and ``exception_class`` on the
    (unsaved) log instance. ``exception_class`` is always recorded, so
    "core declined" stays distinguishable from "no table entry yet".
    """
    activity_log.exception_class = exception_class_name(exc)
    category, layer = classify_failure(exc)
    activity_log.error_category = category
    activity_log.error_layer = layer
