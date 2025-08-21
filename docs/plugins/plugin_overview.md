# Plugin Overview

ADL (Automated Data Loader) helps you **pull weather/observational data from many sources**, normalize it, and **store
it in one database** for dashboards, APIs, and downstream systems.

Under the hood it uses:

- **Django** for models, admin UI (via Wagtail), and orchestration
- **TimescaleDB/PostgreSQL** for time-series storage
- **Redis + Celery** for scheduled/background jobs
- **Docker Compose** for a reproducible local stack

---

## Why Plugins?

Each provider storage (TAHMO, PulsoWeb, ADCON, Campbell, National AWS networks, CSV/FTP endpoints, etc.) exposes data
differently. A **plugin** is a tiny, provider-specific adapter that knows:

1. **How to talk** to that provider (API auth, pagination, retries), and
2. **How to translate** the provider’s fields/units into ADL’s common format.

ADL then handles date windows, timezones, unit conversion, upserts (safe re-ingest), logging, and scheduling.

---

## Core Concepts (Mental Model)

- **Network**: A group of stations (e.g., “National AWS Network”).
- **Station**: One observing site with metadata (location, WIGOS ID, heights…).
- **Network Connection**: A configured “pipe” to a data source. You select the **plugin** type here.
- **Station Link**: Binds a Station to a Connection and stores per-station settings (provider station code, timezone, *
  *variable mappings**).
- **Parameter & Unit**: ADL’s canonical variables (e.g., *air_temperature, °C*). Enable consistent **unit conversion**.
- **ObservationRecord**: A single saved datapoint: *(time, station, connection, parameter, value)*.

---

## What Does a Plugin Actually Do?

One thing: **fetch station records for a time window** and return them as dictionaries.

ADL calls:

```python
get_station_data(station_link, start_date, end_date) -> Iterable[Dict[str, Any]]
```

You return rows like:

```python
{
    "observation_time": datetime(...),  # timestamp (aware or naive; see timezone rules)
    "temp_K": 293.15,  # any number of source fields
    "rh": 75.0,
}
```

ADL will:

- Match source fields to Station Link **variable mappings** (e.g., `temp_K → air_temperature`).
- Convert units when needed (e.g., **K → °C**).
- **Upsert** into the database (safe to re-fetch overlaps).

---

## The Ingestion Flow

1. **Scheduling**  
   Celery triggers a **Network Connection** on its interval.

2. **Station Loop**  
   For each **enabled** Station Link:
    - ADL computes a station-local **time window**:
        - Prefer **latest saved timestamp** (resume from last ingest),
        - Else **Station’s first collection date** (if provided),
        - Else a **default 1-hour window** ending at the next hour.
    - Window is **aligned to hour boundaries** (e.g., 10:00–11:00 local time).

3. **Plugin Fetch**  
   ADL calls your `get_station_data(...)` with that window.

4. **Normalize & Save**  
   ADL normalizes timestamps, applies mappings and unit conversions, then **upserts** `ObservationRecord`s.

5. **Dispatch (Optional)**  
   Separate “dispatch channels” (e.g., WIS 2.0 uploader) can push stored data onward.

---

## Timezones & Timestamps (Rules)

- ADL prefers **aware datetimes** (with `tzinfo`).
- If your record timestamp is:
    - **Aware**: ADL converts it correctly to the station’s timezone.
    - **Naive**: ADL **assumes it’s station-local**.
- The fetch window you receive is already **station-local** and **hour-aligned**.
- Storage is consistent so comparisons and queries are unambiguous.

---

## Units & Variable Mappings

- In the Station Link UI, you define rows like:  
  **air_temperature (°C)** ← **temp_K** (source unit **K**)
- On save, ADL uses `DataParameter.convert_value_from_units()` to convert (e.g., **m/s → km/h**, custom contexts for
  tricky conversions like precipitation mass/height).
- If a value is missing for a source field, ADL skips that parameter for that record and continues.

---

## Where Does It Run?

**Docker Compose** typically runs:

1. **TimescaleDB** (PostgreSQL + time-series features)
2. **Redis**
3. **ADL Web** (Django + your plugin code, hot reload)
4. **Celery Worker/Beat** (background jobs)

You control everything with `docker compose up`, and configure via the **Wagtail admin**.

---

## Day-One Checklist for a New Plugin

1. **Scaffold** from the cookiecutter boilerplate.
2. **Add models** for your provider:
    - `NetworkConnection` subclass (credentials, base URL, etc.)
    - `StationLink` subclass (provider station code, per-station mappings)
3. **Implement** `get_station_data()`:
    - Fetch between `start_date` and `end_date`
    - Return records with `"observation_time"` and source fields named to match your mappings
4. **Register** your plugin in `apps.py` using `plugin_registry.register(...)`.
5. **Run** the stack, create a Connection (select your plugin type), add Station Links, set mappings, watch data land in
   the DB.

---

## Common Questions

- **Do I write database code?**  
  No — just return records. ADL saves them (with upsert).

- **What about pagination/rate limits?**  
  Handle those inside `get_station_data()`. ADL only cares about the result shape.

- **How do I map fields?**  
  Ensure your Station Link mappings use the **exact source field names** you return.

- **Different units per station?**  
  Fine. Each mapping row stores its source unit; ADL converts per row.

- **Can I re-fetch the same window?**  
  Yes. Upsert prevents duplicates from crashing ingestion.

- **Timestamps look off…**  
  Return **aware** datetimes when possible. If naive, ADL interprets as **station-local**. Also verify the Station Link
  timezone.

---

> **TL;DR**: *Your plugin fetches raw rows for a time window. ADL handles the windowing, timezone normalization, unit
conversion, and saving.*
