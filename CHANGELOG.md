# Changelog

Notable changes to ADL core. Plugins are versioned separately in their own
repositories.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
with one addition: each release carries an **Upgrade notes** section listing the
migrations it ships and anything an operator must do *before* running them.
Read that section before upgrading a deployment.

This file starts at 0.8.9. Earlier history is in the git log.

## [Unreleased]

## [0.8.15] — 2026-09-01

A release about getting to the data without re-selecting it. The data viewer's
table and chart pages previously booted empty on every visit — whatever you
were looking at, the URL never knew. Both pages now read their state from the
URL and keep it there as you work, so a view can be bookmarked, shared, or
linked to from anywhere in the admin — and the admin now does exactly that,
with "View Data" links on every surface that names a station. One PR (#308).

### Added

- **The data viewer table is deep-linkable.** `/viewer/table/` reads
  `connection`, `station` (station-link id), `category` and `from`/`to`
  (`YYYY-MM-DD`) from the URL on load, and reflects filter changes back with
  `history.replaceState` — the Back button still returns to the page you came
  from. Values equal to their defaults are omitted, so `?station=42` is a
  complete, canonical link that always means "that station's latest day".
  `station` wins over a mismatched `connection`. Invalid or stale params fall
  back per-param to defaults, dates clamp to the station's archive, and
  everything dropped or adjusted is listed in one dismissible banner.

- **Chart views are shareable.** `/viewer/chart/` encodes each panel as a
  repeatable packed param —
  `chart=<connectionId>:<stationLinkId>:<parameterId>:<from>:<to>`, empty
  segments meaning defaults — and writes every configured panel back, so a
  multi-panel comparison view survives a copy-paste. Same correction and
  fallback semantics as the table.

- **"View Data" links across the admin.** The monitoring dashboard's
  connection-activity rows (previously a link to a blank table) and
  dispatch-channel rows (previously dead) now open the viewer pre-filtered to
  the station, as do three new entry points on station links: the index row
  more-menu, the inspect page header, and the station-link monitoring page.
  All of them build the URL through one shared helper,
  `get_station_link_view_data_url()`.

### Upgrade notes

- No migrations, and no plugin has to be edited. The rebuilt viewer bundles
  ship in the image; there is nothing to run beyond deploying the release.

## [0.8.14] — 2026-08-27

A release about a claim core was making on evidence that did not support it.
Ingestion refused any observation older than the newest one it already held,
mistaking a high-water mark for a guarantee that everything below it had
arrived. Wherever a station's history had a hole, the records sent to fill it
were dropped — permanently, since the file that carried them was stamped as
processed. The floor is now the Collection Start Date, a claim an operator
actually made. A patch bump; no migrations, and no plugin has to be edited.

### Fixed

- **Observations were rejected for arriving behind the newest record ADL held,
  and their files were stamped so they were never retried.** Timestamp
  validation compared each record against the resolved window `start_date`,
  which is derived from the newest observation already stored. That value
  answers "the newest thing I hold"; the check read it as "everything older, I
  already hold". Those are the same statement only when a station's history has
  no holes, so any record arriving to fill a gap was discarded — and for a
  file-staging plugin the file was still stamped `processed_at` with
  `values_saved = 0`, which is never re-read. The lower bound is now the
  station link's **Collection Start Date** (`get_first_collection_date()`), the
  one an operator actually sets, and records below the high-water mark are
  saved normally.

  This most visibly affected the ADL Agent, which uploads newest-first *by
  design* so that history fills in behind, making a gap the normal state rather
  than the exception: after the first current file landed, every backlog file
  behind it was dropped on arrival. It also silently disabled re-processing —
  re-decoding a file older than the station's newest record produced nothing.

- The `end_date` upper bound on timestamp validation has been removed. For
  every plugin using the default `get_default_end_date` it was unreachable:
  `end_date` always falls after `now`, so the future-timestamp check bound
  first. A plugin overriding it to floor at the current hour could reach it,
  but only in principle — such a plugin passes the same `end_date` to its
  source, so the response is bounded at the request. Dead code that read as a
  live guard. `observation_time` in the future is still rejected — that check
  is unchanged and is now the only upper bound.

### Changed

- `Plugin.save_records()` no longer takes `start_date` and `end_date`. They
  were only ever read by the two bound checks above and are now unused. No
  plugin in the ADL plugin set calls this method directly; the window is still
  resolved and still passed to `get_station_data()` exactly as before.

### Upgrade notes

No migrations.

Ingestion now accepts records older than the newest one already stored. Two
consequences worth knowing before upgrading:

- **Stations with no Collection Start Date configured have no lower bound at
  all.** If a source is known to emit bad historical timestamps, set that field
  on the station link — it is the supported way to express "never store data
  before this date".
- **Data already dropped is not recovered by upgrading.** For file-staging
  plugins, the affected files are the ones stamped as processed with zero
  values saved; re-processing them re-runs the drain and lands their data.
  Re-process *after* upgrading, never before — a re-process against the old
  code re-stamps the files and destroys the only marker identifying which ones
  were affected.

## [0.8.13] — 2026-08-20

A release about telling silence apart from health. Two shapes of connection
were reading green at the ingestion diagnostic's external layers when nothing
was reaching ADL at all: one whose observations are submitted directly, and
one whose source is a real remote machine that pushes to us. Both now say what
they are, and the diagnostic stops claiming network calls it never made. Ships
one migration.

### Fixed

- A plugin's dev stack no longer dies at startup when `PLUGIN_BUILD_GID` is
  not the image's own group. `install_plugin.sh` ended by handing the plugin
  folder and the container markers to `adl_docker_user` — including on the
  runtime path, where it is not root and cannot give a file to a group it
  does not belong to. On macOS the documented `PLUGIN_BUILD_GID=$(id -g)` is
  `20`, so the chown returned `EPERM` and `set -e` took the container down
  before the app started. The chown now happens only when running as root,
  which is the only time it means anything: unprivileged, everything the
  script just created is already owned by the user that created it, and
  reassigning it would take a developer's own bind-mounted source folder
  away from them.

- A connection whose plugin has no upstream source no longer reads a
  fabricated green at layers 4 and 5 of the ingestion diagnostic. Observations
  that are submitted to ADL directly never cross a network or present a
  credential, yet every successful run minted an `OK` for both layers — and
  because those verdicts are blocking, the ladder stopped there and never
  walked the operator down to layer 6, where the real fault (nobody submitted
  anything) lives. Such a plugin now declares `has_external_source = False` on
  its `NetworkConnection` subclass; both layers report the new
  `NOT_APPLICABLE` state, gathering no evidence at all, and the on-demand
  source-probe buttons are withdrawn from the connection and its station
  links. (#235)

- A connection whose source pushes to ADL no longer reads a fabricated green
  at layers 4 and 5 from its own ingestion runs. `has_external_source` asked
  only whether an external source exists, so a plugin whose source is a real
  remote machine that *delivers* to ADL — an ADL Agent on a country server
  with no public IP — had to choose between claiming a network path it never
  opens and giving up a layer that has a genuine subject. Worse, either way
  its runs were read as evidence: such a run sweeps a staging store, dialling
  and authenticating nothing, yet each completed one minted an `OK` for both
  layers, and because the freshest observation wins, a drain of files that
  arrived before the machine died overruled the machine's own report of being
  dead — the connection read green exactly when the country was dark.

  `NetworkConnection` gains a second declaration, `dials_source` (default
  `True`, so nothing changes for the nine plugins that dial). A connection
  setting it `False` reports layer 4 as `NOT_APPLICABLE` — there is no network
  path of ADL's to probe — and contributes no activity-log evidence to either
  external layer, leaving layer 5 to its plugin's own `check_source()`. The
  predicate is deliberately this flag and not "names an endpoint": a plugin
  that dials but has not yet retrofitted `get_source_endpoint()` still made a
  real connection, and its runs are still evidence. See the new
  *pushed-external* archetype in the plugin diagnostic-contracts guide. (#277)

### Changed

- `make dev-build` now tags its image **`adl:dev`** instead of `adl:latest`,
  leaving `adl:latest` to mean the `prod` target only. The two targets are not
  interchangeable — the dev target omits core's source, because the dev stack
  bind-mounts it — yet both carried the same tag, so whichever of `make build`
  and `make dev-build` you ran last decided whether every plugin's dev stack,
  in every other repository, could start at all. Plugins build
  `FROM adl:latest` and mount only themselves; they need the target that
  contains core. If you develop plugins, run `make build` once to replace an
  `adl:latest` left over from the dev target. Nothing else changes: the dev
  stack builds and runs exactly as before, under its own tag. (#252)

- Diagnostic check badges now render each state's translated label rather
  than its raw enum value. Every previous state was a single word, so the two
  were indistinguishable; `NOT_APPLICABLE` is the first that is not. (#235)

### Upgrade notes

Ships one migration, `monitoring.0011`, which only widens the stored status
choices to include `NOT_APPLICABLE`. No data is rewritten.

**What changes on a running deployment.** Connections whose plugin declares no
upstream source, or declares that ADL does not dial it, stop showing green
verdicts at layers 4 and 5 of the ingestion diagnostic and report
`NOT_APPLICABLE` instead. Nothing about those connections has got worse — the
green was never earned — but a dashboard read as "all layers green" will now
read as "the external layers do not apply here, and the fault is at layer 6".
That is the point: the operator is walked down to where the fault actually is.
Connections whose plugin dials out are unaffected.

**Plugin authors.** `dials_source` defaults to `True`, so no existing plugin
changes behaviour and no plugin has to be edited. If your plugin's source is a
remote machine that pushes to ADL rather than one ADL fetches from, read the
new *pushed-external* archetype in *Developer Guide → Plugins → Ingestion
Diagnostic Contracts*: declaring it is what stops your own ingestion runs being
read as evidence that the remote machine is alive.

**Plugin images.** Plugins build `FROM adl:latest`, so rebuild that image
(`make build`) and then each plugin's stack before the new declarations take
effect there. On an older core the flag is an unread class attribute: such a
plugin still runs, it simply does not get the new behaviour.

## [0.8.12] — 2026-08-17

A bug-fix release. Records a plugin had already fetched could be lost when an
ingestion run was cut short; they are now written before the run ends, and a
plugin can ask for them to be written at its own natural boundaries. No
migrations ship.

### Fixed

- Records a plugin had already yielded are no longer lost when the run is cut
  short. `save_records` buffers records up to `SAVE_CHUNK_SIZE` (500) before
  each bulk write, and previously that buffer was only written on a full chunk
  or a clean end of the source: a batch soft time limit, or an upstream error
  on the next fetch, threw the buffered records away. For a one-record-per-file
  feed that could mean every file of a run downloaded and stamped as processed
  by its plugin with nothing reaching the database. The buffer is now written
  before the exception propagates, and a failed or timed-out run's activity log
  carries the records that *were* saved (`records_count`, observation range,
  and a note on the timeout message) instead of `0`.

### Added

- `adl.core.registries.FLUSH` — a marker a plugin can `yield` from
  `get_station_data` between records to have the buffered records written
  immediately. Meant for sources whose natural unit is much smaller than a
  chunk (one file per observation, small API pages): yielding it after each
  unit keeps fetched data out of memory-only limbo, and code after the `yield`
  runs only once the write is done, so a plugin can mark its own unit as
  processed truthfully. Plugins that never yield it are unaffected. See
  *Plugin API Reference → When records reach the database*.

### Upgrade notes

No migrations in this release. Nothing to do before upgrading.

**What changes on a running deployment.** A station run that hits the batch soft
time limit, or whose source fails part-way, now leaves the records it had
already fetched in the database and reports them on its activity log
(`records_count`, observation range, and "; N records saved before the
cut-off" on the timeout message). Previously such a run reported 0 and kept
nothing. If you have been reading FAILED / 0 rows as "no data was fetched",
re-read them as "nothing survived" — from this release the two are told apart.

**Plugins.** No code change is required. Plugins whose source unit is much
smaller than a 500-record chunk (one file per observation, small API pages)
should yield the new `adl.core.registries.FLUSH` marker after each unit so
records are written as they arrive; `adl-ftp-plugin` does so from 0.11.1. See
*Plugin API Reference → When records reach the database*.

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
