"""
The one bounded broker connection every in-process broker call goes through.

Celery's defaults are built for workers, not for request threads. Left alone
they hang the caller (measured in issue #151, re-confirmed in #166):

- The app's **default connection** retries on failure —
  ``broker_connection_timeout=4`` actually costs ~6 s against a refused
  broker via retry backoff, and the redis transport's ``socket_timeout`` and
  ``socket_connect_timeout`` both default to ``None``, so a *blackholed*
  broker blocks for ~75 s on macOS and ~130 s on Linux.
- **Every ``inspect()`` call burns its full timeout** unless bounded.
  ``kombu.pidbox.Mailbox._collect`` loops ``for i in limit and range(limit)
  or count()`` and only exits on ``socket.timeout``, and kombu sets a limit
  only when ``destination`` is given. So the default ``timeout=1.0`` is a
  one-second-per-call *floor*, paid on every healthy request.

The fix is not to widen Celery's config: ``CELERY_BROKER_TRANSPORT_OPTIONS``
is shared with the workers, and socket timeouts there would reconfigure their
own ``BRPOP`` consume loop, which is *supposed* to block. Bounds belong on a
dedicated short-lived connection, which is what this module hands out. With
them the whole layer-2 observation measured 1.09 s healthy, 0.07 s against a
refused broker and 1.06 s against a blackholed one.

Two contract notes for callers, both easy to get backwards:

- ``inspect()`` returning a falsy reply means **no worker answered** —
  unknown. Idle is ``{'worker@host': []}``; there is no empty-dict reply.
  Rendering silence as "nothing is running" invents an all-clear.
- **The per-call timeout is a floor, not a ceiling, and that is deliberate.**
  ``limit`` would collapse it — ``active_queues()`` drops from 0.51 s to
  0.01 s — but it returns only the *first* reply, so on a deployment that
  has scaled its worker beyond one replica it silently reports one worker
  and misses the rest, including a stuck task on a worker that did not
  answer first. A truncated reply is indistinguishable from a complete one.
  So no caller here passes a limit, and this module does not offer one:
  correctness over the second (see the research's "Why not ``limit=1``?").
"""

import logging

from django.conf import settings
from kombu import Connection

from adl.config.celery import app

logger = logging.getLogger(__name__)

# Roughly one second per call, no retries: ~2.1 s worst case on a healthy
# box, ~1.1 s when the broker is unreachable. Never move these into
# CELERY_BROKER_TRANSPORT_OPTIONS — see the module docstring.
BROKER_CONNECT_TIMEOUT_SECONDS = 1.0
BROKER_SOCKET_TIMEOUT_SECONDS = 2.0
INSPECT_TIMEOUT_SECONDS = 1.0


def bounded_broker_connection():
    """
    A short-lived ``kombu.Connection`` bounded on connect and on socket I/O,
    with retries off. Use as a context manager, and reuse the one connection
    for every call in a single observation.
    """
    return Connection(
        settings.CELERY_BROKER_URL,
        connect_timeout=BROKER_CONNECT_TIMEOUT_SECONDS,
        transport_options={
            "socket_connect_timeout": BROKER_CONNECT_TIMEOUT_SECONDS,
            "socket_timeout": BROKER_SOCKET_TIMEOUT_SECONDS,
            "max_retries": 0,
            "retry_on_timeout": False,
        },
    )


def bounded_inspect(connection, timeout=INSPECT_TIMEOUT_SECONDS):
    """
    A Celery ``Inspect`` bound to ``connection`` and to ``timeout``.

    ``timeout`` is a per-drain idle timeout, not a wall-clock deadline: each
    reply resets it, so a fleet answering steadily can exceed it. With no
    ``limit`` (see the module docstring) it is also the *floor* — the call
    always waits it out — so callers whose workers can legitimately be slow
    to answer should raise it rather than read a timeout as silence.
    """
    return app.control.inspect(timeout=timeout, connection=connection)
