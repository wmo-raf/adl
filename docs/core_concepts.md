(core-concepts)=

# 🧠 Core Concepts

ADL collects observations from many different station networks, stores them
in one schema, and forwards them to the systems that need them. This page
gives you the mental model behind the admin: what the objects are, how they
relate, and what happens between a scheduled tick and a record in the
database. Read it once before configuring anything; every other page assumes
it.

## The big picture

```{mermaid}
flowchart LR
  subgraph SRC["Data sources"]
    FTP[FTP / SFTP server]
    API[Vendor REST API]
    DB[(Vendor database)]
    APP[Mobile collector / agent]
  end

  subgraph ADL["ADL core"]
    direction TB
    PL[Plugins] --> NORM[Validate · map · convert units · QC]
    NORM --> OBS[(Observation records\nTimescaleDB)]
    OBS --> AGG[Hourly aggregates]
    OBS --> VIEW[Data viewer · API · monitoring]
  end

  subgraph DST["Destinations"]
    W2B[WIS2Box]
    S3[S3 / MinIO]
    OUT[FTP / partner systems]
  end

  FTP & API & DB --> PL
  APP --> OBS
  OBS & AGG --> DC[Dispatch channels] --> W2B & S3 & OUT
```

Three things to hold on to:

1. **Plugins do the source-specific work.** The core never knows what an FTP
   file or a vendor API looks like; a plugin turns it into time-stamped
   records. Destinations work the same way through dispatch channels.
2. **Everything lands in one place first.** Every observation becomes an
   *observation record* — one station, one parameter, one time, one value in
   that parameter's unit — before anything else can happen to it.
3. **In and out are decoupled.** Ingestion stores; dispatch reads what was
   stored. Data goes nowhere unless a dispatch channel says so (see
   [Data flow and access control](data-flow-and-access-control.md)).

## The objects and how they relate

```{mermaid}
erDiagram
  NETWORK ||--o{ STATION : "groups"
  NETWORK ||--o{ CONNECTION : "scopes"
  CONNECTION ||--o{ STATION_LINK : "has"
  STATION ||--o{ STATION_LINK : "is linked by"
  STATION_LINK }o--o{ VARIABLE_MAPPING : "source variable → parameter"
  CONNECTION }o--o{ VARIABLE_MAPPING : "(or at connection level)"
  DATA_PARAMETER ||--o{ VARIABLE_MAPPING : "target"
  UNIT ||--o{ DATA_PARAMETER : "stored in"
  STATION ||--o{ OBSERVATION_RECORD : ""
  CONNECTION ||--o{ OBSERVATION_RECORD : ""
  DATA_PARAMETER ||--o{ OBSERVATION_RECORD : ""
  DISPATCH_CHANNEL }o--o{ CONNECTION : "reads from"
  DISPATCH_CHANNEL ||--o{ PARAMETER_MAPPING : "parameter → destination name/unit"
  DISPATCH_CHANNEL ||--o{ CHANNEL_STATION : "per-station enable/disable"
```

| Object | What it is | Admin location | Guide |
|---|---|---|---|
| **Network** | A named group of stations sharing a vendor or collection method. Organisational only. | Sidebar → Networks | [Manage Networks](user_guide/manage_networks.md) |
| **Station** | A physical observing site: name, WIGOS identifier, location, heights, type. Belongs to one network. | Sidebar → Stations | [Manage Stations](user_guide/manage_stations.md) |
| **Unit** | A measurement unit the unit registry can convert between (`°C`, `hPa`, `mm`). | Settings → Units | [Manage Data Parameters](user_guide/manage_data_parameters.md) |
| **Data parameter** | One variable ADL stores — *Air Temperature*, *Precipitation* — with the unit it is stored in and its quality-control rules. | Settings → Data Parameters | [Manage Data Parameters](user_guide/manage_data_parameters.md) |
| **Connection** | One upstream integration: which plugin, its credentials and settings, how often to run. Belongs to one network. | Sidebar → Connections | [Manage Connections](user_guide/manage_connections.md) |
| **Station link** | Binds one station to one connection and carries the *source-side* station identifier, timezone and collection start date. | Sidebar → *\<Plugin\> Station Links* | [Manage Connections](user_guide/manage_connections.md) |
| **Variable mapping** | "Source variable *X* in unit *U* is ADL parameter *P*". Lives on the connection, the station link, or both, depending on the plugin. | On the connection or station link form | [Manage Plugins](user_guide/manage_plugins.md) |
| **Observation record** | The stored measurement: `(time, station, connection, parameter) → value`. Unique on that key, so re-ingesting the same time updates rather than duplicates. | Data viewer; *View Data* on a station link | — |
| **Dispatch channel** | One destination: its type (WIS2Box, S3, FTP…), credentials, schedule, which connections it reads, and parameter mappings to the destination's names and units. | Sidebar → Dispatch Channels | [Manage Dispatch Channels](user_guide/manage_dispatch_channels.md) |

