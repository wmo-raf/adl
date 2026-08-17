# Changelog

Notable changes to ADL core. Plugins are versioned separately in their own
repositories.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
with one addition: each release carries an **Upgrade notes** section listing the
migrations it ships and anything an operator must do *before* running them.
Read that section before upgrading a deployment.

This file starts at 0.8.9. Earlier history is in the git log.

## [Unreleased]

## [0.8.11] — 2026-08-17

A small release. The headline is a change to how a station link's collection
start date is used, so operators can skip a large backlog on a station that has
been offline; the rest is admin ergonomics for plugin-provided station pages.

### Changed

- A station link's configured **collection start date** is now a floor on the
  ingestion window instead of a first-run-only fallback. Each run resumes from the
  later of the latest saved observation and that date, so moving the date forward
  on a station with a large backlog (for example one that has been offline for
  months) makes the next run skip the gap rather than fetch it all; the task log
  says so when it happens. Existing rows are unaffected unless the date is later
  than the latest saved record — the case in which it previously did nothing.
  The date still never moves collection backwards. Plugins need no code change;
  their field label and help text ("Initial collection start date… ignored if any
  data has been collected") will be updated to match in their own releases.

### Added

- A station link's extra admin pages — the `get_extra_model_admin_links()` hook
  a plugin overrides — now render on the station link's **inspect page header**
  as well as on its listing row, so a page reachable from the list is also
  reachable from the record itself. `StationLink` gains a documented default of
  the hook (an empty list) mirroring the connection's, and the plugin guide
  shows the per-instance gating pattern (offer the page only for links
  configured a certain way).

### Removed

- `StationLink.get_extra_model_admin_buttons()`, a hook that was declared but
  never rendered anywhere. No plugin implemented it; `get_extra_model_admin_links()`
  is the one contract for both surfaces.

### Upgrade notes

No migrations in this release.

**Check station links whose start date is later than their latest saved record.**
Until now such a date did nothing. From this release the next scheduled run for
that station resumes from the date and does not fetch the intervening period.
That is the intended use — an operator moved the date forward to skip a backlog
— but if a date was set that way by accident and the gap is wanted, clear or
move the date back *before* upgrading; afterwards the gap is only reachable
through a manual `collect_data(initial_start_date=...)` run.

## [0.8.10] — 2026-08-12

A maintenance release. The headline is a database durability fix that affects
every deployment; the rest is admin ergonomics and plugin-authoring documentation.

### Fixed

- The database container is given five minutes to shut down rather than Docker's
  default ten seconds. The `timescaledb-ha` image stops on `SIGINT` — a Postgres
  *fast shutdown*, which must complete a checkpoint flushing `shared_buffers`
  (2 GB by default) to disk before it exits. Ten seconds does not reliably cover
  that, so every `docker compose down`, `restart` and host reboot was
  `SIGKILL`ing Postgres mid-checkpoint and leaving an unclean shutdown, on every
  deployment. Repair of the resulting torn pages then rested entirely on the
  storage honouring `fsync`. One installation lost the HOT chain parent on
  `django_celery_beat_periodictasks` after a power cut, which made
  `PeriodicTasks.last_change()` raise `MultipleObjectsReturned`; celery beat
  crash-looped for 14 days with no ingestion or dispatch and nothing to announce
  it. (#241)
- Scaffolded plugins run the three queue-specific celery workers. The plugin
  compose template still used the entrypoint's removed generic `celery-worker`
  command, so a new plugin shipped a worker that printed usage help and exited 1
  — and even when that command existed it consumed only the default queue, never
  the `adl` ingestion or `dispatch` queues that tasks are actually routed to.
  (#240)

### Added

- Station links surface their plugin's extra admin pages as listing buttons, as
  connections already did through `get_extra_model_admin_links()`. A plugin page
  scoped to a single station — a per-station variable-mapping editor, say — had
  no way to be reached from the listing. (#240)
- The ingestion diagnostic's **Run ingestion now** button now closes the layer
  ladder instead of heading the page, so the whole diagnosis is read before the
  action is offered. It is hidden when no worker is consuming the ingestion
  queue, the one state where the press provably achieves nothing; every failure
  a manual run can still help with — a stopped scheduler above all — keeps the
  button, since the run bypasses beat and goes straight to the queue. (#242)
- A plugin-authoring guide for the ingestion diagnostic contracts: the seven
  contract surfaces a plugin can implement so layers 4, 5 and part of 6 report
  something better than `UNSUPPORTED`, what each means per source archetype, and
  the rules a retrofit is measured against. (#239)

### Upgrade notes

No migrations in this release.

**The database fix needs one manual step, once.** `stop_grace_period` is fixed
when a container is *created*, so a running `adl_db` still carries the ten-second
timeout — including for the stop that `docker compose up -d` performs in order to
recreate it. Recreating it without stopping it explicitly crash-kills the
database one last time:

```bash
docker compose stop -t 300 adl_db   # clean shutdown under the old container
docker compose up -d
docker compose logs adl_db | tail -20
```

The last line should end in `database system is shut down` on the stop and show
no `database system was not properly shut down` on the start.

This bounds the routine crash-kills; it does not make a host safe from power
loss. Sites still need a UPS with automatic graceful shutdown, and should enable
`data_checksums` so that a torn page is detected rather than silently served.

## [0.8.9] — 2026-08-03

A maintenance release. Every change is a fix to how ADL behaves when something
upstream is broken, or to what a failure is allowed to reveal.

### Security

- Credentials are no longer stored in operator-visible failure text. A source
  that authenticates with a query parameter leaked its token into activity-log
  messages, which the monitoring API then served back: `requests` puts the full
  request URL in its `HTTPError` text, and core stored it verbatim. Redaction
  now happens where the text is produced, so the stored row, the admin
  rendering, the export and the worker log are all covered at once. Only a
  named secret is removed and the key is kept, so a message still says which
  credential was involved. (#214, #218, #219)
- The manual-action admin views are gated on a change permission for the object
  being acted on. They were registered with no check of their own, so the
  effective gate was "any user who can log into the Wagtail admin" — including
  an account provisioned purely to read the monitoring pages. The sharpest of
  the five, `reset_channel_dispatch`, deletes the per-station locks that prevent
  concurrent double-dispatch. (#216)

### Fixed

- A deleted network connection or dispatch channel no longer leaves its Celery
  Beat schedule behind. The orphaned entry stayed enabled and fired forever
  against an id nobody could see in the admin — ingestion logged an error every
  interval, dispatch failed hard every interval. Deployments that have already
  accumulated orphans can clear them with the new
  `prune_orphaned_periodic_tasks` management command, which takes `--dry-run`.
  (#217)
- The task-monitor page no longer hangs on a broken broker. Its two Celery
  `inspect()` calls used the app's default connection, which retries: measured
  at ~12 s against a refused broker and ~150 s against a blackholed one, on a
  page whose whole purpose is to be usable when things are broken. In-process
  broker calls now go through one short-lived connection with ~1 s timeouts and
  no retries. (#215)
- A dispatch channel's "test connection" button is bounded at 15 s and
  rate-limited to one press per minute. Nothing previously bounded how long a
  channel could take or how often the button could be pressed, and the probe
  runs synchronously in the web process — a blackholed S3 endpoint tied up a
  worker for minutes per click, re-clickable. The return shape of
  `test_connection` is also validated in core rather than trusted from the
  plugin. (#212, #213)
- The ingestion lock TTL and the stale-log sweep are derived from the batch
  timeout rather than set independently, so they can no longer disagree with the
  bound they are supposed to follow. (#210)
- A plugin install can no longer resolve `django-celery-beat` away from core's
  pin. Core drives its model API directly to write beat schedules, so a plugin
  moving it would move the schedule writer. A plugin that genuinely needs a
  different version now fails loudly at install time. (#218)

### Added

- The admin shows the effective per-station ingestion timeout. The configured
  value is a batch budget, not a per-station one, and the two differ whenever a
  connection has more than one station. (#210)

### Upgrade notes

Migrations in this release:

- `core.0051` — metadata only (`help_text` on `ingest_timeout_seconds`).
- `monitoring.0010` — **a data sweep over activity-log history.** It rewrites
  stored rows in `StationLinkActivityLog`, `SourceProbeResult` and
  `NetworkConnectionHealth`, replacing credentials with `***`. Irreversible by
  design: the reverse is a no-op because the secret is gone, which is the point.

**Before migrating,** if this deployment has enabled TimescaleDB compression on
old activity-log chunks, decompress them. Timescale refuses updates to a
compressed chunk, and the migration deliberately does not decompress for you —
that is a deployment decision, not something a migration should do silently.
Installs without compression need do nothing.

After migrating, consider clearing any orphaned beat schedules left by
connections or channels deleted under earlier versions:

```bash
adl prune_orphaned_periodic_tasks --dry-run   # review first
adl prune_orphaned_periodic_tasks
```
