"""
Per-run logs: what a worker was doing during one ingestion or dispatch run,
kept beside the run's activity row so it can be read without server access.

Every Python log record emitted while a run scope is open — core, the plugin,
its decoder and client libraries — goes to that run's log. Plugins need no
changes: most log through plain module loggers, so capturing only
:class:`~adl.core.logging.TaskLogger` would show almost nothing from them.

Scoping is by :mod:`contextvars`, so a record lands in the run whose code
emitted it. Scopes nest: a station run inside a batch takes its own lines,
and the batch keeps only what is logged between stations. Records emitted on
other threads (paramiko's transport thread, for one) are not captured.

The stored log is bounded — the first :data:`HEAD_LINES` and the last
:data:`TAIL_LINES` lines with an omission marker between them — because when
a run dies it is the last lines that say where. It is written to the
database at most every :data:`FLUSH_INTERVAL_SECONDS` and once more when the
scope closes, so a run killed outright loses at most that interval. Each line
is also pushed live on the station run's SSE channel.
"""

import contextvars
import logging
import time
import traceback
from collections import deque
from contextlib import contextmanager

from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone as dj_timezone

from .redaction import redact_secrets

logger = logging.getLogger(__name__)

HEAD_LINES = 200
TAIL_LINES = 200
FLUSH_INTERVAL_SECONDS = 2.0
MIN_LEVEL = logging.INFO
MAX_LINE_CHARS = 4000

# Loggers whose records would recurse into the capture (the database write
# and the SSE push are themselves logged) or are noise in a run's story
EXCLUDED_LOGGERS = (
    "django.db.backends",
    "django_eventstream",
    "django_tasks",
    __name__,
)

_current_sink = contextvars.ContextVar("adl_run_log_sink", default=None)
_handler = None


def activity_channel(activity_log_id):
    """The SSE channel a run's lines are pushed on."""
    return f"activity-{activity_log_id}"


class RunLogBuffer:
    """
    The first ``head`` lines, then the most recent ``tail``, counting what
    falls out between them. Pure: no I/O, so the bounding rule is testable on
    its own.
    """

    def __init__(self, head=HEAD_LINES, tail=TAIL_LINES):
        self.head_limit = head
        self.head = []
        self.tail = deque(maxlen=tail)
        self.omitted = 0

    def add(self, line):
        if len(self.head) < self.head_limit:
            self.head.append(line)
            return
        if self.tail.maxlen == 0:
            self.omitted += 1
            return
        if len(self.tail) == self.tail.maxlen:
            self.omitted += 1
        self.tail.append(line)

    def snapshot(self):
        lines = list(self.head)
        if self.omitted:
            lines.append({"omitted": self.omitted})
        lines.extend(self.tail)
        return lines


def format_record(record):
    """One stored line for a log record, redacted, tracebacks included."""
    try:
        message = record.getMessage()
    except Exception:
        message = str(record.msg)

    if record.exc_info:
        message = f"{message}\n{''.join(traceback.format_exception(*record.exc_info)).rstrip()}"

    message = redact_secrets(message)
    if len(message) > MAX_LINE_CHARS:
        message = message[:MAX_LINE_CHARS] + " …[truncated]"

    return {
        "t": dj_timezone.now().isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "msg": message,
    }


class RunLogSink:
    """
    One run's log: a bounded buffer, persisted through ``persist(lines)`` at
    most every ``interval`` seconds, and pushed live on ``channel``.
    """

    def __init__(self, persist, channel=None, interval=None,
                 clock=time.monotonic, head=HEAD_LINES, tail=TAIL_LINES):
        self.persist = persist
        self.channel = channel
        self.interval = FLUSH_INTERVAL_SECONDS if interval is None else interval
        self.clock = clock
        self.buffer = RunLogBuffer(head=head, tail=tail)
        self.dirty = False
        self.busy = False
        self.last_flush = clock()

    def add(self, line):
        self.buffer.add(line)
        self.dirty = True
        self._push("log", line)
        if self.clock() - self.last_flush >= self.interval:
            self.flush()

    def flush(self):
        self.last_flush = self.clock()
        if not self.dirty:
            return
        self.dirty = False
        try:
            self.persist(self.buffer.snapshot())
        except SoftTimeLimitExceeded:
            # The run's time budget, arriving while a line was being stored.
            # Swallowed here it would never stop the run.
            raise
        except Exception as e:
            # A log that cannot be stored must never fail the run it describes
            logger.debug("Could not persist run log: %s", e)

    def close(self, **end):
        self.flush()
        self._push("end", end)

    def _push(self, event, data):
        if not self.channel:
            return
        try:
            from django_eventstream import send_event
            send_event(self.channel, event, data)
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            pass


class RunLogHandler(logging.Handler):
    """Routes records to the sink of the run scope open in this context."""

    def emit(self, record):
        sink = _current_sink.get()
        if sink is None or sink.busy:
            return
        if record.levelno < MIN_LEVEL or record.name.startswith(EXCLUDED_LOGGERS):
            return
        sink.busy = True
        try:
            sink.add(format_record(record))
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            pass
        finally:
            sink.busy = False


def current_task_id():
    """The id of the Celery task running this code, or ``None`` outside one."""
    try:
        from celery import current_task
        return getattr(getattr(current_task, "request", None), "id", None) if current_task else None
    except Exception:
        return None


def install():
    """Attach the handler to the root logger, once per process."""
    global _handler
    if _handler is None:
        _handler = RunLogHandler(level=MIN_LEVEL)
        logging.getLogger().addHandler(_handler)
    return _handler


@contextmanager
def capture(sink):
    """Route this context's log records to ``sink`` until the block exits."""
    install()
    token = _current_sink.set(sink)
    try:
        yield sink
    finally:
        _current_sink.reset(token)


@contextmanager
def capture_activity_log(activity_log):
    """
    Capture a run's log onto its :class:`StationLinkActivityLog` row.

    Flushes write ``log_lines`` with a targeted UPDATE, and also onto the
    instance, so the run's own full ``save()`` of the row keeps the latest
    snapshot rather than overwriting it. The final flush happens when the
    block exits — wrap the run so that is after its last save.
    """
    from adl.monitoring.models import StationLinkActivityLog

    def persist(lines):
        activity_log.log_lines = lines
        StationLinkActivityLog.objects.filter(pk=activity_log.pk).update(log_lines=lines)

    sink = RunLogSink(persist, channel=activity_channel(activity_log.pk))
    try:
        with capture(sink):
            yield sink
    finally:
        sink.close(status=activity_log.status)


@contextmanager
def capture_batch_log(task_id, network_connection=None):
    """
    Capture the lines a batch task logs outside any station run onto an
    :class:`~adl.monitoring.models.IngestionBatchLog` keyed by ``task_id``.
    Without a task id there is nothing to key it by, and nothing is stored.
    """
    if not task_id:
        yield None
        return

    from adl.monitoring.models import IngestionBatchLog

    batch_log, _ = IngestionBatchLog.objects.get_or_create(
        task_id=task_id,
        defaults={
            "time": dj_timezone.now(),
            "network_connection_id": getattr(network_connection, "pk", None),
        },
    )

    def persist(lines):
        IngestionBatchLog.objects.filter(pk=batch_log.pk).update(log_lines=lines)

    # Stored only, not streamed: a batch's own lines are few, and it is the
    # station runs inside it that are followed live
    sink = RunLogSink(persist)
    try:
        with capture(sink):
            yield sink
    finally:
        sink.close()
