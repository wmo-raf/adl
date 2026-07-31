"""
Layer-2 broker and queue observations for the ingestion diagnostic.

All broker interaction for "is a worker consuming the ingestion queue, and is
work backing up?" lives behind :func:`get_ingestion_queue_health` — callers
and tests substitute that one name instead of patching kombu and the Celery
control API. The version predicates and ``UNSUPPORTED`` degradation live here
too, beside the calls they guard.

Three facts the vocabulary here is built on (measured, see issue #151):

- **Depth is not backlog.** BRPOP is destructive: reserved messages leave the
  Redis list the moment a worker prefetches them, so broker-visible depth
  undercounts by up to ``prefetch_count + concurrency``. Depth is reported as
  depth, never as "work outstanding".
- **``None`` means unknown, not down.** A wedged worker is indistinguishable
  from a dead one over the control channel, and a broker that does not answer
  must not manufacture a false outage.
- **A fragile signal outside its tested range is ``UNSUPPORTED``, never
  ``None``.** ``None`` already means "the broker did not answer"; collapsing
  a moved API into it would make layer 2 report "unknown" on a perfectly
  healthy box. The fragile signals reach past the public task API —
  ``default_channel.queue_declare(passive=True).message_count`` is an
  undocumented kombu transport attribute, the redis ``transport_options``
  keys are what bound the ~1.1 s broker-down worst case, and
  ``active()``'s ``time_start`` being wall-clock epoch is an implementation
  detail that has changed before — so each carries its own version predicate
  against the pinned stack in requirements.txt (issue #162).
"""

import importlib.metadata
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional, Tuple

from django.conf import settings
from django.utils.translation import gettext as _
from kombu import Connection
from kombu.exceptions import ChannelError

from adl.config.celery import app

from .tasks import INGESTION_QUEUE_NAME, INGESTION_TASK_NAME

logger = logging.getLogger(__name__)

# The task names that constitute ingestion work on the queue — the
# coordinator and the per-station batch it spawns
INGESTION_TASK_NAMES = frozenset({
    INGESTION_TASK_NAME,
    "adl.core.tasks.process_station_link_batch",
})

# One dedicated short-lived connection, bounded at roughly one second per
# call with no retries: worst case ~2.1 s healthy, ~1.1 s when the broker is
# unreachable. These must never go into CELERY_BROKER_TRANSPORT_OPTIONS —
# that would also reconfigure the workers' own blocking BRPOP loop.
BROKER_CONNECT_TIMEOUT_SECONDS = 1.0
BROKER_SOCKET_TIMEOUT_SECONDS = 2.0
INSPECT_TIMEOUT_SECONDS = 1.0

# A running ingestion task is judged against the connection's own interval —
# a 5-minutely and a daily connection are both judged fairly. Warn once it
# outlives one tick; call it stuck at three.
RUNNING_TASK_WARN_INTERVAL_MULTIPLE = 1
RUNNING_TASK_STUCK_INTERVAL_MULTIPLE = 3

# The broker libraries the layer-2 signals lean on. requirements.txt pins the
# exact measured set; these are the ranges the predicates vouch for
# ([min, max), compared on numeric release segments). Bumping a pin without
# re-testing and widening the range here fails
# core/tests/test_dependency_pins.py — that coupling is what stops the guard
# vouching for an untested stack.
BROKER_LIBRARIES = ("celery", "kombu", "redis")
TESTED_LIBRARY_RANGES = {
    "celery": ("5.6", "5.7"),
    "kombu": ("5.6", "5.7"),
    "redis": ("8.0", "8.1"),
}

# Which libraries each fragile signal trusts, split by the process that
# actually executes it. The queue-depth read (passive declare + the redis
# transport_options) runs in this process on kombu/redis; the
# worker-consuming signal is the celery control API driven from this
# process; the running-task ages are computed from ``time_start``, which the
# *worker* stamps — so that one is judged against the worker's own reported
# stack, cached on the connection heartbeat (see
# :func:`worker_stack_guard_message`).
SIGNAL_GUARD_LIBRARIES = {
    "queue_depth": ("kombu", "redis"),
    "worker_consuming": ("celery",),
}
WORKER_SIGNAL_GUARD_LIBRARIES = ("celery",)

