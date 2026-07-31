# Celery worker and queue health: what ADL can trust

Research findings for [issue #151](https://github.com/wmo-raf/adl/issues/151).
Input to **layer 2 ("Worker")** of the per-connection ingestion diagnostic.

**Status:** research only. No production code changed by this note.

---

## Where this file lives

The repo has no `docs/research/` convention. `docs/` is a published Sphinx tree
(`docs/conf.py`, `docs/index.md` toctree) aimed at NMHS operators, and dropping an
engineering research note in there would put it in the user-facing manual. The
existing convention for internal engineering reference material is
`.claude/docs/` (see `.claude/docs/architectural_patterns.md`, linked from
`CLAUDE.md`), so this note goes to `.claude/docs/research/`.

---

## Question

What can ADL reliably observe about the health of the `adl` ingestion queue and its
workers, and what are the failure modes of each observation?

Layer 2 must answer three things when a connection goes silent:

1. Is a worker consuming the `adl` queue at all?
2. How deep is the backlog?
3. Is a `process_station_link_batch` task stuck long enough to be starving the queue?

---

## Method and version pin

Two evidence streams, both primary:

- **Source reading** against the exact package versions a fresh ADL image resolves to.
- **A live experiment**: local Redis + a real Celery worker (`-Q adl -n adl-worker@test
  --concurrency 2`, matching ADL's production launch line), driven by probe scripts that
  measured wall-clock cost and return values under healthy, busy, wedged, dead-broker and
  blackholed-broker conditions. Every timing quoted as "measured" below comes from that run.

**Version pin — with a caveat that matters.** `adl/requirements.txt` does **not** pin
Celery, Kombu or redis-py at all. Celery arrives transitively via
`django-celery-beat==2.9.0`, whose metadata requires `celery<6.0,>=5.2.3`
(verified from the wheel's `METADATA`). So the version is *whatever pip resolves at
image build time* and drifts between installations. Resolving today gives:

| Package | Resolved |
|---|---|
| celery | 5.6.3 |
| kombu | 5.6.2 |
| redis-py | 8.0.1 |

Source line numbers below are from those versions. The behaviours that matter here are
stable across the 5.x line: `kombu/pidbox.py` is byte-identical between kombu 5.3.7 and
5.5.4, and `celery/app/control.py` differs between Celery 5.4.0 and 5.5.3 by one unrelated
line in `revoke_by_stamped_headers`. The one real 5.x behaviour change found is in
`kombu.transport.redis.Channel._do_restore_message` (§ Queue depth).

> **Recommendation (out of scope for layer 2, but found here):** pin `celery`, `kombu` and
> `redis` explicitly in `adl/requirements.txt`. A diagnostic that reasons about broker
> internals should not be running against an unpinned dependency across 26+ installations.

---

## ADL's actual topology (the ground this stands on)

From `docker-entrypoint.sh` and `adl/src/adl/config/settings/base.py`:

- Three queues, three dedicated worker containers
  (`docker-entrypoint.sh:143-151`):

  | Container | Command | Queue | Node name | Default concurrency |
  |---|---|---|---|---|
  | `adl_celery_worker_default` | `celery-worker-default` | `celery` | `default-worker@%h` | 1 |
  | `adl_celery_worker_adl` | `celery-worker-adl` | `adl` | `adl-worker@%h` | 2 |
  | `adl_celery_worker_dispatch` | `celery-worker-dispatch` | `dispatch` | `dispatch-worker@%h` | 2 |

- **The node-name prefix is an ADL-controlled contract.** `-n adl-worker@%h` means every
  ingestion worker's node name starts with `adl-worker@`. This is the single most useful
  asset layer 2 has, because it lets one broadcast identify ingestion workers without a
  second round trip. `%h` expands to the container hostname, which is *not* stable
  (Docker assigns the container ID), so the full node name cannot be hard-coded — only
  the prefix can be matched.

- Routing (`base.py:304-310`): `run_network_plugin` and `process_station_link_batch` →
  `adl`; the three dispatch tasks → `dispatch`.

- **No pool type is specified**, so the default **prefork** pool is used
  (`start_celery_worker` in `docker-entrypoint.sh:60-69` passes only `--concurrency` and
  `-l`). This matters enormously for `ping` (§ Worker liveness).

- **ADL sets none of** `worker_prefetch_multiplier`, `task_acks_late`,
  `broker_transport_options`, or `broker_connection_timeout`. Celery defaults apply
  (`celery/app/defaults.py`):

  | Setting | Default | Consequence for ADL's `adl` worker |
  |---|---|---|
  | `worker_prefetch_multiplier` | `4` (L348) | prefetch count = 4 × 2 = **8** |
  | `task_acks_late` | `False` (L265) | message acked when handed to a child, not on completion |
  | `broker_connection_timeout` | `4.0` (L89) | bounds connection *retries*, not socket I/O |
  | `broker_pool_limit` | `10` (L99) | `pool.acquire(block=True)` — blocks forever if exhausted |

  Measured `prefetch_count` reported by `stats()` on a 2-concurrency worker: **8**. Confirms.

- **Redis db 0 is shared.** `REDIS_URL` (db 0) is used simultaneously as
  `CELERY_BROKER_URL`, the `django-redis` cache `LOCATION`, and `EVENTSTREAM_REDIS`
  (`base.py:288-330`). Any diagnostic must address specific keys; `KEYS *`, `DBSIZE` and
  `FLUSHDB` are all off-limits.

---

## Findings per signal

### 1. `inspect().ping()` — **trustworthy, with a hard scope limit**

**What it reports.** The entire worker-side handler is
`celery/worker/control.py`:

```python
@inspect_command(default_timeout=0.2)
def ping(state, **kwargs):
    """Ping worker(s)."""
    return ok('pong')
```

Zero I/O, zero locks, no pool interaction. It proves exactly one thing: **the pidbox
consumer is being serviced**.

**Who services it.** `celery/worker/consumer/control.py:24-26`:

```python
self.is_green = c.pool is not None and c.pool.is_green
self.box = (pidbox.gPidbox if self.is_green else pidbox.Pidbox)(c)
```

Under prefork (ADL's case), `Pidbox` registers a consumer on the Consumer's connection,
drained by `asynloop` in the **MainProcess**. Tasks execute in forked children. So a
prefork worker whose children are all blocked answers `pong` instantly.

**Measured.** With both pool children 24.8 s into a 30 s blocking sleep:

```
ping while children busy               0.01s  {'adl-worker@test': {'ok': 'pong'}}
stats while children busy              0.00s  True
active_queues limit=1                  0.00s  ['adl']
```

**Verdict: trustworthy as a MainProcess-liveness signal, and useless as a
throughput signal.** A fully wedged worker — every child stuck on a blocking socket,
ingestion throughput zero — passes `ping`. Layer 2 must never present a green `ping`
as "ingestion is working". Celery's own docs say this outright for the solo pool
(`docs/userguide/workers.rst`: *"any task executing will block any waiting control
command"*), and ADL is not on solo — but the inverse trap applies: on prefork, ping is
*too* forgiving.

### 2. `inspect().active()` — **trustworthy, and the only signal that answers Q3**

Worker handler (`celery/worker/control.py`):

```python
@inspect_command(alias='dump_active')
def active(state, safe=False, **kwargs):
    """List of tasks currently being executed."""
    return [request.info(safe=safe)
            for request in state.tset(worker_state.active_requests)]
```

`Request.info` (`celery/worker/request.py:674-686`) returns `id`, `name`, `args`,
`kwargs`, `type`, `hostname`, `time_start`, `acknowledged`, `delivery_info`, `worker_pid`.

**`time_start` is wall-clock epoch seconds, not a monotonic value.**
`celery/worker/request.py:519`:

```python
# Convert monotonic time_accepted to absolute time
self.time_start = time() - (monotonic() - time_accepted)
```

This is the load-bearing fact for Q3: `time.time() - task["time_start"]` computed in the
Django process is a valid task age, because both sides are on `time.time()`. Measured
against a task known to have been running 24.8 s, the arithmetic agreed to 0.1 s. The
only exposure is clock skew between the Django container and the worker container; under
`docker-compose` on one host both read the same kernel clock, so skew is zero. Across
split hosts it is not, and a large negative age is the tell.

**Two traps.**

- **`active()` leaks task arguments by default.** `Inspect.active(safe=None)` → falsy →
  worker uses `safe=False` → deserialized `args`/`kwargs` verbatim over the broker.
  For `process_station_link_batch` the args are `(network_id, [station_link_ids])` —
  harmless, and in fact needed for per-connection attribution. But layer 2 should be
  aware it is opting into payload transfer, and should not extend the pattern to tasks
  with credentials in args.
- **`reserved()` accepts `safe` and silently discards it** —
  `celery/app/control.py`: `def reserved(self, safe=None): return self._request('reserved')`.

**Verdict: trustworthy.** This is the signal that detects a stuck batch.

### 3. `inspect().reserved()` — **trustworthy but frequently misread**

Worker handler:

```python
@inspect_command()
def reserved(state, **kwargs):
    """List of currently reserved tasks, not including scheduled/active."""
    reserved_tasks = (
        state.tset(worker_state.reserved_requests) -
        state.tset(worker_state.active_requests)
    )
```

Prefetched into worker memory, **not yet started**, active explicitly subtracted.

**The misreading:** treating `reserved()` as the backlog. It is only the part of the
backlog a *live, replying* worker has already pulled in. If the worker is dead there is
no backlog reported at all, and if the worker is healthy it caps at `prefetch_count`.

**Verdict: trustworthy as "work held in worker memory", misleading as "backlog".**
Its real value is as the second term in the true-depth sum (§ Queue depth).

### 4. `inspect().scheduled()` — **irrelevant to ADL, and a trap if used**

Returns the worker's in-memory ETA/countdown heap
(`state.consumer.timer.schedule.queue`). ADL never uses `countdown=` or `eta=`:
`process_station_link_batch.apply_async(args=[...], queue='adl')` and
`dispatch_station.apply_async(...)` are both immediate. Beat-driven periodic tasks are
dispatched by `django_celery_beat` at fire time and are never "scheduled" in this sense.

Measured on a worker with 20 queued tasks: `scheduled()` → `{'adl-worker@test': []}`.

**Verdict: always empty in ADL. Do not include it — a permanently-empty panel row
trains operators to ignore the panel.**

### 5. `inspect().stats()` — **trustworthy but the most expensive call; mostly redundant**

`celery/worker/worker.py:326-334`:

```python
def stats(self):
    info = self.info()
    info.update(self.blueprint.info(self))
    info.update(self.consumer.blueprint.info(self.consumer))
    try:
        info['rusage'] = self.rusage()
    except NotImplementedError:
        info['rusage'] = 'N/A'
    return info
```

A `getrusage(2)` call plus a walk of **two** bootstep blueprints calling `.info()` on
every step, including `Pool._get_info()` (PID list, per-child write distribution).
Measured payload for a single idle 2-concurrency worker: **1018 bytes**, keys
`['broker', 'clock', 'pid', 'pool', 'prefetch_count', 'rusage', 'total', 'uptime']`.

The only field layer 2 would actually want is `prefetch_count`, which is derivable from
`concurrency × worker_prefetch_multiplier` — both known statically from ADL's own config.

**Verdict: trustworthy but redundant.** `ping()` proves the same liveness for a fraction
of the cost. Exclude from the per-request path; it is a good "expand for detail" action.

### 6. `inspect().active_queues()` — **the only honest answer to "is a worker consuming `adl`"**

`celery/worker/control.py`:

```python
@inspect_command()
def active_queues(state):
    """List the task queues a worker is currently consuming from."""
    if state.consumer.task_consumer:
        return [dict(queue.as_dict(recurse=True))
                for queue in state.consumer.task_consumer.queues]
    return []
```

This reads the live consumer's bound queues, so it catches the misconfiguration case
(a worker running with the wrong `-Q`) that a node-name prefix match would miss.
Measured: `{'adl-worker@test': [{'name': 'adl', ...}]}`, 0.01 s with `limit=1`.

**Verdict: trustworthy, and the only signal that distinguishes "an ingestion worker
exists" from "an ingestion worker is bound to the `adl` queue".**

### 7. `None` vs `{}` — **the ticket's premise needs correcting**

The issue text says `get_active_dispatch_tasks()` "encodes the crucial distinction
between `None` (no worker replied — unknown) and `{}` (idle)". The `None` half is right.
The `{}` half is not: **Celery inspect never returns `{}` to mean idle.**

`celery/app/control.py:92-103`:

```python
def _prepare(self, reply):
    if reply:
        by_node = flatten_reply(reply)
        ...
        return by_node
```

There is no `else`. Falsy `reply` (an empty list from `Mailbox._collect`) falls off the
end → implicit `None`.

Measured, idle worker:

```
inspect(t=1.0).active()    1.03s  {'adl-worker@test': []}
```

So the three states are:

| Return | Meaning |
|---|---|
| `None` | Zero replies within the timeout — **unknown** |
| `{'adl-worker@host': []}` | Worker replied, has nothing running — **idle** |
| `{'adl-worker@host': [ ... ]}` | Worker replied with work |
| `{}` | Only reachable when a `pattern` was supplied and no responding node matched |

**Consequence for the existing code:** `get_active_dispatch_tasks()`
(`adl/src/adl/core/tasks.py:42-69`) is *behaviourally correct* — `if not active: return
None` catches only the `None` case in practice, and an idle-but-replying worker yields a
truthy `{'dispatch-worker@h': []}` which correctly reduces to `{}` "nothing running".
Only the docstring's description of `{}` is inaccurate. Layer 2 should copy the pattern
and fix the wording, not the logic.

**`None` is still overloaded.** It cannot distinguish "no worker exists", "worker exists
but was slower than the timeout", and "worker exists but its pidbox is wedged".
Celery's own CLI collapses all three (`celery/bin/control.py`: *"No nodes replied within
time constraint"*). Layer 2 must render this as **unknown**, never as **down**.

### 8. `inspect()` cost — **every call burns the full timeout unless bounded**

`kombu/pidbox.py:394-401`:

```python
try:
    with consumer:
        for i in limit and range(limit) or count():
            try:
                self.connection.drain_events(timeout=timeout)
            except socket.timeout:
                break
        return responses
finally:
    chan.after_reply_message_received(queue.name)
```

`limit=None` → falsy → **`count()`, unbounded**. The only exit is the `socket.timeout`.
The client cannot stop early because there is no registry of how many workers exist —
`kombu/pidbox.py:332-334` only sets a limit when `destination` is given:

```python
# Set reply limit to number of destinations (if specified)
if limit is None and destination:
    limit = destination and len(destination) or None
```

Celery's docs state the rationale (`docs/userguide/workers.rst`): *"Since there's no
central authority to know how many workers are available in the cluster, there's also no
way to estimate how many workers may send a reply, so the client has a configurable
timeout."*

**Measured, healthy single worker:**

```
inspect(t=1.0).ping()             1.01s
inspect(t=3.0).ping()             3.07s
inspect(t=1.0, limit=1).ping()    0.00s     <-- returns the instant the reply lands
inspect(t=0.5).active_queues()    0.51s
```

Also note `timeout` is a **per-drain idle timeout, not a wall-clock deadline** — each
`drain_events` gets a fresh budget. With many workers replying slowly, total time can far
exceed `timeout`. And a truncated result is indistinguishable from a complete one; nothing
signals that a slow worker was dropped.

**Verdict: the default `timeout=1.0` with no `limit` is a 1-second-per-call floor.**
ADL's existing `get_active_tasks_by_network()`
(`adl/src/adl/monitoring/views/__init__.py:287-305`) makes **two** unbounded inspect calls
with the default timeout, so it costs ≥ 2 s on every request even when everything is
healthy.

### 9. Queue depth — **broker-side is the only honest source, but naive `LLEN` is wrong twice**

**Where the queue lives.** `kombu/transport/redis.py`:

```python
def _put(self, queue, message, **kwargs):
    """Deliver message."""
    pri = self._get_message_priority(message, reverse=False)

    with self.conn_or_acquire() as client:
        client.lpush(self._q_for_pri(queue, pri), dumps(message))

def _q_for_pri(self, queue, pri):
    pri = self.priority(pri)
    if pri:
        return f"{queue}{self.sep}{pri}"
    return queue
```

with `sep = '\x06\x16'` and `PRIORITY_STEPS = [0, 3, 6, 9]`. For priority 0 (falsy) the
key is the queue name **verbatim** — so ADL's `adl` queue is the Redis LIST at key `adl`.
Confirmed by observation: with 20 tasks enqueued the db held exactly
`['_kombu.binding.adl', '_kombu.binding.celery.pidbox', '_kombu.binding.celeryev', 'adl',
'unacked', 'unacked_index']`.

**Is `LLEN adl` a supported contract? No — it is an implementation detail, and it is
wrong in two independent ways.**

**Wrongness 1 — priority keys.** Any message published with `priority >= 3` lands on a
suffixed key. Measured, publishing priorities 0/4/7/9 to one queue:

```
keys                : ["b'adlprio'", "b'adlprio\\x06\\x163'", "b'adlprio\\x06\\x166'", "b'adlprio\\x06\\x169'"]
naive LLEN adlprio  : 1
queue_declare depth : 4
```

A naive `LLEN` read **1** where the true depth was **4**. Today ADL never sets a priority,
so the suffixed keys are never created and `LLEN adl` happens to be exact. That is a
latent trap: the day someone adds `priority=` to an `apply_async`, or sets
`broker_transport_options={'priority_steps': ..., 'sep': ':'}`, the diagnostic silently
starts reading a fraction of the real backlog. Kombu's own `_size` sums across all steps:

```python
def _size(self, queue):
    with self.conn_or_acquire() as client:
        with client.pipeline() as pipe:
            for pri in self.priority_steps:
                pipe = pipe.llen(self._q_for_pri(queue, pri))
            sizes = pipe.execute()
            return sum(size for size in sizes
                       if isinstance(size, numbers.Integral))
```

**Use the public wrapper, not `LLEN`.** `virtual.Channel.queue_declare`
(`kombu/transport/virtual/base.py:527-538`) returns `queue_declare_ok_t(queue,
self._size(queue), 0)`, so:

```python
conn.default_channel.queue_declare(queue="adl", passive=True).message_count
```

is priority-aware, `global_keyprefix`-aware, and is the AMQP-shaped contract kombu
implements for every transport. (Equivalently `SimpleQueue.qsize()`, which is the same
call.) **Do not** use `conn.default_channel.client.llen(...)`: `.client` is the
*asynchronous* client the transport itself uses for BRPOP.

**Wrongness 2 — prefetch, and this is the one that bites today.** BRPOP is destructive:
a reserved message leaves the list at the instant the worker takes it. It reappears in
the `unacked` HASH and `unacked_index` ZSET (`redis.QoS.append`), governed by
`visibility_timeout = 3600`. With `task_acks_late=False` (ADL's default) the ack fires in
`Request.on_accepted`:

```python
self.time_start = time() - (monotonic() - time_accepted)
task_accepted(self)
if not self.task.acks_late:
    self.acknowledge()
```

so a *started* task leaves `unacked` too.

**Measured**, 20 tasks enqueued to a 2-concurrency worker (prefetch 8), sampled 3 s in:

```
LLEN adl               : 10
queue_declare depth    : 10
unacked hlen           : 8
active count           : {'adl-worker@test': 2}
reserved count         : {'adl-worker@test': 8}
```

`10 + 8 + 2 = 20`. Broker-side depth undercounted the real backlog by exactly
`reserved + active` = 10, i.e. by `prefetch_count + concurrency`.

**So neither source alone is honest:**

- `queue_declare` depth sees only **unreserved** work. With 2 concurrency it can read
  **0 while 10 batches are held in worker memory**.
- `reserved()` + `active()` see only what a **live, replying** worker holds. If no worker
  replies they report nothing, whatever the real backlog.

**True depth = `queue_declare(...).message_count` + `len(reserved)` + `len(active)`**,
and that sum is only computable when the worker replies. When it does not, broker-side
depth is a **lower bound** and must be labelled as such.

**`unacked` cannot be attributed per-queue.** `unacked_key = 'unacked'` and
`unacked_index_key = 'unacked_index'` are fixed strings, global to the Redis db, shared by
all three ADL queues (`celery`, `adl`, `dispatch`). `HLEN unacked` is a whole-broker
number. Do not present it as an `adl` backlog. It is still a useful *tie-breaker*: with
inspect silent and `HLEN unacked` non-zero and not falling, something holds messages it
is not processing.

**Version drift found.** In kombu 5.3.7 `_do_restore_message` restored to the bare queue
key regardless of priority; 5.4.0+ restores to `_q_for_pri(queue, pri)`. Another argument
for pinning kombu.

**Verdict: `queue_declare(passive=True).message_count` is trustworthy as
"unreserved work". Naive `LLEN adl` is misleading (priority keys). Treating either as
"the backlog" is misleading (prefetch).**

### 10. `queue_declare(passive=True)` on an empty queue — **raises, does not return 0**

`kombu/transport/virtual/base.py:530-535`:

```python
if passive and not self._has_queue(queue, **kwargs):
    raise ChannelError(
        'NOT_FOUND - no queue {!r} in vhost {!r}'.format(...),
        (50, 10), 'Channel.queue_declare', '404',
    )
```

and redis `_has_queue` is `any(EXISTS)` over the priority keys. Redis has no empty lists —
the key is deleted when the last element is popped. So **an empty queue is
indistinguishable from a never-used one, and both raise.**

Measured on an idle broker:

```
queue_declare passive depth   0.00s  EXC ChannelError: Channel.queue_declare: (404) NOT_FOUND - no queue 'adl' in vhost '0'
```

**Verdict: a correctness landmine.** Any implementation must catch `ChannelError` and map
it to depth `0`. Getting this wrong turns a perfectly healthy idle system into a red
diagnostic.

### 11. Broker down — **the page-hanging risk is real and measured**

`Mailbox._broadcast` reaches `self.connection.default_channel`, which calls
`_ensure_connection(timeout=self.connect_timeout)` → `retry_over_time` with
`interval_start=2, interval_step=2, max_retries=None`. The deadline is checked *after* a
failed attempt (`kombu/utils/functional.py:316-322`), so with `broker_connection_timeout=4`
the sequence is attempt@0 → sleep 2 → attempt@2 → sleep 4 → attempt@6 → `time() > end` →
raise `kombu.exceptions.OperationalError`.

**Measured, connection refused (nothing listening):**

```
refused: inspect(1.0).ping()      6.08s  EXC OperationalError: Error 61 connecting ... Connection refused.
refused: queue_declare depth      6.03s  EXC OperationalError: Error 61 connecting ... Connection refused.
```

≈ 6 s, not the 4 s the setting name suggests. Exactly as predicted from the retry loop.

**Measured, TCP blackhole** (SYN dropped, no RST — the realistic case for a frozen host,
a dropped security-group rule, or a mid-failover network):

```
blackhole: inspect(1.0).ping()   75.06s  EXC OperationalError: Timeout connecting to server
```

**75 seconds on macOS.** On Linux, with `tcp_syn_retries=6`, it is ~130 s. The cause is
kombu's redis defaults (`kombu/transport/redis.py`):

```python
socket_timeout = None
socket_connect_timeout = None
```

passed straight through `_connparams` to redis-py, which does `sock.settimeout(None)` —
block until the OS TCP stack gives up. **This is the single concrete way a diagnostic page
hangs**, and ADL is currently exposed to it: `broker_transport_options` is unset, and
`get_active_tasks_by_network()` makes two unbounded inspect calls on the request path.
Worst case today: **~150 s of gunicorn worker occupancy per page load** against a
blackholed Redis.

**Measured with bounds applied** (`connect_timeout=1.0`,
`transport_options={'socket_connect_timeout': 1.0, 'socket_timeout': 2.0, 'max_retries': 0}`):

```
bounded refused:   0.07s
bounded blackhole: 1.09s
```

75 s → 1.09 s. The fix is decisive.

**Critical caveat: do not set these globally.** `CELERY_BROKER_TRANSPORT_OPTIONS` in
`settings/base.py` would also apply to the **workers**, whose consume loop uses a blocking
`BRPOP` with a 1 s timeout. A `socket_timeout` of 1–2 s there causes spurious poll-loop
timeouts and reconnect churn. Layer 2 must build its **own short-lived
`kombu.Connection`** with bounded options and pass it in via `inspect(connection=...)`,
leaving the app's connection pool untouched.

**Verified end to end.** A probe using exactly that shape:

```python
BOUNDED = dict(
    connect_timeout=1.0,
    transport_options={
        "socket_connect_timeout": 1.0,
        "socket_timeout": 2.0,
        "max_retries": 0,
        "retry_on_timeout": False,
    },
)
with Connection(settings.CELERY_BROKER_URL, **BOUNDED) as conn:
    depth = conn.default_channel.queue_declare(queue="adl", passive=True).message_count
    insp = app.control.inspect(timeout=1.0, connection=conn)
    ...
```

measured:

| Broker state | Total elapsed | Result |
|---|---|---|
| healthy | 1.09 s | depth + ping + active all returned |
| refused | 0.07 s | `OperationalError` |
| blackholed | 1.06 s | `OperationalError` |

**Two residual unbounded-hang risks, both avoidable:**

1. `broker_pool_limit` is 10 and `connection_or_acquire` does `pool.acquire(block=True)` —
   **blocks forever** if exhausted. Using an own `Connection` sidesteps the pool entirely.
2. `Mailbox._publish` publishes with `retry=True` and an empty retry policy
   (`kombu/pidbox.py`), which routes to `Connection.ensure(max_retries=None)` whose loop
   is `for retries in count(0):  # for infinity`. Setting `max_retries: 0` in transport
   options is what closes this.

Note `broker_connection_retry` / `broker_connection_max_retries` are **irrelevant here** —
they are read only by the worker's own consumer, never by `Control.broadcast`.

### 12. Worker heartbeats / the event stream — **available for free, but not for layer 2**

`worker-online` / `worker-heartbeat` / `worker-offline` are emitted by an unmodified
worker with no flags. `celery/worker/consumer/events.py`:

```python
self.groups = None if task_events else ['worker']
self.send_events = (
    task_events or
    not without_gossip or
    not without_heartbeat
)
```

`not without_gossip` is `True` by default, so the dispatcher is enabled and the `worker`
group is sent. `-E` only adds the `task` group. Interval is **2.0 s**
(`celery/worker/heartbeat.py`: `self.interval = float(interval or 2.0)`) — note the
published docs say "every minute", which contradicts the source; trust the source.

**Why it is nonetheless wrong for layer 2:** consuming an event stream requires a
long-lived consumer process holding broker state. That is exactly the extra
infrastructure the ticket rules out. `_kombu.binding.celeryev` exists in the db, but
nothing in ADL consumes it.

**Verdict: not usable from a synchronous request handler.** Worth recording as the
upgrade path if ADL ever wants a true "last seen" timestamp that survives a wedged
pidbox — a `worker-heartbeat` consumer writing to Redis would distinguish
"dead" from "wedged", which no synchronous probe can.

### 13. The distinction layer 2 cannot fully make: dead vs wedged vs slow

This was tested directly by `SIGSTOP`-ing the worker MainProcess — a faithful simulation
of a wedged event loop — while its two pool children still held 8 prefetched messages:

```
ping                     1.01s  None
stats                    1.01s  False
active_queues            1.00s  None   (AttributeError if not guarded)
depth (broker-side)      0.00s  2
LLEN adl                 : 2
HLEN unacked             : 8
```

**A wedged worker is byte-for-byte identical to a dead worker over the control channel.**
Both return `None` from every inspect command. The distinction can only be inferred from
broker-side state, which remains fully readable because it does not depend on the worker
at all:

| Condition | inspect | broker depth | `HLEN unacked` | Distinguishing tell |
|---|---|---|---|---|
| No worker ever started | `None` | rising | 0 | `unacked` empty |
| Worker dead / restarting | `None` | rising | falls to 0 within `visibility_timeout` (3600 s) | eventually redelivered |
| Worker wedged (main loop) | `None` | **static** | **static, non-zero** | messages held, nothing moving |
| Worker alive, children wedged | replies normally | static | static | `active()` shows large `time_start` age |
| Worker alive, just slow | replies normally | falling slowly | churning | `active()` ages are bounded |

The genuinely useful row is **"worker alive, children wedged"** — inspect answers, and
`active()` age is the tell. That is precisely ADL's failure mode: a plugin's
`get_station_data()` blocked on an upstream socket with no timeout.

**Verdict: layer 2 can reliably distinguish "children wedged" (inspect replies + old
`time_start`) from everything else. It cannot distinguish "worker dead" from "worker
wedged" in a single synchronous request, and must not pretend to.** The honest rendering
of `None` is **unknown**, with broker depth shown alongside as the independent evidence.

---

## Failure-mode table

| Signal | Cost (measured, healthy) | Silence means | Fails when | Verdict |
|---|---|---|---|---|
| `inspect().ping()` | 1.01 s unbounded / **0.00 s with `limit=1`** | unknown — dead **or** wedged **or** slow | prefork MainProcess alive but all children blocked → green while throughput is 0 | Trustworthy (MainProcess liveness only) |
| `inspect().active()` | 1.03 s / 0.00 s with `limit` | unknown | leaks task args (`safe=False` default); truncation is silent | **Trustworthy** — the Q3 signal |
| `inspect().reserved()` | ~1.5 s | unknown | capped at `prefetch_count` (8); zero when worker dead | Trustworthy as "held in memory", **misleading as backlog** |
| `inspect().scheduled()` | 1.01 s | unknown | always `[]` in ADL (no ETA/countdown anywhere) | **Exclude** |
| `inspect().stats()` | 1.00 s, ~1 KB | unknown | `getrusage` + two blueprint walks; only useful field is derivable statically | Trustworthy, **redundant** |
| `inspect().active_queues()` | 0.51 s / 0.01 s with `limit` | unknown | — | **Trustworthy** — the Q1 signal |
| `queue_declare(passive=True).message_count` | 0.00 s | n/a — raises instead | **raises `ChannelError` on an empty queue**; excludes all prefetched work | **Trustworthy** as unreserved depth |
| naive `LLEN adl` | 0.00 s | n/a | undercounts if any `priority >= 3` (measured 1 vs 4); ignores `global_keyprefix` | **Misleading** — do not use |
| `HLEN unacked` | 0.00 s | n/a | global to the Redis db, shared by all 3 queues | Trustworthy only as a whole-broker tie-breaker |
| Any of the above, broker refused | **6.08 s** unbounded → **0.07 s** bounded | — | `broker_connection_timeout=4` actually costs ~6 s via retry backoff | Must be bounded |
| Any of the above, broker blackholed | **75.06 s** unbounded (≈130 s on Linux) → **1.09 s** bounded | — | `socket_connect_timeout=None` default | **Page-hanging bug if unbounded** |
| `worker-heartbeat` events | needs a long-lived consumer | — | not consumable synchronously | Out of scope; upgrade path |

---

## Recommended set for layer 2

**Design rule:** one bounded connection, one broker-side read, at most two inspect
broadcasts, hard total budget **≈ 2.1 s worst case**, and every failure surfaces as
`unknown` rather than an exception or a hang.

### The connection

Build a dedicated short-lived `kombu.Connection`. Never mutate
`CELERY_BROKER_TRANSPORT_OPTIONS` in settings — that would also reconfigure the workers'
`BRPOP` loop.

```python
BOUNDED = dict(
    connect_timeout=1.0,
    transport_options={
        "socket_connect_timeout": 1.0,   # bounds the TCP blackhole -> 1.09s measured
        "socket_timeout": 2.0,           # bounds a hung established socket
        "max_retries": 0,                # kills the ~6s retry backoff -> 0.07s measured
        "retry_on_timeout": False,
    },
)
```

Rationale for each number:

- `connect_timeout=1.0` + `max_retries=0` → one attempt, no backoff. Measured 0.07 s on
  connection-refused (vs 6.08 s with defaults).
- `socket_connect_timeout=1.0` → bounds the blackhole case. Measured 1.09 s (vs 75.06 s on
  macOS, ~130 s on Linux).
- `socket_timeout=2.0` → deliberately above the 1.0 s inspect timeout so a healthy
  round trip is never cut short, and above kombu's 1 s BRPOP so the value stays sane if it
  is ever reused elsewhere.
- These apply to this connection object only; the app's pool and the workers are untouched.

### The three calls

| # | Call | Timeout | Answers | Worst case |
|---|---|---|---|---|
| 1 | `conn.default_channel.queue_declare(queue="adl", passive=True).message_count` | n/a (bounded by socket) | **Q2** — unreserved depth | ~0.01 s |
| 2 | `app.control.inspect(timeout=1.0, connection=conn).active_queues()` | 1.0 s | **Q1** — is a worker bound to `adl` | 1.0 s |
| 3 | `app.control.inspect(timeout=1.0, connection=conn).active()` | 1.0 s | **Q3** — stuck task, via `time_start` age | 1.0 s |

Total ≈ 2.1 s worst case healthy, ≈ 1.1 s when the broker is unreachable (call 1 raises
and short-circuits calls 2 and 3).

**Why not `limit=1`?** It measures 0.00 s instead of 1.0 s, which is very tempting. But it
returns the **first** reply only, so on an installation that has scaled
`adl_celery_worker_adl` to more than one replica it would report a single worker and miss
the others — including a stuck task on a worker that happened not to answer first. ADL's
compose ships one replica, so `limit=1` is safe *today* and would cut the budget to
~0.1 s. **Recommendation: default to unbounded `limit` with `timeout=1.0` for
correctness; treat `limit=1` as an opt-in fast path only if the diagnostic explicitly
declares itself single-worker.** Do not silently adopt it.

**Why not `destination=[...]`?** `-n adl-worker@%h` expands `%h` to the container
hostname, which Docker assigns. The full node name is not knowable in advance, so
`destination` (which would set `limit=len(destination)` and return immediately) is
unavailable. Only the **prefix** `adl-worker@` is stable — use it to filter results, not
to address the broadcast.

### Interpreting each result

**Call 1 — depth.**

```python
try:
    depth = conn.default_channel.queue_declare(queue="adl", passive=True).message_count
except ChannelError:
    depth = 0          # empty queue == absent key on Redis. NOT an error.
except OperationalError:
    depth = None       # broker unreachable -> everything below is unknown
```

`depth` is **unreserved work only**. Label it that way in the UI. It is a *lower bound* on
the backlog whenever call 3 returns `None`.

**Call 2 — is a worker consuming `adl`.**

```python
queues = insp.active_queues()          # None | {node: [queue dicts]}
if queues is None:
    consuming = "unknown"              # dead OR wedged OR slower than 1.0s
else:
    consuming = any(
        q["name"] == "adl"
        for node, qs in queues.items()
        for q in qs
    )
```

- `None` → render **"No worker replied (unknown)"**. Never "worker down".
- `{}`-equivalent (replies exist, none bound to `adl`) → render **"Workers alive but none
  consuming `adl`"** — the misconfigured-`-Q` case.
- A node bound to `adl` → **green**, and record whether its name starts with
  `adl-worker@` (an unexpected prefix means someone launched a worker by hand and it is
  worth showing).

**Call 3 — stuck task.**

```python
active = insp.active()                 # None | {node: [task dicts]}
if active is None:
    stuck = "unknown"
else:
    now = time.time()
    batches = [
        (t, now - t["time_start"])
        for node, tasks in active.items()
        for t in tasks
        if t["name"] == "adl.core.tasks.process_station_link_batch"
    ]
```

`time_start` is wall-clock epoch (`request.py:519`), so this subtraction is valid across
processes. Attribute to a connection via `args[0] == network_id`, matching the existing
convention in `get_active_tasks_by_network()`.

Suggested thresholds, expressed **relative to the connection's own schedule** rather than
a fixed constant, since ADL connections run on wildly different intervals:

- age > 1 × the connection's beat interval → **warn**, "batch running longer than one cycle"
- age > 3 × the connection's beat interval → **stuck**, "starving the queue"

A negative age indicates clock skew between the Django and worker containers — surface it
as a distinct diagnostic rather than clamping to zero.

**Composite verdicts to render:**

| depth | call 2 / 3 | Render |
|---|---|---|
| any | replied, `adl` bound, no old batches | **OK** |
| any | replied, batch age over threshold | **Stuck batch** — show task id, age, `station_link_ids` from `args[1]` |
| rising | `None` | **Worker not responding (unknown)** + "backlog ≥ N, and N is a lower bound" |
| 0 | `None` | **Worker not responding (unknown)** — no backlog, so possibly just idle |
| `None` | `None` | **Broker unreachable** — a distinct, higher-severity state |
| any | replied, no node bound to `adl` | **Misconfigured worker** — workers alive, none consuming `adl` |

### Rules the implementation must follow

1. **Every inspect result may be `None`.** The existing
   `get_active_tasks_by_network()` does `list(active.keys())[0]` — guarded by `if active`,
   but the pattern is fragile. Guard explicitly; a probe of `active_queues()` against a
   frozen worker raised `AttributeError: 'NoneType' object has no attribute 'values'`.
2. **Catch `ChannelError` from `queue_declare` and map to 0.** Otherwise a healthy idle
   system renders red.
3. **Catch `kombu.exceptions.OperationalError` around the whole block** and render
   "broker unreachable". Do not let it reach the template.
4. **Never call `stats()` on the request path.** Redundant with `ping`, and the most
   expensive command.
5. **Never call `scheduled()`.** Structurally always empty in ADL.
6. **Never use raw `LLEN`.** Use `queue_declare(...).message_count`.
7. **Never present broker depth as "the backlog"** without the `reserved + active` terms,
   or without labelling it "unreserved".
8. **Do not add `CELERY_BROKER_TRANSPORT_OPTIONS` to settings** to get the timeouts —
   it would reconfigure the workers' consume loop.
9. **Reuse the `None`-means-unknown convention** already established by
   `get_active_dispatch_tasks()`, and fix that docstring's inaccurate `{}` claim while
   nearby.

### Two follow-ups this research surfaced (separate from layer 2)

- **`get_active_tasks_by_network()` (`monitoring/views/__init__.py:287`) is exposed to the
  hang.** Two unbounded inspect calls at the default 1.0 s timeout: ≥ 2 s on every healthy
  request, ~12 s against a refused broker, and ~150 s against a blackholed one. It should
  adopt the same bounded connection.
- **Celery, Kombu and redis-py are unpinned** in `adl/requirements.txt` (they arrive via
  `django-celery-beat`'s `celery<6.0,>=5.2.3`). Across 26+ installations built at
  different times, this means different broker-internals behaviour — e.g. the kombu 5.3 vs
  5.4 change to priority-aware message restore.

---

## Open questions this research could not settle

1. **Do any real ADL installations scale `adl_celery_worker_adl` beyond one replica?**
   This decides whether `limit=1` (0.00 s vs 1.0 s per call) is safe. Compose ships one,
   but `deploy/` and site-specific overrides were not audited.
2. **What is a sensible stuck threshold in practice?** The "N × beat interval" rule is
   reasoned, not measured. It needs the observed distribution of
   `process_station_link_batch` durations across plugins — data ADL already has in
   `django-celery-results` / the monitoring tables but which was not analysed here.
3. **Clock skew between the Django and worker containers in non-compose deployments.**
   Under one `docker-compose` host it is zero. Installations running Django and workers on
   separate hosts were not surveyed, and `time_start` arithmetic degrades there.
4. **Is 1.0 s enough on a loaded NMHS box?** All timings here are from an unloaded laptop.
   A worker MainProcess under memory pressure could exceed a 1.0 s pidbox round trip and be
   reported `unknown` while perfectly healthy. Needs measurement against a real deployment
   before the timeout is fixed in code.
5. **Whether `dispatch` and `celery` queues should share this probe.** The mechanism is
   identical (only the queue name and node prefix change), but the thresholds are not.
   Not designed here.
6. **Does the beat container's own health need a layer?** If `adl_celery_beat` is dead,
   nothing is enqueued, the queue reads 0, and the worker reads perfectly healthy — the
   diagnostic would render all-green on a fully stalled system. This is a real blind spot
   of layer 2 as scoped, and probably belongs to a different layer.

---

## Source index

**Repo (this branch)**
- `docker-entrypoint.sh:60-69, 143-161` — worker launch, `-Q`/`-n`, default prefork pool
- `docker-compose.yml:91-171` — three worker containers, concurrency env vars
- `adl/src/adl/config/settings/base.py:283-322` — broker URL, task routes, shared Redis db 0
- `adl/src/adl/config/celery.py` — app construction, `CELERY` namespace
- `adl/src/adl/core/tasks.py:42-69` — `get_active_dispatch_tasks()`, the `None`/idle convention
- `adl/src/adl/core/tasks.py:99-200` — `run_network_plugin`, `process_station_link_batch`
- `adl/src/adl/monitoring/views/__init__.py:287-305` — existing unbounded inspect usage
- `adl/requirements.txt` — no celery/kombu/redis pin

**Celery 5.6.3**
- `celery/app/control.py:71-115` — `Inspect.__init__` (`timeout=1.0`), `_prepare` (implicit `None`), `_request`
- `celery/app/control.py:274-294, 558-575` — `Inspect.ping` vs `Control.ping`
- `celery/app/control.py:753-788` — `Control.broadcast`
- `celery/app/base.py:1042-1067` — `_connection`, `connect_timeout` from `broker_connection_timeout`
- `celery/app/defaults.py:89, 99, 265, 348` — `connection_timeout=4`, `pool_limit=10`, `acks_late=False`, `prefetch_multiplier=4`
- `celery/worker/control.py:395-443, 627-632` — `ping`, `stats`, `scheduled`, `reserved`, `active`, `active_queues`
- `celery/worker/worker.py:326-334` — `WorkController.stats`
- `celery/worker/request.py:515-521, 674-686` — `on_accepted` (ack-on-accept, wall-clock `time_start`), `info()`
- `celery/worker/consumer/control.py:18-33` — `Pidbox` vs `gPidbox` selection
- `celery/worker/heartbeat.py:28` — 2.0 s heartbeat interval
- `celery/worker/consumer/events.py:19-32` — worker events enabled without `-E`
- `docs/userguide/workers.rst` — reply-timeout rationale, solo-pool caveat
- `docs/userguide/routing.rst` — Redis message priorities

**Kombu 5.6.2**
- `kombu/pidbox.py:241-257, 298-340, 361-403` — reply queue, `_publish`, `_broadcast` limit rule, `_collect` `count()` loop
- `kombu/connection.py:411-416, 894-913, 946-964` — `_ensure_connection`, `_extract_failover_opts`, `default_channel`
- `kombu/utils/functional.py:275-334` — `retry_over_time`, post-attempt deadline check
- `kombu/transport/redis.py:106, 634-654, 1007-1043, 1077-1083, 1169-1204` — `PRIORITY_STEPS`, `sep`, `_size`, `_q_for_pri`, `_put`, `_get`, `_has_queue`, `_connparams`
- `kombu/transport/redis.py:360-458` — `QoS.append`, `unacked`/`unacked_index`, `visibility_timeout=3600`
- `kombu/transport/virtual/base.py:527-538` — `queue_declare`, `passive` 404, `message_count`
- `kombu/simple.py` — `SimpleQueue.qsize()` → same `_size` path

**Experiment**
- Local `redis-server` on port 6399 + `celery -A lab.app worker -Q adl -n adl-worker@test
  --concurrency 2`, exercising: idle inspect timing, `limit=1` short-circuit, 20-task
  prefetch accounting, `time_start` age arithmetic, `SIGSTOP` on the MainProcess vs on pool
  children, priority-key undercount, and refused / blackholed broker with and without
  bounded transport options.
