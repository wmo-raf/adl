(backup-restore)=

# Backup and Restore

An ADL deployment is four things on disk. Back up all four and you can
rebuild the server from nothing; miss one and you cannot.

| What | Where (defaults from `.env`) | Contains |
|---|---|---|
| **Database** | `ADL_DB_VOLUME` → `./docker/db_data` | Every network, station, connection, credential, mapping, observation record, activity log and user. The only thing that cannot be recreated by hand. |
| **Media** | `ADL_MEDIA_VOLUME` → `./docker/media` | Uploaded files (station CSV imports, images). Small. |
| **Configuration** | `.env`, `plugins.toml`, `docker-compose.override.yml` if present | Secrets, ports, volume paths and the exact plugin versions. Without `.env` the database cannot be opened; without `plugins.toml` the image cannot be rebuilt identically. |
| **Backups folder** | `ADL_BACKUP_VOLUME` → `./docker/backup` | Where database dumps are written. Copy it off the server. |

Static files (`ADL_STATIC_VOLUME`) are regenerated on every start and need
no backup.

```{important}
**Automatic scheduled backups are currently disabled** in the core: the
nightly backup task is a placeholder pending a fix for TimescaleDB-aware
dumps. Until that lands, backups are something you run or schedule yourself
using the commands below. Put the database dump in `cron` on the host.
```

## Taking a backup

### Database

Two commands work; pick one and use it consistently.

**Option A — `adl dbbackup` (django-dbbackup).** Writes a compressed
`pg_dump` custom-format file into the backups folder and keeps the most
recent one:

```bash
docker compose exec adl adl dbbackup --clean --noinput
ls docker/backup/
```

**Option B — `pg_dump` directly.** The same thing without the Django wrapper,
and the form to use when you want to keep several dated dumps:

```bash
source .env
docker compose exec -T adl_db pg_dump -U "$ADL_DB_USER" -d "$ADL_DB_NAME" -Fc \
  > "docker/backup/adl-$(date +%F).dump"
```

Either way the dump is only a file on the same disk until you copy it
elsewhere. A minimal host `cron` entry that dumps nightly and syncs to
another machine:

```text
15 1 * * * cd /opt/adl && . ./.env && docker compose exec -T adl_db pg_dump -U "$ADL_DB_USER" -d "$ADL_DB_NAME" -Fc > docker/backup/adl-$(date +\%F).dump && find docker/backup -name 'adl-*.dump' -mtime +14 -delete && rsync -a docker/backup/ backup-host:/backups/adl/
```

**How big?** Observation records dominate. A twenty-station network at
ten-minute intervals with six parameters adds about half a million rows a
month; the compressed dump is typically well under a gigabyte per year of
data. Check `du -sh docker/db_data` for the live size.

### Media and configuration

```bash
tar czf "docker/backup/adl-config-$(date +%F).tgz" .env plugins.toml docker-compose.override.yml 2>/dev/null
tar czf "docker/backup/adl-media-$(date +%F).tgz" -C docker media
```

Store the configuration archive somewhere access-controlled: `.env` holds
the database password and the Django secret key, and connections' source
credentials are inside the database dump.

### Before an upgrade

Always. The [upgrade procedure](upgrading.md) starts with a backup because a
migration that fails halfway is recoverable only from one.

(restoring)=

## Restoring

Restoring means: a clean stack with an empty database, the PostGIS and
TimescaleDB extensions present, then the dump loaded **while nothing else is
connected**. The application containers must not run their startup
migrations against the empty database first, or the restore will collide
with the freshly created tables.

### 1. Prepare the target server

Install Docker and clone the repository as in [Installation](../installation.md),
then restore the configuration archive so `.env` and `plugins.toml` are the
originals:

```bash
tar xzf adl-config-<date>.tgz
mkdir -p docker/db_data docker/media docker/static docker/backup
cp adl-<date>.dump docker/backup/
tar xzf adl-media-<date>.tgz -C docker
```

Build the image with the same plugin versions:

```bash
make build
```

### 2. Start only the database

```bash
docker compose up -d adl_db
docker compose logs -f adl_db   # wait for "database system is ready to accept connections"
```

The database container creates the empty database named in `.env` on first
start. Create the extensions the dump expects:

```bash
source .env
docker compose exec adl_db psql -U "$ADL_DB_USER" -d "$ADL_DB_NAME" \
  -c "CREATE EXTENSION IF NOT EXISTS postgis;" \
  -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

### 3. Load the dump

TimescaleDB needs to be told a restore is in progress so hypertable
internals are rebuilt correctly:

```bash
docker compose cp "docker/backup/adl-<date>.dump" adl_db:/tmp/adl.dump
docker compose exec adl_db psql -U "$ADL_DB_USER" -d "$ADL_DB_NAME" -c "SELECT timescaledb_pre_restore();"
docker compose exec adl_db pg_restore -U "$ADL_DB_USER" -d "$ADL_DB_NAME" --no-owner --no-privileges /tmp/adl.dump
docker compose exec adl_db psql -U "$ADL_DB_USER" -d "$ADL_DB_NAME" -c "SELECT timescaledb_post_restore();"
```

`pg_restore` may print warnings about extensions that already exist; those
are harmless. Errors mentioning missing roles are avoided by `--no-owner`.

If the dump was made with `adl dbbackup`, the equivalent is the wrapper's
own restore, run from a one-off application container that skips startup
migrations:

```bash
docker compose run --rm -e MIGRATE_ON_STARTUP=false adl manage dbrestore --noinput
```

### 4. Start everything and verify

```bash
docker compose up -d
make logs
```

Startup migrations now run against the restored schema and apply anything
the new image needs. Then:

1. Sign in to the admin. Your users, networks and connections are there.
2. Open **Connections**: every connection shows `No verdict yet` until the
   first five-minute health sweep, then its real verdict.
3. Open one connection's Ingestion Diagnostic and press **Probe source now**
   to confirm the restored credentials still reach the source.
4. Open a station link's *View Data* and confirm the history is present up
   to the backup time. Collection resumes from the latest saved record on the
   next tick, so the gap since the backup is backfilled automatically where
   the source still holds the data.

## Moving to a new server

The restore procedure *is* the migration procedure: back up on the old
server, restore on the new one, then repoint DNS or the proxy. Keep the old
server stopped (`make stop`) from the moment the final backup is taken, or
the two instances will both collect and both dispatch.

## Disaster checklist

Kept somewhere other than the server, per deployment:

- Last verified restore date (do one on a test machine after every major
  upgrade).
- Location of the off-server backup copies and who has access.
- The `.env` and `plugins.toml` archive.
- The ADL release and plugin tags in production (`git describe --tags` in
  the checkout, and `docker compose exec adl list-plugins`).
