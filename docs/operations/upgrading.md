(upgrading)=

# Upgrading

ADL core and its plugins are released independently. A core upgrade is a
rebuild of the image from a newer git revision; a plugin upgrade is a change
of one `tag` in `plugins.toml` followed by the same rebuild. Both take a few
minutes of downtime while containers restart, and both run database
migrations automatically on start.

## Before you start

1. **Read the changelog.** Every core release has an **Upgrade notes**
   section in [CHANGELOG.md](https://github.com/wmo-raf/adl/blob/main/CHANGELOG.md)
   listing the migrations it ships and anything to do *before* running them.
   Read every release between yours and the target, not just the newest.
2. **Check plugin compatibility.** Each plugin guide has a *Compatibility*
   table naming the core version it needs. A plugin can require a minimum
   core; a core can drop support for an old plugin contract. Upgrade the
   core first, then plugins, unless the changelog says otherwise.
3. **Take a backup** — see [Backup and restore](backup_restore.md). A
   migration that fails halfway is recoverable only from one.
4. **Pick a quiet moment.** Ingestion pauses during the restart; a
   ten-minute connection loses at most one tick, and the next run resumes
   from the last saved record, so nothing is lost where the source keeps
   history. Dispatch likewise catches up on its next run.
5. **Note the current version** so you can roll back:

   ```bash
   git describe --tags        # core
   docker compose exec adl list-plugins   # plugins
   ```

## Upgrading the core

```bash
cd /opt/adl                      # your checkout
git fetch --tags
git checkout v0.8.15             # the release tag from the changelog
make build                       # rebuild the image (plugins are re-installed from plugins.toml)
make up                          # recreate the containers
make app-logs                    # watch migrations and startup
```

`make build` is not optional. Releases can add services or entrypoint
commands that exist only in the new image; `make up` recreates the
containers whose definition changed and leaves the rest running.

Core release tags carry a leading `v` (`v0.8.15`). If you track `main`
instead of tags, `git pull` replaces the checkout step.

### What happens on start

Each application container runs `migrate` and `collectstatic` before
serving. Watch `make app-logs` for the migration list; when it ends with
`Applying …  OK` lines and gunicorn's *Listening at*, the upgrade is
applied. Workers wait for the web container to be healthy before starting,
so they never run against a half-migrated schema.

### Verify

1. Sign in and confirm the admin loads.
2. Open **Connections** and confirm every connection still shows a verdict.
   A `MISCONFIGURED` verdict after an upgrade means a plugin tightened its
   validation rules and a stored connection no longer passes them; the
   message names the field to fix.
3. Open one Ingestion Diagnostic and press **Run ingestion now**. A completed
   run proves the workers, the queue and the plugin all came up.
4. Check a dispatch channel's *Station Links* page for a fresh *Last dispatch
   run* after its next interval.

(upgrading-a-plugin)=

## Upgrading a plugin

Edit the plugin's entry in `plugins.toml`:

```toml
[[plugins]]
name = "ADL FTP Plugin"
git  = "https://github.com/wmo-raf/adl-ftp-plugin.git"
tag  = "0.13.0"    # was 0.12.2 — plugin tags carry no leading "v"
```

Then rebuild and restart exactly as for the core:

```bash
make build
make up
make app-logs
```

Plugin migrations run on start alongside the core's. If you install plugins
with `ADL_PLUGIN_GIT_REPOS` instead, change the `#tag` suffix there:

```bash
ADL_PLUGIN_GIT_REPOS=https://github.com/wmo-raf/adl-ftp-plugin.git#0.13.0
```

```{note}
Plugin tags are bare (`0.13.0`); core and agent tags have a `v`
(`v0.8.15`). The manifest pins the tag verbatim, so a `v` copied onto a
plugin tag fails the build with a "reference not found" error from git.
```

## Rolling back

Core and plugins roll back the same way they upgrade: check out the previous
tag (or restore the previous `plugins.toml`), `make build`, `make up`.

Migrations are the catch. Django migrations applied by the new version stay
in the database, and an older image may not know them. Roll back the
database too when the changelog's upgrade notes for the release you are
leaving list migrations:

1. `make down`
2. Restore the pre-upgrade backup — {ref}`Restoring <restoring>`.
3. Check out the previous tag, `make build`, `make up`.

Observations collected between the upgrade and the rollback are in the new
database only; where the source still has them, the next runs backfill from
the restored last-saved record.

## Upgrading across many releases

Jumping several releases at once is supported — migrations apply in
sequence — but read the *Upgrade notes* of every intermediate release
first. Where one says a step must happen *before* its migrations (a manual
data fix, a plugin upgrade that must land first), do that step at the
corresponding point: check out that release, `make build`, `make up`, then
continue.

## Upgrading the database image

`adl_db` runs `timescale/timescaledb-ha:pg15`. The compose file pins the
image; do not change the PostgreSQL major version by editing the tag, since
the data directory format differs between majors. A PostgreSQL major upgrade
is a backup, a fresh data directory with the new image, and a restore — the
{ref}`restore procedure <restoring>` end to end.