The chain to remember is **Network → Connection → Station link → Variable
mapping → Observation record → Dispatch channel**. If a station collects
nothing, the fault is somewhere along that chain, and the
[Ingestion Diagnostic](user_guide/monitoring_and_diagnostics.md) tells you
which link.

## A worked example, end to end

A national service has twelve Davis Vantage Pro2 stations whose logger
software uploads a CSV file per station every ten minutes to the service's
own FTP server. The GBON subset must reach WIS2Box. Here is the complete
configuration, in the order you would do it.

**1. Units and parameters.** Load the predefined parameters
(*Temperature* in °C, *Relative Humidity* in %, *Atmospheric Pressure* in
hPa, *Wind Speed* in m/s, *Wind Direction* in degrees, *Precipitation* in
mm) with *conversion units* ticked, which also creates Kelvin, Pascal and
kg/m² for WIS2Box.

**2. Network.** *Davis AWS Network*, type *Automatic Weather Stations*.

**3. Stations.** Import the twelve stations from OSCAR Surface into the
network; each arrives with its WIGOS identifier and coordinates.

**4. Plugin.** Install `adl-ftp-plugin` (pinned to a release tag in
`plugins.toml`) and rebuild. *FTP Connection* now appears as a connection
type.

**5. Connection.** *Davis FTP*, network *Davis AWS Network*, plugin *FTP*,
interval **10** minutes, stations timezone *Africa/Nairobi*. Plugin fields:
host, port, username, password, the remote folder, the file-name pattern
and the decoder for Davis CSV.

**6. Variable mappings** on the connection (the same CSV columns for every
station):

| ADL parameter | Source variable | Source unit |
|---|---|---|
| Temperature | `temp_out` | °F |
| Relative Humidity | `hum_out` | % |
| Atmospheric Pressure | `bar` | inHg |
| Wind Speed | `wind_speed` | mph |
| Wind Direction | `wind_dir` | degree |
| Precipitation | `rain` | in |

Only mapped columns are stored; the CSV's other columns are ignored.

**7. Station links.** One *FTP Station Link* per station: the ADL station,
the connection, the station's sub-folder or file prefix on the FTP server,
and *Collection Start Date* set to the beginning of the month to backfill.

**8. First run.** Open the connection's Ingestion Diagnostic, press
**Probe source now** (DNS, TCP, login and folder listing pass), then **Run
ingestion now**. Within a minute each station's Inspect page shows *Records
Fetched* and the dashboard turns green.

**9. Dispatch.** Create a *WIS2Box Upload* channel reading from *Davis FTP*,
map *Temperature* → `air_temperature` in Kelvin, *Atmospheric Pressure* →
`pressure` in Pascal, *Precipitation* → `precipitation` in kg/m², and so on;
disable the non-GBON stations on the channel's station list. Every ten
minutes the channel sends what is new.

From here on the system runs itself. What follows explains what happens on
each of those ten-minute ticks.

## What happens on a tick

```{mermaid}
sequenceDiagram
  participant Beat as Celery Beat
  participant W as Ingestion worker
  participant P as Plugin
  participant S as Source
  participant DB as Database

  Beat->>W: run connection (every N minutes)
  W->>W: heartbeat · split enabled station links into batches
  loop each station link (locked)
    W->>W: choose window [start, end)
    W->>P: get_station_data(link, start, end)
    P->>S: fetch (FTP list/read · API call · SQL)
    S-->>P: raw records
    P-->>W: {observation_time, var: value, ...}
    W->>W: validate · map variables · convert units · QC
    W->>DB: upsert observation records
    W->>DB: activity log (count, window, outcome)
  end
```

1. **Beat fires** the connection's schedule entry every *Interval* minutes.
2. **The coordinator** on the ingestion worker stamps a heartbeat, takes the
   connection's enabled station links, and splits them into batches of
   *Processing Batch Size*. Each station is **locked** while it runs, so an
   overlapping tick skips it rather than double-fetching.
3. **The window** for each station is computed (next section) and handed to
   the plugin with the station link.
4. **The plugin fetches** from the source and yields records shaped
   `{"observation_time": …, "<source variable>": value, …}`.
5. **The core normalises**: records are validated, each source variable is
   looked up in the variable mappings (unmapped keys are dropped), the value
   is converted from the mapping's source unit to the parameter's unit, QC
   checks run, and the record is **upserted** on `(time, station,
   connection, parameter)`.
6. **An activity log row** records the outcome per station: how many source
   items were offered, how many records were saved, the window, and any
   error. These rows are what the dashboard and the diagnostic read.
7. Each station's run is bounded by the connection's *Ingestion Timeout*; a
   hung source fails that station's run instead of wedging the worker.

## Time windows, timezones and backfill

- **Timezones.** Plugins work in the **station's timezone** (the
  connection's *Stations Timezone*, or the station link's own when *Use
  Connection Timezone* is unticked). The database stores UTC. A naive
  `observation_time` from a plugin is taken as station-local; an aware one is
  converted without changing the instant.
