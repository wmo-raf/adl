"""
The wall-clock bound and the press budget shared by every on-demand probe.

Both directions of the system dial partner hosts from the web process on an
operator's button press — the ingestion diagnostic's source probe
(:mod:`adl.core.source_checks`) and the dispatch channel's connection test
(:mod:`adl.core.dispatch_checks`) — and both call code that lives in an
independently-versioned plugin repo. The base-class docstrings ask those
implementations for a short, bounded check; nothing on the far side of a
plugin boundary makes that true. A plugin that forgets ``timeout=`` does not
return a bad verdict, it wedges a web worker.

So the bound is core's, not the implementation's, and it lives here rather
than on either side: nothing about a wall clock is ingestion-specific, and
a private cross-import between the two check modules would make one of them
the de facto home of a shared primitive.

The discipline that must not regress is one line of *absence*.
:func:`bounded_executor` deliberately shuts its executor down with
``wait=False`` and is **not** implemented as ``with ThreadPoolExecutor(...)``:
``with``-exit joins abandoned worker threads, which would let a stuck plugin
call outlive the bound this module promises. The timed-out worker is
abandoned to finish on its own.

SIGALRM was considered and rejected: it only fires on the main thread of a
POSIX process, and this repo runs under Daphne.

The press budget lives here for the same reason. The wall clock bounds one
press; nothing bounds ten of them, so :func:`claim_probe_cooldown` and
:func:`read_probe_claim` give both buttons one claim-before-you-dial
discipline. What a press inside the cooldown is *told* stays with each side,
which has its own history to report from.
"""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from datetime import datetime

from django.core.cache import cache

# One probe may take at most this long, wall clock. Both sides already have
# the same two-level shape — a ~10 s contract asked of implementations, and
# a core wall above it — and the same number is used for both, so the worst
# case an operator can experience is identical whichever button they press.
PROBE_WALL_CLOCK_SECONDS = 15

# One probe per target per minute. The wall clock bounds a single press;
# nothing bounds ten of them, and a dead host would otherwise spawn a thread
# per click. A cooldown claimed before the probe fires closes that without
# the cross-target starvation a shared fixed thread pool would introduce.
PROBE_COOLDOWN_SECONDS = 60


class ProbeTimeout(Exception):
    """The bound expired before the probed call returned.

    Its own type rather than the executor's ``TimeoutError``: since Python
    3.11 ``concurrent.futures.TimeoutError`` **is** the builtin
    ``TimeoutError``, so catching that would silently also catch a probe
    that failed fast with a socket timeout of its own and report it as
    "did not complete within the budget" — a false statement about a call
    that did complete.
    """


def _capture(fn):
    """Run ``fn`` and box its outcome, so the worker never completes
    exceptionally.

    This is what keeps :class:`ProbeTimeout` unambiguous. ``Future.result()``
    re-raises whatever the call raised, and since Python 3.11 the executor's
    own ``TimeoutError`` is the builtin one — so a callee that failed fast
    with its own socket timeout would be indistinguishable from an expired
    wait. Boxed, the only exception ``result()`` can raise is the expiry.
    """
    try:
        return True, fn()
    except BaseException as e:  # noqa: BLE001 — re-raised verbatim below
        return False, e


def _submit_bounded(executor, fn, timeout_seconds):
    """Submit ``fn`` to ``executor`` and wait no longer than the budget.

    Raises :class:`ProbeTimeout` if the budget expires first, and whatever
    ``fn`` raised otherwise. The floor keeps an already-spent budget from
    being read as "wait forever". The abandoned worker is left to finish on
    its own.
    """
    future = executor.submit(_capture, fn)
    try:
        succeeded, outcome = future.result(timeout=max(timeout_seconds, 0.001))
    except FutureTimeoutError as e:
        raise ProbeTimeout() from e

    if succeeded:
        return outcome
    raise outcome


@contextmanager
def bounded_executor(max_workers):
    """
    Yield a ``bounded_call(fn, timeout_seconds)`` callable backed by a
    private thread pool, for probes that chain several steps against one
    shared deadline. Each call raises :class:`ProbeTimeout` on expiry.

    The pool is shut down with ``wait=False``: a timed-out worker is
    abandoned, never joined, so no step can outlive the budget it was given.
    A bare ``ThreadPoolExecutor`` is not yielded, so no caller can
    accidentally join it.
    """
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        yield lambda fn, timeout_seconds: _submit_bounded(executor, fn, timeout_seconds)
    finally:
        executor.shutdown(wait=False)


def run_bounded(fn, timeout_seconds):
    """Run ``fn`` under a hard wall clock of ``timeout_seconds``.

    Raises :class:`ProbeTimeout` on expiry, leaving the abandoned worker to
    finish on its own. For a single call; use :func:`bounded_executor` where
    several steps share one deadline.
    """
    with bounded_executor(1) as bounded_call:
        return bounded_call(fn, timeout_seconds)


def claim_probe_cooldown(key, now):
    """
    Claim ``key``'s cooldown for this press, returning True when the claim
    is ours and the probe may fire.

    Atomic, and taken **before** the probe: the TTL is never extended on
    completion and never released early, including when the probe raises,
    since a crashed probe still dialled the host. That is what makes a
    press inside the cooldown answerable with a message rather than a
    second thread against a dead host.
    """
    return cache.add(key, now.isoformat(), timeout=PROBE_COOLDOWN_SECONDS)


def read_probe_claim(key):
    """The time the live claim on ``key`` was taken, or ``None`` when there
    is none or it is unreadable — a claim is a cache value with a TTL, so a
    caller must never depend on getting one back."""
    try:
        return datetime.fromisoformat(cache.get(key))
    except (TypeError, ValueError):
        return None
