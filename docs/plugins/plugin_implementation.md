# Plugin Implementation

This section walks you through implementing a **data-source plugin** for the ADL (Automated Data Loader) platform using
the **TAHMO** API as a concrete, end-to-end example. It assumes minimal Django experience and explains the plugin
contract, file layout, model definitions, views, widgets, date handling, saving observations, and testing.

---

## 1) What is an ADL Plugin? (Quick refresher)

An ADL plugin is a **Django app** that knows how to:

1. **Connect** to a specific upstream data source (API, database, file feed, etc.).
2. **Fetch** observations for one or more stations within a time window.
3. **Normalize** and **save** those observations into ADL’s core database schema.
4. (Optionally) provide **admin UI** helpers like station pickers and custom views.

Plugins implement a **contract** (a base class called `Plugin`) that the ADL core can call on a schedule or on demand.

---

## 2) The Plugin Contract (Core Expectations)

Every plugin must inherit from `adl.core.registries.Plugin` (your code may import it as
`from adl.core.registries import Plugin`). The **minimum responsibilities** are:

- **Set**: a human-readable plugin name for logs and admin UI.
- **Implement**: returns raw records for one station between the two timestamps.
- (The base class already implements helpful utilities: date window helpers, saving, orchestration.)

### 2.1 `get_station_data(self,station_link,start_date,end_date)` Input

- `station_link`: a `StationLink` subclass instance for the upstream system (e.g., `TahmoStationLink`). It carries
  station configuration and mappings.
- `start_date`, `end_date`: timezone-aware datetimes in the **station’s timezone** that define a **closed-open**
  half-open interval `[start_date, end_date)`. ADL will decide these for you via `get_dates_for_station` unless you need
  to override.

> Tip: If ADL passes in **naive** datetimes, the base class normalizes them to the station timezone.

### 2.2 `get_station_data()` Output (must follow this schema)

Return an **iterable of dicts**. Each dict is a single time step and **must** include:

- `observation_time`: `datetime` – can be naive (interpreted as station-local) or aware (will be normalized).

It **may** also include any number of **source-parameter fields** whose names match your station’s **variable mapping**.
Example:

```python
{
    "observation_time": datetime(2025, 1, 1, 10, 0),  # station local (naive ok)
    "temp_K": 293.15,
    "rh": 55.2,
    "wind_speed_ms": 3.4,
}
```

The base `Plugin.save_records()` method will:

- Look up the station’s **variable mappings** (e.g., `source_parameter_name` → ADL `DataParameter`).
- Perform **unit conversion** if the upstream unit differs from ADL’s canonical unit for the parameter.
- **Upsert** (`bulk_create(update_conflicts=True)`) `ObservationRecord` rows keyed by
  `(time, station, connection, parameter)`.

> If you prefer to save manually, you can override `save_records`, but the default handles most cases.

---

## 3) Plugin Folder Structure (tahmo example for reference)

A typical plugin lives under `plugins/<your_plugin_slug>/`. The TAHMO example ships like this (abridged):

```{note}
For complete code reference, see the [ADL TAHMO Plugin](https://github.com/wmo-raf/adl-tahmo-plugin)
```

```
plugins/adl_tahmo_plugin/
├─ src/adl_tahmo_plugin/
│  ├─ apps.py                      # AppConfig registers the Plugin in the registry
│  ├─ client.py                    # Thin HTTP client for the TAHMO API
│  ├─ models.py                    # NetworkConnection + StationLink + Mapping models
│  ├─ plugins.py                   # The Plugin subclass (TahmoPlugin)
│  ├─ validators.py                # Field validators (e.g., “start_date must be past”)
│  ├─ views.py                     # JSON endpoints + admin views
│  ├─ widgets.py                   # Custom admin widgets for async selects
│  ├─ wagtail_hooks.py             # Admin URLs for the above views
│  ├─ config/settings/settings.py  # Optional settings hook
│  └─ migrations/                  # Standard Django migrations
├─ requirements/                   # Dev/base requirements (pip-tools friendly)
├─ setup.py / pyproject.toml       # Python packaging metadata (installed by ADL)
├─ build.sh / runtime_setup.sh     # Lifecycle hooks called by ADL
└─ dev.Dockerfile + docker-compose.yml
```

---

## 4) Models for TAHMO (how the plugin stores configuration)

### 4.1 `TahmoConnection`

Subclass of `adl.core.models.NetworkConnection`. Holds credentials and any connection-wide options.

