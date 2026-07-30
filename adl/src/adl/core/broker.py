"""
Layer-2 broker and queue observations for the ingestion diagnostic.

All broker interaction for "is a worker consuming the ingestion queue, and is
work backing up?" lives behind :func:`get_ingestion_queue_health` — callers
and tests substitute that one name instead of patching kombu and the Celery
control API. This is also where the version predicates and ``UNSUPPORTED``
degradation will live once the dependency pins land.

Two facts the vocabulary here is built on (measured, see issue #151):

- **Depth is not backlog.** BRPOP is destructive: reserved messages leave the
  Redis list the moment a worker prefetches them, so broker-visible depth
  undercounts by up to ``prefetch_count + concurrency``. Depth is reported as
  depth, never as "work outstanding".
- **``None`` means unknown, not down.** A wedged worker is indistinguishable
  from a dead one over the control channel, and a broker that does not answer
  must not manufacture a false outage.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from django.conf import settings
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
class IngestionQueueHealth:
    """
    A point-in-time observation of the ingestion queue and its workers.

    Each field is independently ``None`` when it could not be observed —
    unknown, never down. A falsy-but-not-``None`` value is a real
    observation: depth ``0`` is an empty queue, ``worker_consuming False``
    is a worker fleet that replied but has nobody on the ingestion queue,
    and ``running_tasks ()`` is an idle worker that replied.
    """

    # Broker-visible messages on the ingestion queue. A lower bound on the
    # work outstanding, since prefetched and executing tasks are not counted.
    queue_depth: Optional[int]
    # Is any worker consuming the ingestion queue?
    worker_consuming: Optional[bool]
    running_tasks: Optional[Tuple[RunningIngestionTask, ...]]


def running_task_warn_after_seconds(network_connection):
    """Age at which a running ingestion task has outlived its own beat tick."""
    return RUNNING_TASK_WARN_INTERVAL_MULTIPLE * network_connection.interval * 60


def running_task_stuck_after_seconds(network_connection):
    """Age at which a running ingestion task counts as stuck, not merely slow."""
    return RUNNING_TASK_STUCK_INTERVAL_MULTIPLE * network_connection.interval * 60


def get_ingestion_queue_health():
    """
    Observe the ingestion queue over one short-lived, bounded broker
    connection. Never raises; each signal degrades to ``None`` on its own.
    """
    queue_depth = None
    worker_consuming = None
    running_tasks = None

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
            queue_depth = _queue_depth(connection)

            inspect = app.control.inspect(
                timeout=INSPECT_TIMEOUT_SECONDS, connection=connection
            )
            worker_consuming = _worker_consuming(inspect)
            running_tasks = _running_tasks(inspect)
    except Exception as e:
        logger.warning("[BROKER] Could not observe the ingestion queue: %s", e)

    return IngestionQueueHealth(
        queue_depth=queue_depth,
        worker_consuming=worker_consuming,
        running_tasks=running_tasks,
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
    except Exception as e:
        logger.warning("[BROKER] Could not read ingestion queue depth: %s", e)
        return None
    # message_count sums across kombu's priority-suffixed keys, which a raw
    # LLEN on the queue name would undercount
    return declared.message_count


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
    except Exception as e:
        logger.warning("[BROKER] Could not inspect active queues: %s", e)
        return None

    # Inspect never returns {} to mean idle — no reply at all collapses to a
    # falsy value, which is unknown, not "nobody consuming"
    if not replies:
        return None

    return any(
        queue.get("name") == INGESTION_QUEUE_NAME
        for queues in replies.values()
        for queue in (queues or [])
    )


def _running_tasks(inspect):
    try:
        replies = inspect.active()
    except Exception as e:
        logger.warning("[BROKER] Could not inspect active tasks: %s", e)
        return None

    if not replies:
        return None

    now = time.time()
    running = []
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
    return tuple(running)


def _freeze(value):
    """Recursively turn lists into tuples so the reported structure is plain and hashable."""
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value
