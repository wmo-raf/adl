# Plugin Implementation

This guide walks through implementing a data-source plugin for ADL using the
[TAHMO](https://tahmo.org) API as a concrete, end-to-end example. Every code
snippet is taken directly from the real TAHMO plugin source.

By the end you will know how to:

- Define the models that hold your plugin's configuration
- Implement the `Plugin` subclass that fetches data
- Wire up the Wagtail admin (panels, widgets, custom views)
- Register your plugin so ADL can discover it
- Understand the date-window logic and where to override it

---

## 1. What Is an ADL Plugin?

An ADL plugin is a **Django app** that acts as an adapter between one upstream
data source (an HTTP API, FTP feed, database, serial port, etc.) and ADL's
internal observation store.

Your plugin is responsible for exactly one thing: **fetching raw records for a
station over a time window** and returning them as a list of dicts. ADL handles
everything else — scheduling, date windowing, timezone normalization, unit
conversion, upserts, and logging.

---

## 2. Core Concepts (Quick Refresher)

Before writing code it helps to have the object model clear:

| Concept               | What it is                                                                                                                          |
|-----------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| **Network**           | A group of stations sharing the same vendor/source                                                                                  |
| **NetworkConnection** | Credentials and config for one upstream data source; you pick the plugin type here                                                  |
| **StationLink**       | Binds one ADL `Station` to one `NetworkConnection`; holds per-station settings like the upstream station code and variable mappings |
| **DataParameter**     | ADL's canonical variable (e.g. `air_temperature`), always stored in a known unit                                                    |
| **Unit**              | A unit of measurement, used to drive automatic conversion                                                                           |
| **ObservationRecord** | One saved data point: `(time, station, connection, parameter, value)`                                                               |

Your plugin provides subclasses of `NetworkConnection` and `StationLink` (and
usually a related `Orderable` for per-variable mappings).

---

## 3. File Layout

Scaffold your plugin with the cookiecutter template
(see [Plugin Structure](plugin_structure.md)). The TAHMO plugin we are using for our example, uses this same layout:

```
plugins/adl_tahmo_plugin/
├── adl_plugin_info.json          # Plugin metadata (name, version)
├── build.sh                      # Called on container build/install
├── runtime_setup.sh              # Called on first container startup
├── uninstall.sh                  # Called on uninstall
├── setup.py / pyproject.toml     # Python packaging
├── requirements/
│   ├── base.txt
│   └── dev.txt
└── src/adl_tahmo_plugin/
    ├── apps.py                   # AppConfig — registers the plugin
    ├── client.py                 # HTTP client for the upstream API
    ├── models.py                 # Connection, StationLink, variable mapping
    ├── plugins.py                # Plugin subclass (the fetch logic)
    ├── utils.py                  # Shared helpers (e.g. build station list)
    ├── validators.py             # Field validators
    ├── views.py                  # JSON endpoints + admin views
    ├── wagtail_hooks.py          # Registers admin URLs
    ├── widgets.py                # Custom form widgets
    ├── config/settings/
    │   └── settings.py           # Optional Django settings hook
    └── templates/adl_tahmo_plugin/
        ├── metadata.html
        └── widgets/
            ├── tahmo_station_select_widget.html
            └── tahmo_variable_select_widget.html
```

```{note}

You can find the full source code for the TAHMO plugin at
[adl-tahmo-plugin](https://github.com/wmo-raf/adl-tahmo-plugin)

```

---

## 4. Models

### 4.1 `NetworkConnection` Subclass

Subclass `adl.core.models.NetworkConnection` to store the credentials and
options your plugin needs to connect to the upstream source.

```python
# src/adl_tahmo_plugin/models.py

from adl.core.models import NetworkConnection, StationLink, DataParameter, Unit
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import MultiFieldPanel, FieldPanel

from .client import TahmoAPIClient


class TahmoConnection(NetworkConnection):
    # Required: tells ADL which StationLink model belongs to this connection.
    # Must be an "app_label.ModelName" string.
    station_link_model_string_label = "adl_tahmo_plugin.TahmoStationLink"
    
    api_key = models.CharField(max_length=255, verbose_name="API Key")
    api_secret = models.CharField(max_length=255, verbose_name="API Secret")
    
    # Extend the base panels with your own fields
    panels = NetworkConnection.panels + [
        MultiFieldPanel([
            FieldPanel("api_key"),
            FieldPanel("api_secret"),
        ], heading=_("TAHMO API Credentials")),
    ]
    
    class Meta:
        verbose_name = "TAHMO API Connection"
        verbose_name_plural = "TAHMO API Connections"
    
    def get_api_client(self):
        """Convenience method — returns an authenticated client instance."""
        return TahmoAPIClient(api_key=self.api_key, api_secret=self.api_secret)
    
    def get_extra_model_admin_links(self):
        """
        Optional. Return extra action links shown in the connection's admin row.
        Each dict must have 'label', 'url', and optionally 'icon_name' and 'kwargs'.
        """
        return [
            {
                "label": _("View Metadata"),
                "url": reverse("tahmo_metadata_for_connection", args=[self.id]),
                "icon_name": "list-ul",
                "kwargs": {"attrs": {"target": "_blank"}},
            }
        ]
```

```{note}
`station_link_model_string_label` is **required**. ADL uses it to find the
correct `StationLink` subclass when rendering forms and running ingestion. If
you omit it, station links will not appear in the admin and data collection
will silently do nothing.
```

### 4.2 `StationLink` Subclass

Subclass `adl.core.models.StationLink` to store per-station configuration —
typically the upstream station identifier, a timezone override, and an optional
historic start date for backfills.

```python
from adl.core.models import StationLink
from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, InlinePanel

from .validators import validate_start_date
from .widgets import TahmoStationSelectWidget


class TahmoStationLink(StationLink):
    tahmo_station_code = models.CharField(
        max_length=255,
        verbose_name="Tahmo Station",
    )
    start_date = models.DateTimeField(
        blank=True,
        null=True,
        validators=[validate_start_date],
        verbose_name=_("Initial Collection Start Date"),
        help_text=_(
            "The date to start collecting data for the first run. "
            "Ignored if data has already been collected for this station."
        ),
    )
    
    panels = StationLink.panels + [
        FieldPanel("tahmo_station_code", widget=TahmoStationSelectWidget),
        FieldPanel("start_date"),
        InlinePanel(
            "variable_mappings",
            label=_("Station Variable Mapping"),
            heading=_("Station Variable Mappings"),
        ),
    ]
    
    class Meta:
        verbose_name = "TAHMO Station Link"
        verbose_name_plural = "TAHMO Stations Link"
    
    def __str__(self):
        return f"{self.tahmo_station_code} - {self.station} - {self.station.wigos_id}"
    
    def get_variable_mappings(self):
        return self.variable_mappings.all()
    
    def get_first_collection_date(self):
        """
        ADL calls this to determine where to start if no prior data exists.
        Return None to fall back to the default window.
        """
        return self.start_date
```

### 4.3 Variable Mapping Model

Each `StationLink` usually needs a per-variable mapping that tells ADL how to
translate upstream field names and units into ADL's canonical parameters. Use
Wagtail's `Orderable` and a `ParentalKey` so the mappings are managed inline
on the station link form.

```{important}
Your mapping model **must** expose two properties that ADL's `save_records()`
looks up at runtime:

- `source_parameter_name` — the key in the records dict that `get_station_data()` returns (e.g. `"rh"`)
- `source_parameter_unit` — the `Unit` instance the upstream value is expressed in

Without these, unit conversion and saving will silently fail.
```

```python
from adl.core.models import DataParameter, Unit
from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from wagtail.admin.panels import FieldPanel
from wagtail.models import Orderable

from .widgets import TahmoVariableSelectWidget


class TahmoStationLinkVariableMapping(Orderable):
    station_link = ParentalKey(
        TahmoStationLink,
        on_delete=models.CASCADE,
        related_name="variable_mappings",
    )
    adl_parameter = models.ForeignKey(
        DataParameter,
        on_delete=models.CASCADE,
        verbose_name=_("ADL Parameter"),
    )
    tahmo_variable_shortcode = models.CharField(
        max_length=255,
        verbose_name="TAHMO Variable",
    )
    tahmo_parameter_unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        verbose_name=_("TAHMO Parameter Unit"),
    )
    
    panels = [
        FieldPanel("adl_parameter"),
        FieldPanel("tahmo_variable_shortcode", widget=TahmoVariableSelectWidget),
        FieldPanel("tahmo_parameter_unit"),
    ]
    
    @property
    def source_parameter_name(self):
        """The field key your plugin returns in each record dict."""
        return self.tahmo_variable_shortcode
    
    @property
    def source_parameter_unit(self):
        """The Unit the upstream value is expressed in."""
        return self.tahmo_parameter_unit
```

---

## 5. The API Client

Wrap your upstream HTTP (or other I/O) calls in a dedicated client class. Keep
it focused: authentication, request construction, response parsing, and
optional caching. No ADL model logic here.

The TAHMO client illustrates three patterns worth copying:

**Caching expensive list endpoints** (station and variable lists rarely change,
so cache them for 24 hours using Django's cache framework):

```python
# src/adl_tahmo_plugin/client.py

import requests
from dateutil import parser as date_parser
from django.core.cache import cache
from requests.auth import HTTPBasicAuth


class TahmoAPIClient:
    def __init__(self, api_key, api_secret,
                 base_url='https://datahub.tahmo.org', use_cache=True):
        self.api_key = api_key
        if not base_url.endswith('/'):
            base_url += '/'
        self.base_url = base_url
        self.use_cache = use_cache
        self.auth = HTTPBasicAuth(api_key, api_secret)
    
    def get_stations(self):
        cache_key = f"{self.api_key}-tahmo-stations"
        if self.use_cache and cache.get(cache_key):
            return cache.get(cache_key)
        
        url = f'{self.base_url}services/assets/v2/stations'
        response = requests.get(url, auth=self.auth)
        response.raise_for_status()
        
        stations_data_dict_by_code = {
            str(s['code']): s
            for s in response.json().get('data', [])
        }
        
        if self.use_cache:
            cache.set(cache_key, stations_data_dict_by_code, 86400)
        
        return stations_data_dict_by_code
```

**Pivoting time-series results into per-timestamp dicts** (the TAHMO API
returns long-format rows of `time / variable / value`; pivot them into wide
dicts keyed by timestamp so each dict represents one observation time step):

```python
def get_measurements(self, station_code, collection_type="raw", start_date=None, end_date=None, variable=None,
                     sensor=None):
    url = (f'{self.base_url}services/measurements/v2/stations/'
           f'{station_code}/measurements/{collection_type}')
    
    params = {}
    if start_date:
        params['start'] = start_date
    if end_date:
        params['end'] = end_date
    
    response = requests.get(url, auth=self.auth, params=params)
    response.raise_for_status()
    
    results = response.json().get('results', [])
    data = None
    if results:
        series = results[0].get('series', [])
        if series:
            data = series[0]
    
    measurements_by_date = {}
    
    if data:
        columns = data.get('columns', [])
        values = data.get('values', [])
        
        for item in values:
            row = {col: val for col, val in zip(columns, item)}
            time = row.get('time')
            variable_name = row.get('variable')
            value = row.get('value')
            quality = row.get('quality', None)
            
            # Normalize: TAHMO returns relative humidity as a decimal fraction
            if variable_name == "rh" and value is not None:
                value = value * 100
            
            if time not in measurements_by_date:
                # isoparse returns a timezone-aware UTC datetime
                measurements_by_date[time] = {
                    "observation_time": date_parser.isoparse(time)
                }
            
            # Only save values that passed TAHMO's quality check (quality == 1)
            if value is not None and quality == 1:
                measurements_by_date[time][variable_name] = value
    
    return list(measurements_by_date.values())
```

```{note}
The quality filter (`quality == 1`) is a deliberate choice: TAHMO flags
observations that failed sensor validation with a quality value other than 1.
Decide upfront whether your data source has an equivalent quality flag and
filter accordingly. Passing bad values through to `save_records()` will store
them without complaint.
```

---

## 6. The Plugin Class

Subclass `adl.core.registries.Plugin` and set a unique `type` string and a
human-readable `label`. The only method you **must** implement is
`get_station_data`.

```python
# src/adl_tahmo_plugin/plugins.py

import logging
from datetime import timedelta

from adl.core.registries import Plugin

logger = logging.getLogger(__name__)


class TahmoPlugin(Plugin):
    type = "adl_tahmo_plugin"  # Must be unique across all installed plugins
    label = "ADL TAHMO Plugin"
    
    def get_station_data(self, station_link, start_date=None, end_date=None):
        """
        Fetch raw measurements from TAHMO for one station over [start_date, end_date).

        Args:
            station_link: A TahmoStationLink instance.
            start_date:   Timezone-aware datetime (station-local). Provided by ADL.
            end_date:     Timezone-aware datetime (station-local). Provided by ADL.

        Returns:
            A list of dicts. Each dict must contain 'observation_time' and any
            number of variable fields whose keys match the station link's
            variable mapping shortcodes (e.g. 'rh', 'te', 'pr').
        """
        start_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        client = station_link.network_connection.get_api_client()
        
        return client.get_measurements(
            station_link.tahmo_station_code,
            start_date=start_str,
            end_date=end_str,
        )
```

### 6.1 Date-Window Overrides

ADL determines the `start_date` and `end_date` passed to `get_station_data`
through a chain of methods on the base `Plugin` class. You can override any of
them.

The default resolution order for `start_date` is:

1. **`get_start_date_from_db`** — latest `observation_time` already saved for
   this station link (so ingestion always resumes from where it left off)
2. **`station_link.get_first_collection_date()`** — the custom start date set
   on the station link, if any (used for historical backfills)
3. **`get_default_start_date`** — fallback when no prior data and no custom
   date exists; base class defaults to one hour before `end_date`

The TAHMO plugin overrides two of these:

```python
def get_default_start_date(self, station_link):
    """
    Override: fall back to 24 hours before end_date instead of 1 hour.
    TAHMO data is hourly, so a 1-day window is a safer default.
    """
    end_date = self.get_default_end_date(station_link)
    return end_date - timedelta(days=1)


def get_start_date_from_db(self, station_link):
    """
    Override: add 1 minute to the last saved timestamp to avoid re-fetching
    the already-stored observation at the boundary.
    """
    start_date = super().get_start_date_from_db(station_link)
    if start_date:
        start_date += timedelta(minutes=1)
    return start_date
```

Override only what your data source requires. If your API uses inclusive
end dates, or if your source reports at irregular intervals, adjust here rather
than in `get_station_data`.

### 6.2 What the Base Class Does After `get_station_data` Returns

Once your method returns, the base `Plugin` class:

1. Ensures each `observation_time` is a timezone-aware datetime (naive values
   are interpreted as station-local and localized automatically)
2. Iterates the station link's variable mappings
3. Looks up `record[mapping.source_parameter_name]` for each mapping
4. If `mapping.source_parameter_unit != mapping.adl_parameter.unit`, converts
   the value using `DataParameter.convert_value_from_units()`
5. Upserts `ObservationRecord(time, station, connection, parameter) → value`
   using `bulk_create(update_conflicts=True)`, so re-fetching an already-stored
   window is safe

---

## 7. Admin UI: Widgets, Views, and Wagtail Hooks

For a good operator experience, the TAHMO plugin provides AJAX-powered select
widgets that populate station and variable dropdowns dynamically from the live
API connection. This section walks through the full wiring.

### 7.1 JSON Views

Two lightweight Django views serve the options. They accept a `connection_id`
query parameter, instantiate the API client, and return a JSON list of
`{label, value}` objects.

```python
# src/adl_tahmo_plugin/views.py

from adl.core.utils import get_object_or_none
from django.http import JsonResponse

from .models import TahmoConnection
from .utils import get_stations


def get_tahmo_stations_for_connection(request):
    connection_id = request.GET.get('connection_id')
    if not connection_id:
        return JsonResponse({"error": "Network connection ID is required."}, status=400)
    
    conn = get_object_or_none(TahmoConnection, pk=connection_id)
    if not conn:
        return JsonResponse({"error": "The selected connection is not a TAHMO API Connection."}, status=400)
    
    return JsonResponse(get_stations(conn), safe=False)


def get_tahmo_variables_for_connection(request):
    connection_id = request.GET.get('connection_id')
    if not connection_id:
        return JsonResponse({"error": "Network connection ID is required."}, status=400)
    
    conn = get_object_or_none(TahmoConnection, pk=connection_id)
    if not conn:
        return JsonResponse({"error": "The selected connection is not a TAHMO API Connection."}, status=400)
    
    variables_dict = conn.get_api_client().get_variables()
    if not variables_dict:
        return JsonResponse({"error": "No variables found for the selected connection."}, status=404)
    
    variables_list = [
        {
            "label": f"{v['description']} - {v['shortcode']} ({v['units']})",
            "value": v['shortcode'],
        }
        for v in variables_dict.values()
        if v.get('shortcode')
    ]
    return JsonResponse(variables_list, safe=False)
```

A helper in `utils.py` keeps the station-list shape consistent:

```python
# src/adl_tahmo_plugin/utils.py

def get_stations(network_conn):
    stations_dict = network_conn.get_api_client().get_stations()
    return [
        {
            "label": f"{s.get('location', {}).get('name', '')} ({s.get('code')})",
            "value": s.get("code"),
        }
        for s in stations_dict.values()
    ]
```

### 7.2 Register the URLs via Wagtail Hook

Register your views inside the Wagtail admin URL namespace using the
`register_admin_urls` hook. This makes them available under `/admin/` and
subject to Wagtail's authentication middleware.

```python
# src/adl_tahmo_plugin/wagtail_hooks.py

from django.urls import path
from wagtail import hooks

from .views import (
    get_tahmo_stations_for_connection,
    get_tahmo_variables_for_connection,
    get_metadata,
)


@hooks.register('register_admin_urls')
def urlconf_tahmo_plugin():
    return [
        path(
            "adl-tahmo-plugin/tahmo-conn-stations/",
            get_tahmo_stations_for_connection,
            name="tahmo_stations_for_connection",
        ),
        path(
            "adl-tahmo-plugin/tahmo-conn-variables/",
            get_tahmo_variables_for_connection,
            name="tahmo_variables_for_connection",
        ),
        path(
            "adl-tahmo-plugin/metadata/<int:connection_id>/",
            get_metadata,
            name="tahmo_metadata_for_connection",
        ),
    ]
```

### 7.3 Custom Widgets

A custom widget subclasses Django's `Widget`, injects the view URL into the
template context, and lets a small vanilla JS class handle the AJAX fetch and
`<select>` population. The widget is then passed to `FieldPanel` in your model's
`panels` definition.

```python
# src/adl_tahmo_plugin/widgets.py

from django.forms import Widget
from django.urls import reverse


class TahmoStationSelectWidget(Widget):
    template_name = 'adl_tahmo_plugin/widgets/tahmo_station_select_widget.html'
    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['tahmo_stations_url'] = reverse("tahmo_stations_for_connection")
        return context


class TahmoVariableSelectWidget(Widget):
    template_name = 'adl_tahmo_plugin/widgets/tahmo_variable_select_widget.html'
    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['tahmo_variables_url'] = reverse("tahmo_variables_for_connection")
        return context
```

The template renders a `<select>` element and a small JavaScript class that:

- Reads the current value of the `id_network_connection` input on page load
- Fetches the appropriate JSON list from your view using that connection ID
- Re-fetches automatically when the connection changes (listens for `change`
  events on the connection input)
- Restores the previously selected value when editing an existing record
  (`initialStationId` / `initialVariableShortCode`)
- Shows a spinner during the fetch and surfaces any error message from the view

See
`templates/adl_tahmo_plugin/widgets/tahmo_station_select_widget.html` in the
plugin source for the full template. The variable widget follows the same
pattern.

---

## 8. Registering the Plugin

Your `AppConfig.ready()` method is the right place to register your plugin.
ADL's plugin registry is imported and the plugin instance is registered once,
when Django starts up.

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

The `type` string on your `Plugin` subclass (`"adl_tahmo_plugin"`) must be
**globally unique** across all installed plugins. ADL uses it to look up the
correct plugin at runtime when a connection triggers ingestion.

---

## 9. Optional: Settings Hook

If your plugin needs to extend Django settings — for example, to add a
dependency to `INSTALLED_APPS` — implement the `setup` function in
`config/settings/settings.py`:

```python
# src/adl_tahmo_plugin/config/settings/settings.py

def setup(settings):
    """
    Called after ADL has set up its own settings, before Django starts.
    Modify `settings` as you would a normal Django settings file.
    """
    # Example: settings.INSTALLED_APPS += ["some_extra_app"]
    pass
```

ADL discovers and calls this function automatically during startup.

---

## 10. End-to-End Flow

Putting it all together, here is what happens from configuration to stored
observation:

1. An operator creates a `TahmoConnection` in the Wagtail admin, entering API
   key and secret.
2. The operator creates a `TahmoStationLink` for each ADL station. The AJAX
   widget fetches available TAHMO stations from the live connection and populates
   the dropdown. The operator selects the matching TAHMO station code.
3. The operator adds variable mapping rows to the station link — each row maps
   a TAHMO shortcode (e.g. `te`) to an ADL `DataParameter` (e.g.
   `air_temperature`) and specifies the source unit (e.g. degrees Celsius).
4. Celery Beat triggers the ingestion task on the configured schedule. ADL
   resolves the registered plugin via `TahmoConnection.plugin_type` and calls
   `plugin.run_process(connection)`.
5. For each enabled station link, ADL determines the date window using the
   chain described in [Section 6.1](#61-date-window-overrides).
6. ADL calls `get_station_data(station_link, start_date, end_date)`. The plugin
   calls the TAHMO API and returns a list of record dicts.
7. ADL normalizes timestamps, walks the variable mappings, converts units where
   needed, and upserts `ObservationRecord` rows.
8. Observations appear in the database and are available to dispatch channels
   and the monitoring dashboard.

---

## 11. Troubleshooting

**No records are saved**

Check that the keys returned in your `get_station_data` records exactly match
the `source_parameter_name` values on your variable mappings. A mismatch is
silent — ADL simply finds no value for that mapping and skips it.

**Wrong or missing observations at the time boundary**

The TAHMO plugin adds one minute to `get_start_date_from_db` to avoid
re-fetching the last stored timestamp. If your API uses an inclusive end bound
or returns data at irregular intervals, adjust your date-window override
accordingly.

**Unit conversion errors**

Confirm that the `Unit` instances in your mappings use unit symbols that ADL's
conversion engine recognises (e.g. `degC`, `K`, `m/s`, `mm`). If a parameter
requires a special conversion context (e.g. precipitation expressed as a mass
flux), configure `DataParameter.custom_unit_context`.

**Timezone confusion**

Return timezone-aware datetimes from `get_station_data` wherever possible.
The TAHMO client uses `dateutil.parser.isoparse`, which preserves the UTC
offset from the API response. If you return naive datetimes, ADL treats them
as station-local time, which may or may not be what you want.

**`station_link_model_string_label` not set**

If station links do not appear in the admin and data collection does nothing,
check that your `NetworkConnection` subclass sets
`station_link_model_string_label = "your_app.YourStationLink"`.

**Plugin type collision**

If two plugins share the same `type` string the registry will raise an error on
startup. Choose a slug that is specific to your plugin — using the Python
package name (e.g. `adl_tahmo_plugin`) is a safe convention.
