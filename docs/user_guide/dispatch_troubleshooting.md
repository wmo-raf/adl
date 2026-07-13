# Dispatch Troubleshooting

This page is the runbook for when a dispatch channel appears stuck or silent —
data is being collected, but nothing is arriving at the destination
(WIS2BOX, FTP, etc.).

Work through the steps in order, from least to most invasive. Most problems
are resolved by the first three steps, without any server access.

## What heals itself (and what doesn't)

ADL's dispatch pipeline is designed to recover from most failures on its own:

- **Hung sends time out.** Every station dispatch is bounded by the channel's
  *Dispatch Timeout* (default 5 minutes). A send stuck on an unresponsive
  destination is terminated and logged as a failure, and the next scheduled
  run proceeds normally.
- **Stale locks expire.** Overlap-protection locks always outlive the timeout
  by a safety margin, so a crashed worker can never permanently block a
  station.
- **Orphaned history is corrected.** If a worker dies mid-dispatch, a
  background sweeper marks the interrupted log entry as failed within a few
  minutes, so the activity history never shows an entry "running" forever.
- **Backlogs drain incrementally.** Each run sends at most *Maximum Records
  per Dispatch* (default 500) per station, oldest first, so a station
  recovering from days offline catches up across runs instead of timing out
  repeatedly.

What does **not** heal itself: a dead scheduler or a downed dispatch worker.
That is what the OVERDUE flag detects — see step 1.

## Step 1: Check the OVERDUE flag and activity logs

Open **Dispatch Channels** in the admin and click **Station Links** for the
affected channel. The page header shows when the channel last ran:

- **Last dispatch run: … ago** — the scheduler is running the channel.
  Continue to the per-station logs.
- **OVERDUE** (red badge) — the channel has not run within twice its
  *Data Check Interval*. This means the scheduler tick is not reaching the
  dispatch worker at all: the beat scheduler is down, the queue is not being
  consumed, or the dispatch worker is down. Skip to step 4.
- **Never run** — the channel has never dispatched. If it was just created,
  wait one interval; otherwise treat as OVERDUE.

The same information is available on the channel's monitoring dashboard,
along with per-station pipeline and data-freshness status.

Then check the per-station push activity logs (Monitoring → the channel, or
the station's activity log filtered by direction *push*). Each dispatch run
leaves one entry per station:

- **COMPLETED** with a records count — dispatch is working; if the
  destination still shows no data, investigate the destination side.
- **FAILED — "Dispatch timed out after N seconds"** — the destination is
  reachable but too slow, or the batch is too large. See
  [tuning the knobs](#tuning-the-per-channel-knobs).
- **FAILED** with a connection error — the destination is unreachable or
  rejecting credentials. Continue to step 2.
- **SKIPPED — "previous dispatch still running"** — normal under load;
  investigate only if a station shows this repeatedly for a long period.
- **FAILED — "worker died mid-dispatch"** — the worker was killed while
  sending (out-of-memory, container restart). Occasional entries after a
  restart are normal; frequent ones deserve investigation of worker memory.

## Step 2: Test the connection

On the channel's **Station Links** page, click **Test connection**. This
probes the destination synchronously (reachability, authentication, and for
WIS2BOX the presence of the incoming bucket) and reports the result
immediately, including latency.

- **Success** — the destination is fine; the problem is in scheduling or
  locking. Continue to step 3.
- **Failure** — fix what the message says: wrong endpoint, bad credentials,
  missing bucket, or a network/firewall problem between ADL and the
  destination.

## Step 3: Force a run — Dispatch now / Reset

- **Dispatch now** enqueues an immediate dispatch run for the channel,
  without waiting for the next scheduled tick. Watch the activity logs for
  the outcome.
- **Reset dispatch** clears the channel's per-station locks first, then
  triggers a fresh run. Use this if stations show repeated SKIPPED entries
  that never clear on their own.

Both actions affect only the selected channel.

## Step 4: Restart the dispatch worker

If the channel is OVERDUE and Dispatch now produces no activity-log entries
at all, the dispatch worker or scheduler is not processing tasks. On the
server:

```bash
docker compose restart adl_celery_worker_dispatch

# if still overdue after a couple of minutes, also restart the scheduler
docker compose restart adl_celery_beat
```

Dispatch runs on its own dedicated worker, so restarting it does **not**
interrupt in-flight data collection (ingestion runs on
`adl_celery_worker_adl`).

(tuning-the-per-channel-knobs)=
## Tuning the per-channel knobs

Both settings live on the dispatch channel's **Base** configuration section:

- **Dispatch Timeout in Seconds** (default 300, range 30–1800): the maximum
  time one station's dispatch may run. Raise it for slow links or slow
  destinations that log genuine timeouts while making progress. The
  overlap-protection lock and the stale-log sweeper derive their thresholds
  from this value automatically — there is no second knob to keep in sync.
- **Maximum Records per Dispatch** (default 500, range 1–10,000): how many
  records (observation times) one run sends per station, oldest first. Lower
  it if timeouts occur during backlog catch-up; raise it if the destination
  is fast and backlogs should clear more quickly.

Rule of thumb: a channel operating normally should complete each station in
a few seconds. If you find yourself raising the timeout repeatedly, lower
the record cap instead.
