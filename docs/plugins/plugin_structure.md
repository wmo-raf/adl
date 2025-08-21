# Plugin Structure

An ADL Plugin is fundamentally a folder named after the plugin. The folder should be
a [Django/Wagtail App](https://docs.djangoproject.com/en/5.1/ref/applications/).

This section explains the typical file/folder layout of an ADL plugin, what each file does, and how it plugs into the
ADL Core runtime (Django + Wagtail + Celery + TimescaleDB).

## Initialize your plugin from the plugin template

The plugin template is a [cookiecutter](https://cookiecutter.readthedocs.io/en/stable/installation.html) template that
generates a plugin with the required structure and files. This ensures that the plugin follows the expected structure
and can be easily installed into the adl core application.

With the plugin boilerplate you can easily create a new plugin and setup a docker development environment that installs
ADL as a dependency. This can easily be installed via cookiecutter.

To instantiate the template, execute the following commands from the directory where you want to create the plugin:

```sh
pip install cookiecutter
cookiecutter gh:wmo-raf/adl --directory plugin-boilerplate
```

For more details on using the plugin boilerplate, you can check * :doc:`plugins/plugin_boilerplate` on
creating a plugin using the plugin boilerplate.

## Plugin Installation API

A adl docker image contains the following bash scripts that are used to install plugins. They can be used
to install a plugin into an existing adl container at runtime. `install_plugin.sh` can be used to install a
plugin from an url, a git repo or a local folder on the filesystem.

You can find these scripts in the following locations in the built images:

1. `/adl/plugins/install_plugin.sh`

On this repo, you can find the scripts in the `deploy/plugins` folder.

These scripts expect an adl plugin to follow the conventions described below:

## Plugin File Structure

The `install_plugin.sh` script expect your plugin to have a specific structure as follows:

```
├── plugin_name
│  ├── adl_plugin_info.json (A simple json file containing info about your plugin)
|  ├── setup.py
|  ├── build.sh (Called when installing the plugin in a Dockerfile/container)
|  ├── runtime_setup.sh (Called on first runtime startup of the plugin)
|  ├── uninstall.sh (Called when uninstalling the plugin in a container)
|  ├── src/plugin_name/src/config/settings/settings.py (Optional Django setting file)
```

The folder contains three bash files which will be automatically called by adl's plugin scripts during
installation and uninstallation of the plugin. You can use these scripts to perform extra build steps, installation of
packages and other docker container build steps required by your plugin.

1. `build.sh`: Called on container startup if a runtime installation is occurring.
2. `runtime_setup.sh`: Called the first time a container starts up after the plugin has been installed, useful for
   running superuser commands on the container.
3. `uninstall.sh`: Called on uninstall, the database will be available and so any backwards migrations should be run
   here.

## The plugin info file

The `adl_plugin_info.json` file is a json file, in your root plugin folder, containing metadata about your
plugin. It should have the following JSON structure:

```json
{
  "name": "TODO",
  "version": "TODO",
  "description": "TODO",
  "author": "TODO",
  "author_url": "TODO",
  "url": "TODO",
  "license": "TODO",
  "contact": "TODO"
}
```

## Top-Level Layout (cookiecutter result)

```text
plugin-root/
├─ cookiecutter.json                      # (only in the boilerplate template repo)
├─ {{ project_slug }}/                    # concrete plugin project root (e.g., adl-tahmo-plugin/)
│  ├─ README.md
│  ├─ dev.Dockerfile
│  ├─ docker-compose.yml
│  ├─ .env.sample
│  └─ plugins/
│     └─ {{ project_module }}/            # e.g., adl_tahmo_plugin/
│        ├─ adl_plugin_info.json
│        ├─ build.sh
│        ├─ runtime_setup.sh
│        ├─ uninstall.sh
│        ├─ Makefile
│        ├─ MANIFEST.in
│        ├─ pyproject.toml
│        ├─ setup.py
│        ├─ .flake8
│        ├─ requirements/
│        │  ├─ README.md
│        │  ├─ base.in
│        │  ├─ base.txt
│        │  ├─ dev.in
│        │  └─ dev.txt
│        └─ src/                          # Python package code
│           ├─ __init__.py
│           └─ {{ project_module }}/
│              ├─ __init__.py
│              ├─ apps.py                 # Register plugin into ADL at Django startup
│              ├─ plugins.py              # Your Plugin subclass (core ingestion logic)
│              ├─ models.py               # Optional: connection/station link/mappings
│              ├─ views.py                # Optional: admin/ajax helpers
│              ├─ widgets.py              # Optional: Wagtail admin widgets
│              ├─ wagtail_hooks.py        # Optional: admin URL registration, menus
│              ├─ client.py               # Optional: API/Database etc client wrapper(s)
│              ├─ utils.py                # Optional: helpers
│              ├─ validators.py           # Optional: input validators
│              ├─ migrations/             # If you define models
│              │  ├─ 0001_initial.py
│              │  └─ __init__.py
│              └─ config/
│                 └─ settings/
│                    ├─ __init__.py
│                    └─ settings.py       # setup(settings): late changes to Django settings
```

> **Note**: Exact names come from cookiecutter variables: `project_name`, `project_slug`, `project_module`.

---

## Docker & Runtime Integration

### `dev.Dockerfile`

- **Base image**: `FROM adl:latest` (inherits ADL Core with Django/Celery/etc.).
- **User/permissions**: Uses `PLUGIN_BUILD_UID/GID` so mounted volumes are writable from your host.
- **Installs dev deps**: from `requirements/dev.txt` (linters, build tools).
- **Installs the plugin**: Copies your code under `/adl/plugins/<module>/` then runs
  `/adl/plugins/install_plugin.sh --dev` (provided by ADL Core) to install and register it in the ADL virtualenv.

### `docker-compose.yml`

Defines a **dev stack**:

- `adl_db`: TimescaleDB/PostgreSQL for time-series data.
- `adl_redis`: Redis for Celery broker/locks.
- `adl`: Django web app (ADL Core + your plugin); mounts your plugin for **hot reload**.
- `adl_celery_worker`: Celery worker.
- `adl_celery_beat`: Celery beat (schedules).

### `.env.sample`

Template for runtime values. Copy to `.env` and set:

- `PLUGIN_BUILD_UID`, `PLUGIN_BUILD_GID` (use `id -u` / `id -g`)
- `ADL_DB_USER`, `ADL_DB_PASSWORD`, `ADL_DB_NAME`
- `PORT`

---

## Packaging & Metadata

### `setup.py` / `pyproject.toml`

Standard Python packaging. `setup.py` points to the `src/` layout and reads dependencies from `requirements/base.txt`.

### `MANIFEST.in`

Include non-Python assets (templates, static files, locales) in the distribution.

### `requirements/` (managed with **pip-tools**)

- `base.in` → compiled to `base.txt` (runtime deps installed into the image)
- `dev.in` → compiled to `dev.txt` (linters, build/test tools)

### `adl_plugin_info.json`

Human-friendly plugin metadata used by ADL (name, version, author, URLs, license, contact).

---

## Lifecycle Scripts

- **`build.sh`** — Runs at plugin **build time** (during Docker image build or explicit plugin build). Put
  *install-time* tasks here (e.g., OS libs, non-Python tools). **Do not** touch the ADL data volume here.
- **`runtime_setup.sh`** — Runs **on first container start** with the plugin installed (must be **idempotent**). Put
  *runtime* tasks here that require the DB or data volume (e.g., creating extensions, seeding reference data). Use
  `PLUGIN_RUNTIME_SETUP_MARKER` to guard reruns.
- **`uninstall.sh`** — Runs when uninstalling the plugin. Reverse side effects not handled by Django migrations (custom
  DB schema, hypertables, etc.). Python package uninstall is handled by ADL automatically.

---

## Django App Layer (`src/<module>/`)

### `apps.py` — Register your plugin

```python
from django.apps import AppConfig
from adl.core.registries import plugin_registry
from .plugins import MyPlugin


class MyPluginConfig(AppConfig):
    name = "my_plugin"
    
    def ready(self):
        plugin_registry.register(MyPlugin())
```

- Registration makes your plugin discoverable via `NetworkConnection.plugin` (string `type`).

### `plugins.py` — The Plugin class

Subclass ADL’s base `Plugin` and implement **ingestion**:

```python
from adl.core.registries import Plugin


class MyPlugin(Plugin):
    type = "my_plugin"  # stable identifier
    label = "My Plugin"  # human-readable name
    
    def get_station_data(self, station_link, start_date=None, end_date=None):
        # Fetch provider data in [start_date, end_date) (station-local aware datetimes)
        # Return iterable of dicts with at least "observation_time" + source fields
        return [
            {"observation_time": some_dt, "temp_K": 293.15, "rh": 75.0},
            # ...
        ]
```

> **Best practice**: Let the base class **persist** via `save_records()` (it handles timezone normalization, unit
> conversion, and bulk upsert). You just return raw rows.

### `models.py` — Plugin models

Typical plugin models:

- **`NetworkConnection` subclass**: provider credentials/config (API keys, base URL, batching, daily vs hourly).
- **`StationLink` subclass**: per-station config (provider station code, timezone, first-collection date, **variable
  mappings**).
- **Mapping model**: map ADL parameters → provider field names + source units.

**Recommended mapping attribute names** (so `save_records()` works out of the box):

- `adl_parameter` → `DataParameter` instance (target variable in ADL)
- `source_parameter_name` → provider field key you will return in `get_station_data()`
- `source_parameter_unit` → `Unit` instance representing provider’s unit

If your field names differ (e.g., `tahmo_variable_shortcode`), either:

- expose properties that alias to the expected names, or
- override `StationLink.get_variable_mappings()` to yield objects with those attributes.

### `wagtail_hooks.py` / `views.py` / `widgets.py`

- Add **admin endpoints** (AJAX lists, metadata pages) or custom Wagtail form widgets to improve connection/station
  configuration UX.
- Examples:
    - Endpoints listing provider stations/variables via your `client.py`.
    - Widgets that call those endpoints and render searchable selects.

### `client.py`

Provider-specific connection logic (auth, retries, pagination, caching). Keep API logic here and call it from
`get_station_data()` or admin views.

The file can be named anything to match your provider connection mechanism. For example `db.py` for a database
connection, `http.py` for an HTTP API, `ftp.py` for an FTP server, etc.

### `config/settings/settings.py`

Late-binding hook ADL calls during settings init:

```python
def setup(settings):
    # e.g., settings.INSTALLED_APPS += ["my_extra_dep"]
    pass
```

### `migrations/`

Include migrations if you define models (standard Django workflow).

---

## How the pieces work together

1. **Django starts** → `apps.py.ready()` registers your plugin in the **plugin registry**.
2. In the admin, a user creates a **Network Connection** and selects your plugin by `type`.
3. They create **Station Links**, define **variable mappings** (ADL parameter + source field + unit), and set
   per-station options (timezone, start date).
4. Celery (or a manual action) triggers `NetworkConnection.collect_data()` → ADL calls `plugin.run_process(conn)`.
5. For each enabled Station Link, ADL computes a **station-local** time window and calls your `get_station_data()`.
6. ADL’s base `save_records()` performs **unit conversion, timezone normalization, and bulk upsert** into
   `ObservationRecord`.

---

## Naming & Conventions

- `type` (plugin ID) must be **stable** and globally unique (often your package name, e.g., `adl_tahmo_plugin`).
- Keep **source field names** in your results exactly matched to mapping rows’ `source_parameter_name`.
- Return **aware** datetimes when possible; if naive, they’re interpreted as **station-local**.
- Use the module logger (`logging.getLogger(__name__)`) for clear, prefixed logs.

---

## Directory-by-Directory Cheatsheet

- `plugins/<module>/src/<module>/plugins.py` — your `Plugin` subclass; implement `get_station_data()`.
- `plugins/<module>/src/<module>/apps.py` — register the plugin at startup.
- `plugins/<module>/src/<module>/models.py` — `NetworkConnection`, `StationLink`, and mapping models.
- `plugins/<module>/src/<module>/client.py` — HTTP API wrapper(s). Could be named `db.py`, `ftp.py`, etc. for
  database, FTP, or other connections.
- `plugins/<module>/src/<module>/wagtail_hooks.py` — admin URLs & integration.
- `plugins/<module>/src/<module>/views.py` — admin AJAX endpoints or pages.
- `plugins/<module>/src/<module>/widgets.py` — custom admin widgets.
- `plugins/<module>/src/<module>/validators.py` — reusable validation helpers.
- `plugins/<module>/src/<module>/config/settings/settings.py` — late settings hook.
- `plugins/<module>/requirements/` — dependency specs (pip-tools).
- `plugins/<module>/build.sh` — build-time tasks.
- `plugins/<module>/runtime_setup.sh` — one-time runtime initialization.
- `plugins/<module>/uninstall.sh` — cleanup on uninstall.
- `dev.Dockerfile` — dev image that installs your plugin into ADL.
- `docker-compose.yml` — local dev stack (DB, Redis, app, Celery).
- `.env.sample` — template env file for local runs.
- `adl_plugin_info.json` — plugin metadata (name, version, URLs).

---

## Minimal Working Set (if you’re in a hurry)

- `plugins/<module>/src/<module>/plugins.py` — implement `get_station_data()`
- `plugins/<module>/src/<module>/apps.py` — register the plugin
- `plugins/<module>/src/<module>/models.py` — define a `NetworkConnection`, `StationLink`, and mappings
- `dev.Dockerfile`, `docker-compose.yml`, `.env.sample` — to run locally
- `setup.py`, `MANIFEST.in`, `requirements/` — to package/install

With just these, you can fetch, normalize, and store observations end-to-end.

---

## Extensibility Hooks (optional)

- `Plugin.get_urls()` — expose plugin-specific URLs (health checks, manual triggers).
- `Plugin.get_default_start_date()` / `get_default_end_date()` — customize cadence (e.g., daily at 00:00).
- `StationLink.get_first_collection_date()` — provider-specific history fallback.
- **Dispatch channels** (outside the plugin): push saved data to WIS2, MQTT, WIS2Box, etc.

---

## Quick Validation Checklist

- [ ] `apps.py` registers **one** instance: `plugin_registry.register(MyPlugin())`
- [ ] `type` is unique and stable
- [ ] `get_station_data()` returns dicts with `"observation_time"` + mapped source fields
- [ ] Station-link mappings expose `.adl_parameter`, `.source_parameter_name`, `.source_parameter_unit`
- [ ] Units are `Unit` objects; ADL converts to the `DataParameter`’s unit
- [ ] Timestamps are aware (preferred) or valid station-local naive
- [ ] Use base `save_records()` for persistence (bulk upsert)
- [ ] Secrets/base URLs live in `NetworkConnection` or `.env`
- [ ] Dev stack works: `docker compose build && docker compose up`

---

**In short**: a plugin is a normal Django app packaged into the ADL image that registers a `Plugin` subclass. You
provide the fetch logic; ADL handles time-windowing, unit conversion, timezone normalization, and storage.