# Structural backstop sentinel: an API that moved (missing attribute, changed
# shape) is UNSUPPORTED, never None — None already means "did not answer"
_MOVED_API = object()


@lru_cache(maxsize=1)
def local_library_versions():
    """
    The broker-stack versions installed in *this* process, from package
    metadata. A library whose metadata cannot be found maps to ``None`` —
    unknown, about which the predicates make no claim.
    """
    versions = {}
    for name in BROKER_LIBRARIES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def tested_range_display(name):
    """Human-readable tested range for one library, for the diagnostic page."""
    minimum, maximum = TESTED_LIBRARY_RANGES[name]
    return f"{minimum} ≤ v < {maximum}"


def _parse_version(text):
    """Leading numeric release segments of a version string, or ``None``."""
    if not text:
        return None
    parts = []
    for piece in str(text).split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or None


def version_in_tested_range(name, version):
    """
    Whether ``version`` of library ``name`` is inside the tested range.
    ``None`` when the version is unknown or unparseable — no claim either way.
    """
    parsed = _parse_version(version)
    if parsed is None:
        return None
    minimum, maximum = TESTED_LIBRARY_RANGES[name]
    return _parse_version(minimum) <= parsed < _parse_version(maximum)


def _version_guard_message(libraries, versions):
    """
    ``None`` when every named library is inside its tested range (or its
    version is unknown — absence of metadata is not evidence of drift);
    otherwise a message naming resolved-versus-tested for the drifted ones.
    """
    drifted = [
        name for name in libraries
        if version_in_tested_range(name, versions.get(name)) is False
    ]
    if not drifted:
        return None
    detail = ", ".join(
        _("%(name)s %(version)s is outside the tested range %(tested)s")
        % {"name": name, "version": versions.get(name),
           "tested": tested_range_display(name)}
        for name in drifted
    )
    return (
        _("Not evaluated — this is not the tested broker stack: %(detail)s. "
          "The signal cannot vouch for a value measured against a different "
          "stack; see the pinned versions in requirements.txt.")
        % {"detail": detail}
    )


def _moved_api_message(description):
    return (
        _("Not evaluated — the underlying library API is not the tested one: "
          "%(description)s. A library outside the pinned set is likely "
          "installed; see requirements.txt.")
        % {"description": description}
    )


def worker_stack_guard_message(worker_versions):
    """
    Guard for the running-task-age signal, whose ``time_start`` is produced
    by the *worker* process: judge the worker's own reported stack — cached
    on the connection heartbeat — not this process's.

    ``None`` (no claim) when the stack is inside the tested range or simply
    unknown: a heartbeat that has not yet reported versions is "never asked",
    not evidence of drift, and suppressing the stuck-task signal on silence
    would blind the very check layer 2 leans on.
    """
    if not isinstance(worker_versions, dict) or not worker_versions:
        return None
    return _version_guard_message(WORKER_SIGNAL_GUARD_LIBRARIES, worker_versions)


@dataclass(frozen=True)
class RunningIngestionTask:
    """One ingestion task a worker reported as currently executing."""

    task_id: Optional[str]
    name: str
    args: tuple
    # Wall-clock seconds since the worker started it (``time_start`` is epoch
    # wall clock, valid across processes). ``None`` when the worker did not
    # report a start time.
    age_seconds: Optional[float]


@dataclass(frozen=True)
class UnsupportedSignal:
    """One signal degraded to ``UNSUPPORTED``: its version predicate failed
    or its underlying API is structurally not the tested one. The message
    names resolved-versus-tested, ready to render."""

    signal: str
    message: str


