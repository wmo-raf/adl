# Plugin API Reference

This page is the reference for the ADL plugin contract. The prose sections around each block explain *when* and *why* to
override, and call out the non-obvious behaviours that are easiest to miss.

---

## `Plugin` Base Class

```{eval-rst}
.. autoclass:: adl.core.registries.Plugin
   :members: get_station_data, get_default_end_date, get_default_start_date,
             get_start_date_from_db, get_dates_for_station, after_save_records,
             get_urls, save_records, process_station, run_process,
             perform_qc_checks_with_pipeline
   :show-inheritance:
   :no-undoc-members:
```

### What you must implement

The only method your plugin **must** override is {meth}`~adl.core.registries.Plugin.get_station_data`.
Everything else has a working default.

### Date-window override chain

ADL resolves the ``(start_date, end_date)`` window through a chain of calls.
Override the individual helpers rather than {meth}`~adl.core.registries.Plugin.get_dates_for_station`
itself:

```{eval-rst}
.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Method
     - Override when…
   * - :meth:`~adl.core.registries.Plugin.get_default_end_date`
     - Your source reports at daily (or other) resolution rather than hourly
   * - :meth:`~adl.core.registries.Plugin.get_default_start_date`
     - Your source's natural fallback window is larger or smaller than one hour
   * - :meth:`~adl.core.registries.Plugin.get_start_date_from_db`
     - Your API uses an inclusive end bound and you need to offset the boundary
       to avoid re-fetching the last saved record
```

### Silent failure modes

{meth}`~adl.core.registries.Plugin.save_records` drops records silently in
the following cases — no exception is raised and nothing appears in the saved
count:

- ``observation_time`` is missing, not a :class:`datetime`, before
  ``start_date``, after ``end_date``, or in the future.
- A variable mapping row is missing ``source_parameter_name``,
  ``source_parameter_unit``, or ``adl_parameter``.
- The key returned in your record dict does not exactly match
  ``mapping.source_parameter_name`` (case-sensitive).
- The value for a mapping key is ``None`` or not numeric (``int`` or
  ``float``).
- Unit conversion raises an exception for a specific mapping row.

If data is disappearing without errors, work through this list first.

---

## `NetworkConnection` Base Class

```{eval-rst}
.. autoclass:: adl.core.models.NetworkConnection
   :members: collect_data, get_plugin
   :show-inheritance:
   :no-undoc-members:
```

### Required class attribute

```{important}
Every ``NetworkConnection`` subclass **must** set:

.. code-block:: python

    station_link_model_string_label = "your_app.YourStationLink"

ADL uses this string to find the correct ``StationLink`` subclass when
rendering the station link form and running ingestion. If it is missing,
station links will not appear in the admin and data collection will silently
do nothing.
```

### Extending the admin form

Always extend ``NetworkConnection.panels`` rather than replacing it, to keep
the standard fields (name, network, plugin selector, interval, timezone) in
the form:

```python
panels = NetworkConnection.panels + [
    MultiFieldPanel([
        FieldPanel("api_key"),
        FieldPanel("api_secret"),
    ], heading=_("API Credentials")),
]
```

---

## `StationLink` Base Class

```{eval-rst}
.. autoclass:: adl.core.models.StationLink
   :members: get_variable_mappings, get_first_collection_date, timezone
   :show-inheritance:
   :no-undoc-members:
```

### Variable mapping contract

Your per-variable mapping model (an ``Orderable`` with a ``ParentalKey`` on
the station link) must expose these three attributes. They can be model
fields, properties, or a mix:

| Attribute                 | Type                       | Description                                                                                 |
|---------------------------|----------------------------|---------------------------------------------------------------------------------------------|
| ``source_parameter_name`` | ``str``                    | The key in the record dict returned by {meth}`~adl.core.registries.Plugin.get_station_data` |
| ``source_parameter_unit`` | ``Unit`` instance          | The unit the upstream value is expressed in                                                 |
| ``adl_parameter``         | ``DataParameter`` instance | The ADL canonical parameter to store the value under                                        |

If any of the three is missing or ``None`` on a mapping row, that mapping is
skipped silently for every record.

### Extending the admin form

Always extend ``StationLink.panels`` to keep the standard fields (connection,
station, enabled toggle, timezone options):

```python
panels = StationLink.panels + [
    FieldPanel("my_station_code", widget=MyStationSelectWidget),
    FieldPanel("start_date"),
    InlinePanel("variable_mappings", label=_("Variable Mappings")),
]
```

---

## `plugin_registry`

```{eval-rst}
.. autoclass:: adl.core.registries.PluginRegistry
   :members: urls
   :show-inheritance:
   :no-undoc-members:
```

The module-level singleton ``plugin_registry`` is the instance you interact
with directly. Import it and call ``register`` inside ``AppConfig.ready()``:

```python
from adl.core.registries import plugin_registry


class MyPluginConfig(AppConfig):
    name = "my_plugin"
    
    def ready(self):
        from .plugins import MyPlugin
        plugin_registry.register(MyPlugin())
```

```{important}
The ``type`` string on your ``Plugin`` subclass must be **globally unique**
across all installed plugins. Registering two plugins with the same ``type``
will raise an error at startup. Using the Python package name as the type
(e.g. ``"adl_tahmo_plugin"``) is a safe convention.
```

---

## `DataParameter.convert_value_from_units`

```{eval-rst}
.. automethod:: adl.core.models.DataParameter.convert_value_from_units
```

Called automatically by {meth}`~adl.core.registries.Plugin.save_records` for
every mapping row where the source unit differs from the parameter's canonical
unit. You do not call this directly, but understanding it helps when debugging
unexpected values.

If the parameter has a ``custom_unit_context`` configured (for conversions
that pint cannot resolve dimensionally — for example, precipitation from
``mm`` to ``kg/m²``), that context is applied automatically.

---

## Settings Hook

If your plugin needs to modify Django settings at startup, implement the
``setup`` function in ``<your_plugin>/config/settings/settings.py``:

```python
def setup(settings):
    """
    Called after ADL has configured its own settings, before Django starts.
    Modify the ``settings`` object as you would a normal Django settings file.
    """
    settings.INSTALLED_APPS += ["some_required_dependency"]
```

ADL discovers and calls this function automatically on startup. The file path
must follow the convention exactly:
``src/<plugin_name>/config/settings/settings.py``.
