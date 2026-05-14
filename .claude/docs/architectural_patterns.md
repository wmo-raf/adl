# Architectural Patterns

## 1. Registry Pattern

**Files:** `adl/src/adl/core/registry.py` (base), `adl/src/adl/core/registries.py`, `adl/src/adl/core/qc/registry.py`

A generic `Registry`/`Instance` pair (`core/registry.py:1-168`) underpins all extensibility. Registries hold a dict of
`type_string → class`, and instances carry a `.type` attribute matching that key. Concrete registries:

- `PluginRegistry` (`registries.py`) — registers data-source plugins
- `QCValidatorRegistry` (`qc/registry.py`) — registers QC check types
- `ViewSetRegistry` — registers Wagtail admin viewsets

Each registered class can implement `after_register()` to run setup logic when added to the registry.

## 2. Plugin Architecture

**Files:** `adl/src/adl/core/registries.py:1-1093`

All data sources are plugins — separate installable Python packages that subclass `Plugin` and register themselves. The
`Plugin` base class defines the contract:

- **`get_station_data(station_link, start_date, end_date)`** — **must override**; yields/returns raw observation records
- **`after_save_records(station_link, records)`** — hook called after records are upserted; optional override
- **`get_urls()`** — optional; return URL patterns to add to Django's router
- **`get_default_start_date()` / `get_default_end_date()`** — default collection window
- **`get_start_date_from_db(station_link)`** — resumes from the last stored timestamp

Built-in behavior in `Plugin.save_records()` (`registries.py`): QC pipeline application, chunked upserts (
`SAVE_CHUNK_SIZE`), timezone normalization to UTC, and `TaskLogger` audit entries — plugins get all this for free.

New plugins are scaffolded using the Cookiecutter template in `plugin-boilerplate/`.

## 3. Polymorphic Models

**File:** `adl/src/adl/core/models.py`

Three core models use `django-polymorphic` to allow subclassing at the database level:

- `NetworkConnection` — base for vendor-specific connection configs (FTP, HTTP, DB, etc.)
- `StationLink` — base for vendor-specific per-station configuration
- `DispatchChannel` — base for push targets (WIS2Box, FTP, CDMS, etc.)

Plugins define their own concrete subclasses of these. Querying the base model returns instances of the correct subclass
automatically.

## 4. QC Pipeline

**Files:** `adl/src/adl/core/qc/pipeline.py`, `adl/src/adl/core/qc/validators.py`, `adl/src/adl/core/qc/registry.py`

Quality control is a composable, weighted validator chain:

1. `QCValidator` — base class; subclasses implement `validate(value, context) → result`
2. `QCPipeline` (`pipeline.py`) — holds an ordered list of validators with weights; runs them and aggregates a final QC
   flag
3. Built-in validators (`validators.py`): `RangeValidator`, `StepValidator`, `PersistenceValidator`, `SpikeValidator`
4. Pipelines are cached per `(parameter_id, modified_at)` to avoid rebuilds on every record

QC configuration is stored in a Wagtail `StreamField` on `DataParameter`, allowing admin users to configure checks
without code changes. Triggered inside `Plugin.save_records()`.

## 5. Celery Task Coordination

**File:** `adl/src/adl/core/tasks.py`

Ingestion and dispatch follow a coordinator → batch subtask pattern:

- `run_network_plugin()` — coordinator; enqueues `run_station_link_batch()` subtasks per station group
- `run_station_link_batch()` — processes a batch of stations, calling the plugin's `get_station_data()`
- `run_dispatch_channel()` — orchestrates data push for a single dispatch channel
- `run_backup()` — uses Celery Singleton to prevent concurrent duplicate runs

Schedules are managed via `django-celery-beat` (stored in DB, editable in admin). Each task logs structured activity
entries to `StationLinkActivityLog` (`monitoring/models.py`) via `TaskLogger`.

## 6. TaskLogger / Audit Trail

**File:** `adl/src/adl/core/logging.py:1-88`

`TaskLogger` is a context-scoped logger that writes structured entries to the monitoring database. Instantiated with
either a Celery `task_id` or a `plugin_label`. Used throughout `Plugin` base methods and Celery tasks so every ingestion
run has a queryable activity log.

## 7. Dispatcher Pattern

**Files:** `adl/src/adl/core/dispatchers/__init__.py`, `adl/src/adl/core/dispatchers/wis2box.py`

Data dispatch is also extensible via `DispatchChannel` polymorphism (see §3). The dispatcher module provides shared
utilities:

- `get_station_channel_records()` — filters `ObservationRecord` by channel config, time range, and parameter mappings
- `get_dispatch_channel_data()` — aggregates records by station and timestamp
- Channel parameter mappings translate internal `DataParameter` keys to the external schema expected by the target
  system

## 8. Wagtail Admin Integration

**Files:** `adl/src/adl/core/wagtail_hooks.py`, `adl/src/adl/core/viewsets.py`,
`adl/src/adl/monitoring/wagtail_hooks.py`

- `AdletViewSet` — project base viewset extending Wagtail's `ModelAdmin`; all domain admin views inherit from it
- Plugins register their own viewsets via `ViewSetRegistry` so their config panels appear in the admin without modifying
  core code
- `ClusterableModel` (modelcluster) is used on domain models (`Network`, `Station`, etc.) to enable nested inline
  editing in Wagtail panels
- Bulk actions (`core/bulk_actions/`) hook into Wagtail's bulk-action framework for batch enable/disable of stations

## 9. Timezone Handling

**Files:** `adl/src/adl/core/date_utils.py`, `adl/src/adl/core/registries.py`

All `ObservationRecord` timestamps are stored as UTC. Station models carry a `timezone` field (`TimeZoneField`)
representing local time. Plugin methods (`get_default_start_date`, `get_default_end_date`, `get_start_date_from_db`)
return timezone-aware local datetimes. `make_record_timezone_aware()` in `date_utils.py` converts naive datetimes before
upsert.

## 10. Settings Hierarchy

**Files:** `adl/src/adl/config/settings/base.py`, `dev.py`, `production.py`

Standard Django split-settings pattern with `django-environ`:

- `base.py` — shared config; reads `.env` via `environ.Env()`; dynamically appends plugin package names to
  `INSTALLED_APPS`
- `dev.py` / `production.py` — override base with environment-specific values

Plugin package names are injected into `INSTALLED_APPS` at runtime from an environment variable, so installing a new
plugin requires no code change to core settings.