@dataclass(frozen=True)
class IngestionQueueHealth:
    """
    A point-in-time observation of the ingestion queue and its workers.

    Each field is independently ``None`` when it could not be observed —
    unknown, never down. A falsy-but-not-``None`` value is a real
    observation: depth ``0`` is an empty queue, ``worker_consuming False``
    is a worker fleet that replied but has nobody on the ingestion queue,
    and ``running_tasks ()`` is an idle worker that replied.

    A signal listed in ``unsupported`` was not observed at all — its version
    predicate failed or its API moved — and its field is ``None`` for a
    different reason than "the broker did not answer". Callers must check
    :meth:`unsupported_message` before reading the field.
    """

    # Broker-visible messages on the ingestion queue. A lower bound on the
    # work outstanding, since prefetched and executing tasks are not counted.
    queue_depth: Optional[int]
    # Is any worker consuming the ingestion queue?
    worker_consuming: Optional[bool]
    running_tasks: Optional[Tuple[RunningIngestionTask, ...]]
    unsupported: Tuple[UnsupportedSignal, ...] = field(default=())

    def unsupported_message(self, signal):
        """The degradation message for one signal, or ``None`` if supported."""
        for entry in self.unsupported:
            if entry.signal == signal:
                return entry.message
        return None


def running_task_warn_after_seconds(network_connection):
    """Age at which a running ingestion task has outlived its own beat tick."""
    return RUNNING_TASK_WARN_INTERVAL_MULTIPLE * network_connection.interval * 60


def running_task_stuck_after_seconds(network_connection):
    """Age at which a running ingestion task counts as stuck, not merely slow."""
    return RUNNING_TASK_STUCK_INTERVAL_MULTIPLE * network_connection.interval * 60


def get_ingestion_queue_health():
    """
    Observe the ingestion queue over one short-lived, bounded broker
    connection. Never raises; each signal degrades on its own — to ``None``
    when the broker did not answer, to ``UNSUPPORTED`` when this process's
    broker stack is outside the tested range or an underlying API moved. A
    signal guarded out by a local version predicate is never dialled: the
    guard exists precisely because the call's behaviour off the tested stack
    is unknown. The running-task-age signal is the exception — its fragile
    value (``time_start``) is stamped by the *worker*, so its version
    predicate is per-connection and applied at the evaluator against the
    heartbeat-cached worker stack (:func:`worker_stack_guard_message`); here
    it carries only the structural backstop.
    """
    queue_depth = None
    worker_consuming = None
    running_tasks = None
    unsupported = {}

    versions = local_library_versions()
    for signal, libraries in SIGNAL_GUARD_LIBRARIES.items():
        message = _version_guard_message(libraries, versions)
        if message:
            unsupported[signal] = message

    try:
        with Connection(
                settings.CELERY_BROKER_URL,
                connect_timeout=BROKER_CONNECT_TIMEOUT_SECONDS,
                transport_options={
                    "socket_connect_timeout": BROKER_CONNECT_TIMEOUT_SECONDS,
                    "socket_timeout": BROKER_SOCKET_TIMEOUT_SECONDS,
                    "max_retries": 0,
                    "retry_on_timeout": False,
                },
        ) as connection:
            if "queue_depth" not in unsupported:
                queue_depth = _queue_depth(connection)
                if queue_depth is _MOVED_API:
                    queue_depth = None
                    unsupported["queue_depth"] = _moved_api_message(
                        _("the passive queue declare no longer reports a "
                          "message count")
                    )

            inspect = app.control.inspect(
                timeout=INSPECT_TIMEOUT_SECONDS, connection=connection
            )
            if "worker_consuming" not in unsupported:
                worker_consuming = _worker_consuming(inspect)
                if worker_consuming is _MOVED_API:
                    worker_consuming = None
                    unsupported["worker_consuming"] = _moved_api_message(
                        _("the control API no longer reports active queues "
                          "in the expected shape")
                    )
            running_tasks = _running_tasks(inspect)
            if running_tasks is _MOVED_API:
                running_tasks = None
                unsupported["running_tasks"] = _moved_api_message(
                    _("the control API no longer reports active tasks in "
                      "the expected shape")
                )
    except Exception as e:
        logger.warning("[BROKER] Could not observe the ingestion queue: %s", e)

    return IngestionQueueHealth(
        queue_depth=queue_depth,
        worker_consuming=worker_consuming,
        running_tasks=running_tasks,
        unsupported=tuple(
            UnsupportedSignal(signal, message)
            for signal, message in unsupported.items()
        ),
    )


