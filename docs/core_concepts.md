# 🧠 Core Concepts

This section introduces the core ideas behind **ADL (Automated Data Loader)** to help you quickly understand how data
moves through the system and where plugins, models, and admin screens fit in.

---

## 1) The Big Picture

ADL is a **Django-based platform** that ingests observations from many upstream sources, normalizes them into a common
schema, and makes them available for analysis, visualization, and downstream dispatch (e.g., WIS2).

At a high level:

1. **Plugins** know how to talk to external systems (APIs, files, brokers) and produce time-stamped records.
2. **Core models** (Station, Parameter, Unit, ObservationRecord, etc.) provide a canonical structure in the database.
3. **Schedulers** (Celery Beat/Worker) invoke plugins on intervals, handle batches, and support backfills.
4. **Dispatch channels** can publish/forward curated data to external targets (e.g., WIS2Box).

```{mermaid}
flowchart LR
  subgraph Upstream
    A[Source API/Feed]
  end

  subgraph ADL Core
    P[Plugin] --> N[Normalization Unit & Mapping] --> S[Observation Record TimescaleDB]
    S --> A1[Aggregations]
    S --> Q[Query Admin UI]
  end

  subgraph Downstream
    D[Dispatch Channel e.g. WIS2Box]
  end

  A --> P
  A1 --> D
```

---

## 2) Core Data Model

Understanding a few key models clarifies how ADL thinks about networks and measurements.

### Network

Represents a family of stations (e.g., “ADCON Automatic Weather Stations”). Purely organizational.

### Station

A physical observing point (with location, identifiers such as WIGOS, heights, metadata). Stations belong to a
Network.

### NetworkConnection

Configuration for a **specific upstream integration** (credentials, cadence, timezone defaults, batch size, daily vs
hourly data, etc.). A `NetworkConnection` points to a **Plugin type** that will perform the actual collection.

### StationLink

Binds one Station to a NetworkConnection and adds **per-station** connection details (e.g., remote station code,
per-station timezone, enable/disable, optional first-collection date). Plugins typically iterate over the `StationLink`
set of a `NetworkConnection`.

### Unit & DataParameter

- **Unit** defines canonical unit symbols (backed by a unit registry).
- **DataParameter** names a measurable variable (e.g., `air_temperature`) and which **Unit** ADL uses as canonical. It
  also supports optional **conversion contexts** for tricky cases (e.g., precipitation mass/area equivalence).

### ObservationRecord

The atomic measurement in ADL, keyed by `(time, station, connection, parameter)` with a `value`. Stored in TimescaleDB
for efficient time-series operations. Flags whether a record is daily (`is_daily`).

### Aggregations (HourlyObsAgg)

A view for hourly summaries (min/max/avg/sum, counts). Used by analytics and dispatch.

---

## 3) Plugin Architecture (Extension Point)

Plugins are Django apps that extend the `Plugin` base class and register themselves in the **plugin registry**. The base
class provides:

- **Date-window helpers**: Picks `[start_date, end_date)` for each station (resuming from last saved data if present).
- **Normalization & saving**: Converts source values to canonical units and upserts ObservationRecords.
- **Orchestration**: Iterates station links, handles disabled stations, and returns per-station counts.

### Contract: `get_station_data(station_link, start_date, end_date)`

- Inputs are **aware datetimes** in the **station timezone** (base will normalize if naive).
- Return an **iterable of dicts**; each dict must include `observation_time` and may include any number of
  source-parameter fields whose names match your station’s variable mappings (e.g., `temp_K`).
- The base class takes care of unit conversion and upserting.

### Variable Mapping

Each StationLink provides a mapping from **source field name & unit** → **ADL DataParameter**. Example: `temp_K` (
Kelvin) → `air_temperature` (Celsius). This drives conversion and saving.

---

## 4) Time, Timezones & Windows

**Golden rules:**

