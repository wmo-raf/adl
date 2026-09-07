(routine-operations)=

# Routine Operations

The day-to-day of a production stack: which container does what, the
commands to see what they are doing, when to restart which one, and the
housekeeping that keeps disk and database healthy.

(service-map)=

## Service map

`docker compose ps` lists these containers. All of them read the same
`.env`.

| Container | Entrypoint command | Role | If it is down… |
|---|---|---|---|
| `adl_db` | postgres | PostgreSQL 15 with TimescaleDB and PostGIS. Data in `ADL_DB_VOLUME`. | Nothing works; the web container waits for it and every worker fails. |
| `adl_redis` | redis | Message broker for Celery; cache for station locks and probe cooldowns. | Ticks are not delivered; the diagnostic reports *The broker did not answer*. |
| `adl` | `gunicorn-wsgi` | The web application: admin, REST API, data viewer. Runs `migrate` and `collectstatic` on start. | Admin unreachable; ingestion and dispatch **continue** — the workers do not depend on it. |
| `adl_celery_beat` | `celery-beat` | The scheduler. Fires every connection's and channel's schedule entry from the database. | Nothing is scheduled. The diagnostic's Scheduler layer goes red: *The beat scheduler has stopped.* Manual runs still work. |
| `adl_celery_worker_adl` | `celery-worker-adl` | Consumes the **ingestion** queue (`adl`): runs the plugins. | No data collected. Diagnostic: *none is consuming the ingestion queue.* |
| `adl_celery_worker_dispatch` | `celery-worker-dispatch` | Consumes the **dispatch** queue: runs the channels. | Nothing sent. Channels show **OVERDUE**. |
| `adl_celery_worker_default` | `celery-worker-default` | Consumes the default queue: stale-log sweeps, health evaluation every five minutes, nightly cleanup and backup tasks. | Verdicts stop updating (`No verdict yet` never fills in); interrupted runs are never marked failed. |
| `adl_web_proxy` | nginx | Serves static and media files and proxies the app on `ADL_WEB_PROXY_PORT`. | Admin unreachable from outside. |
| `adl_pg_tileserv` | pg_tileserv | Vector tiles for the station map. | The map viewer shows no stations; everything else works. |

Three separate workers is deliberate: a slow FTP source cannot block
dispatch, and a slow WIS2Box cannot block ingestion.

## Daily glance

Sixty seconds on the admin home page answers "is everything working":

1. Every connection card on **Data Pulling** shows a green `OK` health
   badge and mostly green stations.
2. Every channel card on **Data Pushing** shows a recent last run and green
   stations.
3. No card shows `No verdict yet` (the housekeeping worker is alive).

Anything else: open the red thing. The Ingestion Diagnostic and the dispatch
runbook name the layer and the fix —
[Monitoring & Diagnostics](../user_guide/monitoring_and_diagnostics.md),
[Dispatch Troubleshooting](../user_guide/dispatch_troubleshooting.md).

## Looking at logs

```bash
make logs                 # everything, follow
make app-logs             # web container: requests, migrations, probe results
make worker-logs          # ingestion worker: per-station runs, plugin output
make beat-logs            # scheduler: which entries fired
docker compose logs -f adl_celery_worker_dispatch   # dispatch worker
docker compose logs --since 1h adl_celery_worker_adl # last hour only
```

Log verbosity is set in `.env`: `ADL_LOG_LEVEL` for the application,
`ADL_CELERY_WORKER_LOG_LEVEL` for workers, `ADL_CELERY_BEAT_DEBUG_LEVEL` for
beat, `ADL_DATABASE_LOG_LEVEL` for SQL. `INFO` on the workers shows each
station run's window and count and is the most useful setting for
diagnosing a plugin; `WARN` on the app keeps request logging quiet.

Per-station run history is also in the admin, with no server access: the
activity timelines under Monitoring and each station link's **Inspect**
page. Those are kept for seven days; the container logs rotate with Docker's
defaults.

(restarting-services)=

## Restarting services

Restarting is safe at any time. Running station collections are cut off and
logged as failed; their stations are re-collected from the last saved record
on the next tick. In-flight dispatches are likewise retried.