def _queue_depth(connection):
    try:
        declared = connection.default_channel.queue_declare(
            queue=INGESTION_QUEUE_NAME, passive=True
        )
    except ChannelError as e:
        # On Redis an empty queue has no key, so a passive declare reports
        # NOT_FOUND — that is a healthy idle queue, not an unobservable one.
        # Any other channel error stays unknown: it must not manufacture a
        # false healthy depth of zero.
        if _is_not_found(e):
            return 0
        logger.warning("[BROKER] Could not read ingestion queue depth: %s", e)
        return None
    except AttributeError as e:
        # Structural backstop: default_channel or queue_declare moved — an
        # API drift, not an unanswering broker
        logger.warning("[BROKER] Queue-depth API is not the tested one: %s", e)
        return _MOVED_API
    except Exception as e:
        logger.warning("[BROKER] Could not read ingestion queue depth: %s", e)
        return None
    # message_count sums across kombu's priority-suffixed keys, which a raw
    # LLEN on the queue name would undercount
    try:
        return declared.message_count
    except AttributeError as e:
        logger.warning("[BROKER] Queue-depth API is not the tested one: %s", e)
        return _MOVED_API


def _is_not_found(channel_error):
    """
    True when a passive declare failed because the queue does not exist.

    kombu's virtual transports raise with a string ``'404'`` reply code and
    an amqp broker with an int ``404``; older paths carry only the
    ``NOT_FOUND`` reply text.
    """
    reply_code = getattr(channel_error, "reply_code", None)
    if reply_code is not None:
        return str(reply_code) == "404"
    return "NOT_FOUND" in str(channel_error)


def _worker_consuming(inspect):
    try:
        replies = inspect.active_queues()
    except AttributeError as e:
        # Structural backstop: the control API moved — API drift, not an
        # unanswering broker
        logger.warning("[BROKER] Active-queues API is not the tested one: %s", e)
        return _MOVED_API
    except Exception as e:
        logger.warning("[BROKER] Could not inspect active queues: %s", e)
        return None

    # Inspect never returns {} to mean idle — no reply at all collapses to a
    # falsy value, which is unknown, not "nobody consuming"
    if not replies:
        return None

    try:
        return any(
            queue.get("name") == INGESTION_QUEUE_NAME
            for queues in replies.values()
            for queue in (queues or [])
        )
    except (AttributeError, TypeError) as e:
        logger.warning("[BROKER] Active-queues reply is not the tested shape: %s", e)
        return _MOVED_API


def _running_tasks(inspect):
    try:
        replies = inspect.active()
    except AttributeError as e:
        # Structural backstop: the control API moved — API drift, not an
        # unanswering broker
        logger.warning("[BROKER] Active-tasks API is not the tested one: %s", e)
        return _MOVED_API
    except Exception as e:
        logger.warning("[BROKER] Could not inspect active tasks: %s", e)
        return None

    if not replies:
        return None

    now = time.time()
    running = []
    try:
        for worker_tasks in replies.values():
            for task in worker_tasks or []:
                if task.get("name") not in INGESTION_TASK_NAMES:
                    continue
                time_start = task.get("time_start")
                running.append(RunningIngestionTask(
                    task_id=task.get("id"),
                    name=task["name"],
                    args=_freeze(task.get("args") or []),
                    age_seconds=max(0.0, now - time_start) if time_start is not None else None,
                ))
    except (AttributeError, TypeError) as e:
        logger.warning("[BROKER] Active-tasks reply is not the tested shape: %s", e)
        return _MOVED_API
    return tuple(running)


def _freeze(value):
    """Recursively turn lists into tuples so the reported structure is plain and hashable."""
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value
