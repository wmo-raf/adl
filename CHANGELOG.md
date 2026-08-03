# Changelog

Notable changes to ADL core. Plugins are versioned separately in their own
repositories.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
with one addition: each release carries an **Upgrade notes** section listing the
migrations it ships and anything an operator must do *before* running them.
Read that section before upgrading a deployment.

This file starts at 0.8.9. Earlier history is in the git log.

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