```bash
docker compose restart adl_celery_beat            # scheduler stopped / never fired
docker compose restart adl_celery_worker_adl      # ingestion worker down, stuck task
docker compose restart adl_celery_worker_dispatch # dispatch worker down, OVERDUE channels
docker compose restart adl_celery_worker_default  # verdicts not updating
docker compose restart adl_redis                  # "The broker did not answer"
docker compose restart adl                        # admin misbehaving, after a config change
make restart                                      # everything
```

A restart of `adl_redis` clears the station locks and probe cooldowns held
in the cache. That is harmless — locks protect against overlap within a run,
and the next tick takes fresh ones — and is the quickest fix when the
diagnostic reports stale locks on every station.

After a `.env` change, `make up` (not `restart`) is needed, so that the
containers are recreated with the new environment.

## Changing the schedule of a connection or channel

Edit the connection's **Interval** or the channel's **Data Check Interval**
in the admin and save. Saving rewrites the beat schedule entry; there is
nothing to restart. If the Ingestion Diagnostic's Scheduler layer later
warns that the schedule entry does not match the configured interval, or that
duplicate entries exist, saving the connection again repairs it.

## Pausing collection or dispatch

- **One station:** untick *Enabled* on its station link. It is skipped; the
  others continue.
- **One connection:** untick *Active* on the connection. Its schedule entry
  is disabled, its verdict shows `DISABLED`, and its station links keep
  their configuration and start dates.
- **One channel:** untick *Enabled* on the dispatch channel. Records keep
  accumulating and are sent when it is re-enabled, oldest first, at most
  *Maximum Records per Dispatch* per station per run.
- **Everything:** `docker compose stop adl_celery_beat`. Nothing fires until
  it is started again; the admin stays up for inspection.

(disk-and-housekeeping)=

## Disk and housekeeping

What grows:

| Path | What | Managed by |
|---|---|---|
| `docker/db_data` | Observation records, activity logs, health history | Observation records are kept forever. Activity logs are pruned after 7 days, probe results after 30, verdict history after 90, nightly. |
| `docker/backup` | Database dumps | You — see [Backup and restore](backup_restore.md). Prune old dumps in the same cron job that makes them. |
| Docker images and build cache | One layer set per `make build` | `docker image prune` after a successful upgrade; `docker builder prune` occasionally. |
| Container logs | stdout of every service | Docker's own rotation; set `max-size` in `/etc/docker/daemon.json` if `/var/lib/docker/containers` grows. |

Check with:

```bash
df -h
du -sh docker/db_data docker/backup docker/media
docker system df
```

Observation records are the only unbounded growth, and TimescaleDB's
chunking keeps queries fast as they accumulate. A deployment collecting from
dozens of stations at ten-minute intervals adds on the order of a few
gigabytes a year; size the disk for several years and monitor `df`.

### Database maintenance

PostgreSQL's autovacuum runs inside the container and needs no attention.
The hourly aggregates used by dispatch are a TimescaleDB continuous
aggregate, refreshed automatically as records arrive. Two commands exist for the rare cases where they are needed:

```bash
# rebuild hourly aggregates for a period (after a bulk backfill or a manual data correction)
docker compose exec adl adl refresh_hourly_agg --help

# remove beat schedule entries whose connection or channel no longer exists
docker compose exec adl adl prune_orphaned_periodic_tasks
```

## Users and credentials rotation

- **Admin passwords:** Settings → Users, or `docker compose exec adl adl
  changepassword <username>`.
- **Source credentials** (FTP passwords, API tokens): on the connection's
  edit form. After saving, open the Ingestion Diagnostic and press **Probe
  source now**; the Source layer confirms the new credential within the
  one-minute cooldown.
- **Destination credentials:** on the dispatch channel's edit form, then
  **Test connection** on its *Station Links* page.
- **Database password:** change it in PostgreSQL and in `.env` together,
  then `make up`. The application does not cache it.
- **Django `SECRET_KEY`:** rotating it signs every user out and invalidates
  password-reset links; nothing else depends on it.

## Time

All containers run in UTC and observation times are stored in UTC.
Station-local interpretation of timestamps comes from the connection's
*Stations Timezone*, not from the host clock — but the host clock must be
right, because windows end at "the top of the current hour" and a host that
is minutes slow requests data that does not exist yet. Keep NTP running on
the host.
