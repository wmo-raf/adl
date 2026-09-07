(monitoring-module)=

# 📈 Monitoring Module Reference

`adl.monitoring` is the Django app behind the admin's health and activity
screens: the per-connection ingestion diagnostic, the activity timelines,
the dashboard status API and the Task Monitor. This page is the developer
map of the module — what it stores, what it computes, and where the seams
are — for anyone extending the core or implementing the plugin-side
[diagnostic contracts](plugins/diagnostic_contracts.md). The operator-facing
description of the same screens is in the user guide's
[Monitoring & Diagnostics](../user_guide/monitoring_and_diagnostics.md).

## Layout

| Module | Responsibility |
|---|---|
| `models.py` | The four stored record types (below). |
| `health.py` | The ingestion diagnostic evaluator: computes the checklist and persists verdict changes. |
| `status.py` | The one per-station status computation shared by the dashboard, the activity views and the diagnostic's Data layer. |
| `classification.py` | Read-time text classification of unstamped failure rows (the untrusted fallback tier; the trusted write-time tier is `adl.core.classification`). |
| `constants.py` | `CheckState`, layer identifiers and labels, provenance labels. |
| `views/health.py` | The diagnostic page and the three on-demand actions: probe source, run now, station source check. |
| `views/activity.py` | JSON views behind the dashboard cards (`NetworkConnectionActivityView`, `DispatchChannelMonitoringView`). |
| `views/__init__.py` | Timeline pages, activity-log JSON, Task Monitor, active-task inspection. |
| `panels.py`, `wagtail_hooks.py` | The home-page activity panel and URL registration under `/monitoring/`. |
| `tasks.py` | Nightly retention cleanup. |
| `monitoring-ui-vue/` | The Vue source of the dashboard cards and the Task Monitor. |

## Stored records

```{eval-rst}
.. autoclass:: adl.monitoring.models.StationLinkActivityLog
   :members:
   :no-undoc-members:
```

One row per station per run, both directions (`pull` for ingestion, `push`
for dispatch, the latter carrying `dispatch_channel`). Written by the core's
tasks, never by plugins. Notable columns:

| Column | Meaning |
|---|---|
| `status` | `STARTED` → `IN_PROGRESS` → `COMPLETED` / `FAILED`; `SKIPPED` when a lock collision prevented the run. Only `COMPLETED` and `FAILED` count as diagnostic evidence. |
| `records_count` | Observation records saved. |
| `sources_count` | Tri-state: `NULL` = the plugin did not report, `0` = the source answered and offered nothing, `n` = items offered. Read by the Source layer's sources-count qualification. |
| `obs_start_time`, `obs_end_time` | The window requested. |
| `error_category`, `error_layer`, `exception_class` | Write-time classification stamps from `adl.core.classification.mark_failed`; `NULL` when core declined. |

Retention: 7 days (`run_station_link_activity_log_cleanup`).

```{eval-rst}
.. autoclass:: adl.monitoring.models.NetworkConnectionHealth
   :no-members:
```

One overwritten row per connection: the current headline (`status`,
`first_failing_layer`, `headline_check_id`, `headline_message`), `since`
(moves only when the verdict changes) and `evaluated_at`. Rendered by the
connections list *Health* column and the dashboard badge.

```{eval-rst}
.. autoclass:: adl.monitoring.models.NetworkConnectionHealthTransition
   :no-members:
```

Append-only log of `(from_status, from_layer) → (to_status, to_layer)` per
connection; the diagnostic's *Verdict history* and flapping count. Retention
90 days.

```{eval-rst}
.. autoclass:: adl.monitoring.models.SourceProbeResult
   :no-members:
```

One row per probe step: `check_id` (`dns_resolution`, `tcp_connect`,
`source_check`, or `station_source_check`), `layer`, `status`, `category`,
`message`, `latency_ms`, `at`. Connection-scope rows have `station_link`
NULL; station-scope rows carry the link and are excluded from the
connection verdict by query. Retention 30 days.

## The evaluator

```{eval-rst}
.. autofunction:: adl.monitoring.health.evaluate_connection_health
.. autofunction:: adl.monitoring.health.store_connection_health
.. autofunction:: adl.monitoring.health.evaluate_all_connections
```

`evaluate_connection_health` is pure with respect to the partner host: it
reads the beat schedule, the coordinator heartbeat, the cache (locks), one
bounded broker observation (`adl.core.broker.get_ingestion_queue_health`),
activity logs and stored probe rows, and returns a
`ConnectionHealthChecklist` — the precondition band plus one `HealthCheck`
per ladder entry. It never dials the source.

Rules implemented in `_ChecklistBuilder`:

- **First blocking `FAILED` sets the headline**; everything after it is
  emitted as `SKIPPED`. Advisory checks (`blocking=False`) are shown but
  never lead. A blocking `UNSUPPORTED` (the worker-consuming signal off the
  tested broker stack) can lead only when nothing failed or warned.
- **Connection-scope configuration drift** (`full_clean` on the stored
  row raises `ValidationError`) short-circuits the ladder as
  `MISCONFIGURED`; station-scope drift excludes that station's rows from
  layer-5 evidence and is shown on its Inspect page.