- Plugins work in the **station’s timezone**; the database stores UTC.
- Default window is **the previous hour** up to the **top of the next hour** (closed-open `[start, end)`).
- If past data exists in ADL ObservationRecords table, ADL resumes from the **latest saved observation time**.
- If no database records, ADL may use a **station-defined first collection date** or the default previous-hour window.
- For daily feeds, the `NetworkConnection.is_daily_data` flag marks saved rows accordingly.

### Naive vs Aware datetimes

- If a plugin returns naive `observation_time`, ADL interprets it as **station-local** and makes it aware.
- If the plugin returns aware datetimes (UTC or otherwise), ADL converts them to station-local **without shifting the
  instant**.

---

## 5) Scheduling & Execution

- **Celery Beat** triggers periodic runs (e.g., every 15 minutes) according to `plugin_processing_interval` on the
  `NetworkConnection`.
- **Celery Workers** execute the fetch/save jobs and can scale horizontally.
- Manual runs can be initiated via `NetworkConnection.collect_data()` (useful for backfills or debugging).
- Plugins should respect upstream **rate limits** and add **retry/backoff** for transient failures.

---

## 6) Dispatch Channels (Downstream)

After ingestion, ADL can **publish** data to external systems via **Dispatch Channels**. A channel selects parameters,
optionally uses aggregations (e.g., hourly), and pushes records onward. Example: **Wis2BoxUpload** connects to a WIS2
storage endpoint and uploads observations.

Dispatch entities:

- **DispatchChannel**: base configuration (enabled, interval, optional start date, aggregated vs raw).
- **DispatchChannelParameterMapping**: maps ADL parameters into the channel’s expected field names/units and selects the
  aggregation measure (avg/sum/min/max).
- **Station selection**: choose which stations are allowed for the channel.

---

## 7) Observability & Operations

- **Logging**: Plugins and core components log key events (window bounds, station ids, counts, warnings on validation).
- **Idempotency**: Upserts based on the unique key avoid duplicates; late data updates the same unique row.
- **Troubleshooting**: Check plugin logs for window computations, mapping issues, and unit conversion warnings.

Operational tips:

- Use conservative timeouts and a `requests` retry adapter in API clients.
- For performance: paginate upstream requests, stream/process in chunks, rely on TimescaleDB indexes for readbacks.

---

## 8) Security & Configuration

- **Access control** is managed by Django/Wagtail admin permissions; admin-only URLs for plugin helpers (widgets,
  metadata views) should remain authenticated.
- **Licensing & data policy**: Respect source terms; document attribution requirements in plugin README.

---

## 9) Developer Workflow

1. **Create a plugin** from the boilerplate (cookiecutter) or copy the sample.
2. Implement `get_station_data` and register the plugin in `AppConfig.ready()`.
3. Add models for `NetworkConnection` and `StationLink` as needed; create migrations.
4. Add admin widgets/views only if they improve operator UX.
5. Run locally with Docker Compose (ADL core + your plugin) and iterate.

---

## 10) Glossary

- **Plugin**: A Django app implementing `get_station_data` to fetch and normalize upstream data.
- **Network**: A grouping of stations.
- **Station**: An observing site (location/metadata).
- **NetworkConnection**: Configuration for a specific upstream integration; references a Plugin type.
- **StationLink**: Binds a Station to a NetworkConnection and adds per-station connection details.
- **DataParameter**: Canonical variable name with a canonical Unit.
- **Unit**: Measurement unit used by ADL; convertible via the unit registry.
- **ObservationRecord**: The core time-series row `(time, station, connection, parameter, value)`.
- **Dispatch Channel**: A mechanism to publish records to external systems.

---

## 11) Mental Model (TL;DR)

- A **Connection** + **StationLinks** define *what* to pull and *from where*.
- A **Plugin** defines *how* to pull and *how to map* the fields.
- ADL chooses a **time window**, the plugin returns rows, and ADL **upserts** them.
- Optional **Dispatch** moves curated data out to other systems.

If you understand the *Connection → StationLink → Plugin → ObservationRecord* chain, you understand ADL.