```python
# src/adl_tahmo_plugin/models.py (excerpt)

from django.db import models
from adl.core.models import NetworkConnection
from .client import TahmoAPIClient


class TahmoConnection(NetworkConnection):
    api_key = models.CharField(max_length=255, verbose_name="API Key")
    api_secret = models.CharField(max_length=255, verbose_name="API Secret")
    
    def get_api_client(self):
        return TahmoAPIClient(api_key=self.api_key, api_secret=self.api_secret)
```

### 4.2 `TahmoStationLink`

Subclass of `adl.core.models.StationLink`. Binds one ADL `Station` to its TAHMO station code, custom timezone, and
optional **historic start date** for backfills.

```python
from adl.core.models import StationLink
from django.db import models

from .validators import validate_start_date


class TahmoStationLink(StationLink):
    tahmo_station_code = models.CharField(max_length=255, verbose_name="Tahmo Station")
    start_date = models.DateTimeField(
        blank=True, null=True, validators=[validate_start_date],
        help_text="Select a past date to include historical data."
    )
    
    def __str__(self):
        return f"{self.tahmo_station_code} - {self.station} - {self.station.wigos_id}"
```

### 4.3 `TahmoStationLinkVariableMapping`

Maps **TAHMO variable shortcode** to an ADL `DataParameter` and the **source unit**.

```python
from adl.core.models import DataParameter, Unit
from django.db import models
from wagtail.models import Orderable
from modelcluster.fields import ParentalKey


class TahmoStationLinkVariableMapping(Orderable):
    station_link = ParentalKey(TahmoStationLink, related_name="variable_mappings", on_delete=models.CASCADE)
    adl_parameter = models.ForeignKey(DataParameter, on_delete=models.CASCADE)
    tahmo_variable_shortcode = models.CharField(max_length=255)
    tahmo_parameter_unit = models.ForeignKey(Unit, on_delete=models.CASCADE)
```

> These mappings enable `Plugin.save_records()` to find the right ADL parameter and convert units automatically.

---

## 5) Admin UX: Widgets, Views & Wagtail Hooks (optional but helpful)

To make station setup ergonomic, the TAHMO plugin provides **AJAX-powered selects** for stations and variables.

- **Widgets** (`widgets.py`) define custom form rendering and pass URLs to the template.
- **Views** (`views.py`) provide JSON lists (`/adl-tahmo-plugin/tahmo-conn-stations/`,
  `/adl-tahmo-plugin/tahmo-conn-variables/`).
- **wagtail_hooks.py** registers those URLs in the Wagtail admin.

Example view (stations list for a connection):

```python
def get_tahmo_stations_for_connection(request):
    connection_id = request.GET.get('connection_id')
    network_conn = get_object_or_none(TahmoConnection, pk=connection_id)
    stations = get_stations(network_conn)  # calls client.get_stations()
    return JsonResponse(stations, safe=False)
```

---

## 6) The TAHMO API Client (fetching upstream data)

The `TahmoAPIClient` wraps the HTTP calls, authentication, optional caching, and response normalization.

Key methods:

- `get_stations()` → dict keyed by station code
- `get_variables()` → dict keyed by variable shortcode
- `get_measurements(station_code, start, end, ...)` → list of dict rows with `time`, `variable`, `value`, etc.

The client **deduplicates and pivots** results into a list like:

```python
[
    {"datetime": "2025-01-01T10:00:00Z", "rh": 55.0, "temp_K": 293.15},
    {"datetime": "2025-01-01T11:00:00Z", "rh": 52.0, "temp_K": 296.15},
]
```

> Note: it multiplies relative humidity by 100 when TAHMO returns decimal fractions.

---

## 7) Implementing the Plugin Class

Your plugin subclass advertises a **type string** (registry key) and **label**, then implements `get_station_data` (or
in the existing TAHMO code, a slightly older `get_data/process_station_link` pair). Below is a modern implementation
aligned with the **base ****\`\`**** contract**.

> If you already have `get_data()` and `process_station_link()` as in the provided TAHMO code, you can refactor to
`get_station_data()` and rely on the base class for orchestration and saving.

### 7.1 Minimal `get_station_data` for TAHMO

```python
# src/adl_tahmo_plugin/plugins.py
import logging
from adl.core.registries import Plugin

logger = logging.getLogger(__name__)


