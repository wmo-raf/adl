# 📕 Core Models Reference

This page documents the ADL core data models. Understanding these models is
useful whether you are writing a plugin, building on the API, or diagnosing
data issues.

For the plugin-specific base classes ({class}`~adl.core.models.NetworkConnection`
and {class}`~adl.core.models.StationLink`) see
[Plugin Developer Reference](plugins/plugin_reference.md).

---

## Data model overview

```{mermaid}
erDiagram
    Network ||--o{ Station : contains
    Network ||--o{ NetworkConnection : has
    Station ||--o{ StationLink : linked_via
    NetworkConnection ||--o{ StationLink : linked_via
    StationLink ||--o{ ObservationRecord : produces
    DataParameter ||--o{ ObservationRecord : describes
    Unit ||--o{ DataParameter : unit_of
```

---

## `Network`

```{eval-rst}
.. autoclass:: adl.core.models.Network
   :members:
   :no-undoc-members:
   :show-inheritance:
```

A `Network` is a purely organisational grouping of stations — for example, “National AWS Network” or “TAHMO Stations”.
It carries no ingestion logic itself. Networks are used to scope station lists in the admin and to group connections.

---

## `Station`

```{eval-rst}
.. autoclass:: adl.core.models.Station
   :members: wigos_id
   :no-undoc-members:
   :show-inheritance:
```

A `Station` represents one physical observing point. It carries full
[WMO WIGOS](https://community.wmo.int/en/activity-areas/WIGOS) identification
metadata alongside location and sensor height fields.

---

## `Unit`

```{eval-rst}
.. autoclass:: adl.core.models.Unit
   :members: pint_unit, get_registry_unit
   :no-undoc-members:
   :show-inheritance:
```

A `Unit` defines a unit of measurement backed by the
[pint](https://pint.readthedocs.io) unit registry. The `symbol` field must
be a valid pint symbol (e.g. `degC`, `K`, `m/s`, `mm`, `hPa`).

```{important}
When configuring variable mappings in a plugin, the `symbol` must match
exactly what pint recognises. If a unit conversion fails silently, verify
the symbol here first. Common valid symbols: `degC`, `K`, `m/s`, `km/h`,
`mm`, `hPa`, `Pa`, `%`, `W/m^2`.
```

---

## `DataParameter`

```{eval-rst}
.. autoclass:: adl.core.models.DataParameter
   :members: convert_value_from_units, convert_value_to_units
   :no-undoc-members:
   :show-inheritance:
```

A `DataParameter` is ADL's canonical representation of a measurable variable
(e.g. `air_temperature`). It defines the canonical {class}`~adl.core.models.Unit`
in which values are stored, and drives automatic unit conversion when
observations arrive in a different unit.

**Unit conversion**

{meth}`~adl.core.models.DataParameter.convert_value_from_units` converts a
value *from* a given source unit *to* the parameter's canonical unit.
{meth}`~adl.core.models.DataParameter.convert_value_to_units` does the
reverse. Both use pint internally and apply `custom_unit_context` if set.

```python
# Example: convert 293.15 K to the parameter's canonical unit (degC)
converted = air_temp_parameter.convert_value_from_units(293.15, kelvin_unit)
# → 20.0
```

```{warning}
Changing the `unit` of a `DataParameter` that already has
{class}`~adl.core.models.ObservationRecord` rows will raise a
`ValidationError`. Delete the existing records first, or create a new
parameter instead.
```

---

## `ObservationRecord`

```{eval-rst}
.. autoclass:: adl.core.models.ObservationRecord
   :members: utc_time
   :no-undoc-members:
   :show-inheritance:
```

`ObservationRecord` is the atomic unit of stored data in ADL. It is backed by
[TimescaleDB](https://www.timescale.com) for efficient time-series queries.

**Uniqueness constraint**

Each row is uniquely identified by `(time, station, connection, parameter)`.
ADL's `save_records` uses `bulk_create(update_conflicts=True)` against this
constraint, so re-ingesting an already-stored window updates the value rather
than raising an error.

---

## `QCStatus`

```{eval-rst}
.. autoclass:: adl.core.models.QCStatus
   :members:
   :no-undoc-members:
```

An `IntegerChoices` enum stored on each {class}`~adl.core.models.ObservationRecord`.

| Value | Name            | Meaning                                                   |
|-------|-----------------|-----------------------------------------------------------|
| `0`   | `PASS`          | All configured QC checks passed.                          |
| `1`   | `SUSPECT`       | One or more QC checks failed; value retained but flagged. |
| `2`   | `FAIL`          | Record failed hard validation.                            |
| `3`   | `MISSING`       | No value available for this time step.                    |
| `4`   | `ESTIMATED`     | Value was estimated or gap-filled.                        |
| `5`   | `CORRECTED`     | Value was manually corrected.                             |
| `6`   | `NOT_EVALUATED` | No QC checks configured for this parameter. Default.      |

---

## `QCBits`

```{eval-rst}
.. autoclass:: adl.core.models.QCBits
   :members:
   :no-undoc-members:
```

An `IntFlag` bitmask stored alongside `QCStatus` on each
{class}`~adl.core.models.ObservationRecord`. Multiple bits can be set
simultaneously if more than one check failed.

| Bit           | Name              | Check type                                                 |
|---------------|-------------------|------------------------------------------------------------|
| `RANGE`       | Range check       | Value outside configured min/max bounds.                   |
| `STEP`        | Step check        | Change between consecutive observations exceeds threshold. |
| `PERSISTENCE` | Persistence check | Value unchanged for too many consecutive time steps.       |
| `SPIKE`       | Spike check       | Value is an isolated outlier relative to neighbours.       |

---

## `HourlyObsAgg`

```{eval-rst}
.. autoclass:: adl.core.models.HourlyObsAgg
   :members: time
   :no-undoc-members:
   :show-inheritance:
```

A read-only TimescaleDB continuous aggregate view (database table
`obs_agg_1h_v`) that provides pre-computed hourly summaries of
{class}`~adl.core.models.ObservationRecord` data. It is not a managed Django
model — ADL does not create or migrate it directly.

```{note}
Query this model instead of `ObservationRecord` whenever you need hourly
summaries — it is significantly faster for large time ranges because
TimescaleDB maintains the aggregates incrementally.
```