- **Layers 4 and 5 each hold one evidence slot** fed by three producers —
  a fresh probe row (≤ 15 minutes), the freshest terminal activity log
  within 2 × interval (successes, write-time-stamped failures, or
  read-time-classified failures), and, for layer 5 only, the
  sources-count qualification when layer 6 is already red. Freshest wins,
  ties go to the probe, the loser is kept as `superseded`. With no
  evidence the slot rests at `STALE`, never `FAILED`.
- **`has_external_source = False`** on the connection class makes both
  external layers `NOT_APPLICABLE` before any evidence is read;
  **`dials_source = False`** makes layer 4 `NOT_APPLICABLE` and withholds
  run logs from the external slots.
- **Layer 6** rolls up `status.compute_station_status` over enabled links:
  all stale → `FAILED`, some → `WARNING`, none → `OK`.

`store_connection_health` persists only change; `evaluate_all_connections`
is called from `adl.core.tasks.sweep_stale_activity_logs` every five
minutes on the default queue, after stranded rows have been made terminal,
so the evaluator never reads a dead run as in progress.

## Per-station status

```{eval-rst}
.. autofunction:: adl.monitoring.status.compute_station_status
.. autofunction:: adl.monitoring.status.connection_thresholds
.. autofunction:: adl.monitoring.status.dispatch_channel_thresholds
.. autofunction:: adl.monitoring.status.annotate_station_pull_activity
```

One computation, three consumers: the dashboard card JSON, the timeline
pages and the diagnostic's Data layer all call `compute_station_status`
with the timestamps `annotate_station_pull_activity` supplies, so they
cannot disagree about a station. Thresholds derive from the connection's
interval (`×3` pipeline tolerance, `×4` / `×12` freshness) or, for
daily-data connections, 26 / 48 hours; dispatch thresholds add the
aggregation window.

## On-demand actions

All three live in `views/health.py`, are `POST`-only, and are gated by
`adl.core.permissions.can_manage_connection` — the change permission for
the connection's concrete class or the polymorphic base.

| View | URL name | What it does |
|---|---|---|
| `connection_probe_source` | `connection_probe_source` | Claims the per-host 60-second cooldown (`adl.core.probes.claim_probe_cooldown`), runs `adl.core.source_checks.run_source_probe` synchronously under the 15-second wall clock, stores one `SourceProbeResult` per step, reports the first failure or a success count as a Django message. |
| `connection_run_now` | `connection_run_now` | Refuses (with an info message) while a run for the connection is executing or within the connection-keyed cooldown (interval, capped at 15 minutes); otherwise enqueues `run_network_plugin` with `manual=True` on the ingestion queue. `manual=True` stamps `last_manual_run_at` on the heartbeat, never `last_run_at`. |
| `station_link_check_source` | `station_link_check_source` | Same cooldown discipline keyed on `(host, station link)`; runs `run_station_source_check` for one link and stores the row with `station_link` set. |

The buttons are hidden, never disabled: `connection.source_probe_supported`,
`station_link.station_source_check_supported` and the worker-consuming
check decide whether the form renders at all, so a user never sees a
button that cannot act.

## Internal JSON endpoints

These serve the admin's own Vue components. They require an admin session
and are not part of the public [REST API](../api.md); their shapes may
change between releases.

| URL | Consumer |
|---|---|
| `/monitoring/connection-activity/<id>/` | Dashboard connection card: connection meta, stored health (`status`, `first_failing_layer_label`, `since_human`, `diagnostic_url`), per-station statuses and summary counts. |
| `/monitoring/dispatch-activity/<id>/` | Dashboard channel card, same shape for the push side. |
| `/monitoring/station-activity/<connection id>/` | Timeline rows (activity logs) for a connection, bounded to 7 days per request and 30 days back. |
| `/monitoring/plugin-processing-results/<id>/[<from>/]` | Celery `TaskResult` rows of the connection's coordinator task since a date. |
| `/tasks/active/[network/<id>/]` | Running ingestion tasks from the worker's `inspect().active()`, for the Task Monitor. |
| `/events/` | Server-sent events (`django_eventstream`) streaming task log lines to the Task Monitor. |

## The Task Monitor

**Monitoring → Task Monitor** in the sidebar shows the ingestion tasks the
workers report as currently executing (*Active Tasks Monitor*) and a live
tail of their log lines over server-sent events (*Waiting for logs…* until a
task emits). *Worker Status Unknown* means the broker inspection did not
answer, the same condition the diagnostic reports as *The broker did not
answer*. It is a live view only; history lives in the activity logs.

## Extending

- **A new internal check** is a new `_check_<id>` method on
  `_ChecklistBuilder` plus an entry in `_ladder_plan()`; return
  `(state, message, blocking)` or a dict of `HealthCheck` kwargs. Keep
  messages translatable and free of raw exception text.
- **A new failure category** must be added to
  `adl.core.classification.FAILURE_CATEGORIES` *and*
  `adl.monitoring.classification.CATEGORY_MESSAGES`; the vocabulary is
  closed and validated on both tiers.
- **Plugin-side evidence** never touches this module directly: plugins
  implement the contracts on `NetworkConnection` / `StationLink`
  (`get_source_endpoint`, `check_source`, `check_station_source`,
  `adl_sources_count`, exception stamping) and the evaluator reads the
  results. See [Ingestion Diagnostic Contracts](plugins/diagnostic_contracts.md).
- **Tests** for the evaluator live in `adl/src/adl/monitoring/tests/`; run
  them with `make dev-test TEST_ARGS=adl.monitoring`.