- **The window** is half-open, `[start, end)`. `end` is the top of the
  current hour in the station's timezone. `start` is the **later** of the
  latest saved observation for that station and the station link's
  *Collection Start Date*. With no saved data and no start date, the plugin's
  default window applies — usually the previous hour, sometimes the previous
  day; the field's help text says which.
- **Backfill.** Set *Collection Start Date* in the past before the first run.
- **Skipping a backlog.** Move *Collection Start Date* forward past the
  latest saved record; the next run resumes from there and the gap is logged
  as skipped. The date only ever moves collection forward — see
  {ref}`station-links-choosing-where-collection-starts`.
- **Late data.** Because records are upserted on their unique key, a source
  that re-sends an old timestamp updates the existing row rather than
  creating a duplicate.
- **Daily data.** Ticking *Is Daily Data* on the connection marks its records
  as daily and relaxes the freshness thresholds on the dashboard to 26 and
  48 hours.

## Dispatch

```{mermaid}
flowchart LR
  T[Beat tick every\nData Check Interval] --> R[Read records not yet sent\nper station, oldest first,\nup to Max Records per Dispatch]
  R --> M[Apply parameter mappings\nname + unit per destination]
  M --> A{Send aggregated?}
  A -- no --> S[send_station_data]
  A -- hourly --> H[Hourly aggregate\nmin / max / avg / sum] --> S
  S --> L[Activity log · push]
```

A dispatch channel is the mirror image of a connection. It is enabled or
disabled, runs every *Data Check Interval* minutes, reads from one or more
connections, and can start from a fixed *Starting date*. Per run and per
station it sends at most *Maximum Records per Dispatch* (default 500),
oldest first, so a backlog drains across runs. Each send is bounded by the
*Dispatch Timeout*.

**Parameter mappings** translate each ADL parameter into the destination's
field name and unit (Temperature → `air_temperature` in K). With **Send
Aggregated Data** ticked, the channel sends hourly summaries instead of raw
records, and each mapping chooses the measure (average, sum, min, max).

**Station selection** is per channel: every station on the chosen
connections is included unless disabled on the channel's station list. A
station can be in several channels, one, or none.

## Monitoring in one paragraph

The home page shows every connection's stored **health verdict** and every
station's pipeline and data-freshness colour. The verdict comes from the
**Ingestion Diagnostic**, which names the first failing layer of six —
Scheduler, Worker & queue, Station locks, Network path, Source, Data — from
the heartbeats, schedule entries, locks, activity logs and probe results the
system already holds. The two external layers are checked on demand with
**Probe source now**, never on a timer; a station's own identity at the
source is checked with **Check station source now** on its Inspect page.
Dispatch has its own *Test connection*, *Dispatch now* and lock tools. All of
this, with every message the core can show, is in
[Monitoring & Diagnostics](user_guide/monitoring_and_diagnostics.md) and
[Dispatch Troubleshooting](user_guide/dispatch_troubleshooting.md).

## Services on the box

| Container | Role |
|---|---|
| `adl` | The web application (admin, API, data viewer). Runs migrations and collects static files on start. |
| `adl_celery_beat` | The scheduler. Fires connection and channel ticks. |
| `adl_celery_worker_adl` | Consumes the **ingestion** queue: runs plugins. |
| `adl_celery_worker_dispatch` | Consumes the **dispatch** queue: runs channels. |
| `adl_celery_worker_default` | Housekeeping: activity-log sweeps, health evaluation, nightly cleanup. |
| `adl_db` | PostgreSQL with TimescaleDB and PostGIS. |
| `adl_redis` | Message broker and cache (locks, cooldowns). |
| `adl_web_proxy` | Nginx in front of the app, on `ADL_WEB_PROXY_PORT`. |
| `adl_pg_tileserv` | Vector tiles for the map viewer. |

Separate workers per queue mean a flood of ingestion work cannot starve
dispatch, and vice versa. See [Routine operations](operations/routine_operations.md).

## Glossary

- **Plugin** — an installable package that implements one source type
  (ingestion) and/or one destination type (dispatch).
- **Connection** — configuration for one upstream integration; picks the
  plugin and holds its credentials and schedule.
- **Station link** — binds a station to a connection; carries the
  source-side station identifier and collection start date.
- **Variable mapping** — source variable + source unit → ADL parameter.
- **Observation record** — the stored `(time, station, connection,
  parameter) → value` row.
- **Dispatch channel** — one outbound destination with its own schedule,
  station selection and parameter mappings.
- **Tick** — one scheduled run of a connection or channel.
- **Window** — the `[start, end)` time range a station's run asks the source
  for.
- **Health verdict** — the stored result of the Ingestion Diagnostic: a
  status and the first failing layer.
- **Source check / probe** — the on-demand checks behind the Network path and
  Source layers.