class TahmoPlugin(Plugin):
    type = "adl_tahmo_plugin"
    label = "ADL TAHMO Plugin"
    
    def get_station_data(self, station_link, start_date=None, end_date=None):
        start_date_utc_format = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_date_utc_format = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        tahmo_http_client = station_link.network_connection.get_api_client()
        
        records = tahmo_http_client.get_measurements(
            station_link.tahmo_station_code,
            start_date=start_date_utc_format,
            end_date=end_date_utc_format
        )
        
        return records
```

### 7.2 Rely on Base Class for Orchestration & Saving

The base class will:

- Pick **start/end** via `get_dates_for_station()`:
    - Resume from last saved observation if present,
    - else use station’s first collection date (`StationLink.get_first_collection_date()`),
    - else default to “previous hour window”.
- Call your `get_station_data()` with that window.
- Call `save_records()` to upsert into `ObservationRecord`.

So a typical “collect all stations” call is just:

```python
results = TahmoPlugin().run_process(tahmo_connection)
# results is a dict {station_id: saved_count}
```

---

## 8) Mapping, Units & Saving (what happens under the hood)

When you configured a station, you added **variable mappings** on `TahmoStationLinkVariableMapping`:

- `tahmo_variable_shortcode` → matches the **key** you put on each record (e.g., `"temp_K"`).
- `adl_parameter` → points to an ADL `DataParameter` which has a **canonical Unit**.
- `tahmo_parameter_unit` → the **source Unit** (e.g., Kelvin vs. Celsius).

During `save_records()` the plugin will:

1. Ensure `observation_time` is a `datetime` (normalize to station tz).
2. For each **mapping**, look up `value = record[mapping.source_parameter_name]`.
3. If `mapping.adl_parameter.unit != mapping.source_parameter_unit`, convert using
   `DataParameter.convert_value_from_units(...)`.
4. Upsert `ObservationRecord(time, station, connection, parameter) → value`.

> This is why the **record keys must exactly** match your `source_parameter_name` / shortcode.

---

## 9) Timezones & Date Windows (common pitfalls)

- ADL stores datetimes in UTC in the DB, but the plugin API always works in the **station timezone** for convenience.
- `get_default_end_date()` returns **top of next hour** in the station tz (so your hour window ends nicely). This can be
  overridden if you need a different logic for your data source.
- If there’s no prior data and no custom start date, ADL defaults to the **previous hour**.
  accordingly.

**Golden rule**: In `get_station_data`, convert any upstream timestamps to a **timezone-aware** station-local `datetime`
before returning.

---

## 10) Registering Your Plugin with ADL

Your plugin must register itself with the registry inside `AppConfig.ready()`:

```python
# src/adl_tahmo_plugin/apps.py
from django.apps import AppConfig
from adl.core.registries import plugin_registry


class PluginNameConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = "adl_tahmo_plugin"
    
    def ready(self):
        from .plugins import TahmoPlugin
        plugin_registry.register(TahmoPlugin())
```

> The `type = "adl_tahmo_plugin"` must be **unique** across all installed plugins.

---

## 11) End-to-End Flow (TAHMO)

1. **Admin** creates a `TahmoConnection`, entering API key/secret.
2. **Admin** creates a `TahmoStationLink` for each ADL station (selects a TAHMO station code, timezone, optional start
   date).
3. **Admin** adds one or more **variable mappings** (e.g., `temp_K` → `air_temperature` in Celsius, `rh` →
   `relative_humidity` in %).
4. A **scheduled task** or manual action calls `connection.collect_data()`:
    - ADL resolves the registered plugin and calls `run_process(connection)`.
    - Plugin computes the date window.
    - Plugin calls TAHMO API and returns records in the contract format.
    - Base class saves records, converting units as necessary.
5. Data appears in `ObservationRecord` and in admin/reporting UIs.

---

## 12) Troubleshooting

- **No records saved**: Ensure your `get_station_data()` returns keys matching the mapping’s `source_parameter_name` (
  e.g., `"temp_K"`). Ensure you returned `observation_time` for each row.
- **Unit conversion errors**: Confirm the `Unit` symbols match pint (e.g., `degC`, `K`, `m/s`, `mm`). If a special
  context is needed (e.g., precipitation mass/area), configure `DataParameter.custom_unit_context`.
- **Timezone confusion**: Check that your `observation_time` values are **aware** or are interpreted as station-local (
  naive is allowed but will be localized). Verify windows are `[start, end)` not inclusive of `end`.
- **Registry errors**: The `type` string must be unique. If tests register twice, allow overrides or reset the registry
  between tests.

---