(climsoft-integration)=

# 🗄️ Climsoft Integration

[Climsoft](https://climsoft.org) is the Climate Data Management System used
by many NMHSs. It does not receive data from ADL directly: ADL writes CSV
files to an FTP server, and Climsoft's own import picks them up from there.
This page covers the ADL half of that path — the dispatch channel to
configure — and describes the files ADL writes precisely enough for the
Climsoft administrator to set up the other half.

```{mermaid}
flowchart LR
  subgraph ADL
    OBS[(Observation records)] --> AGG[Hourly aggregates] --> DC[Standard FTP/SFTP Upload\ndispatch channel]
  end
  FTP[(FTP server\none folder per station\none CSV per day)]
  subgraph Climsoft
    IMP[Climsoft import] --> DB[(Climsoft database)]
  end
  DC -- "CSV per station\nper day" --> FTP
  FTP -- "configured by the\nClimsoft administrator" --> IMP
```

There is no Climsoft-specific channel type. Climsoft uses the **Standard
FTP/SFTP Upload** channel from the [FTP plugin](plugins/adl-ftp-plugin/guide.md),
configured as described below. This page does not cover how to set up
Climsoft's import; see the [Climsoft documentation](https://climsoft.org) and
the [checklist for the Climsoft administrator](#climsoft-administrator-checklist)
below.

## Prerequisites

- The **ADL FTP plugin** installed (it provides the *Standard FTP/SFTP
  Upload* channel). See [Manage Plugins](user_guide/manage_plugins.md).
- An **FTP or SFTP account** that both ADL and Climsoft can reach: host,
  port, username and password, and a directory ADL may write to. This is
  often a server the Climsoft team already runs for AWS data.
- The stations you want to send, with their **WIGOS identifiers** set in
  ADL. The identifier becomes the folder and file name Climsoft reads (see
  [The files ADL writes](#climsoft-file-contract)).
- Agreement with the **Climsoft administrator** on the list of columns
  (see [Parameter mappings](#climsoft-parameter-mappings)). Settle it before
  the first dispatch; changing it later needs coordination.

## Configuring the channel

Add a dispatch channel as described in
[Manage Dispatch Channels](user_guide/manage_dispatch_channels.md) and choose
**Standard FTP/SFTP Upload**. Use the values below. They are the
configuration in use by a live country deployment, and each one has a
reason; change one only when the Climsoft administrator asks you to.

### Base configuration (Part A)

| Field | Value | Why |
|---|---|---|
| Name | e.g. `Climsoft FTP` | Shown in monitoring and logs. |
| Network Connections | The connections whose stations Climsoft should receive | Limits which stations the channel can send; refine per station under *Station Links*. |
| Enabled | On | |
| Send Aggregated Data | **On** | Climsoft receives one row per hour instead of every raw 1, 5 or 10-minute observation. |
| Aggregation Period | **Hourly** | See [The files ADL writes](#climsoft-file-contract) for what each hourly row means. |
| Data Check Interval, Dispatch Timeout, Maximum Records per Dispatch, Starting date | Defaults | No Climsoft-specific needs. Set a *Starting date* if Climsoft should not receive the station's whole history. |

With hourly aggregation, ADL only sends **complete hours**: the current
hour is held back until it has ended, so a row is never sent half-filled.

### FTP configuration (Part B)

| Field | Value | Why |
|---|---|---|
| Timezone for output dates | **UTC** | No ambiguity at day boundaries or daylight-saving changes. Use local time only if the Climsoft administrator explicitly asks for it. |
| Connection Type | **FTP** (or **SFTP**) | FTP is what the live deployment uses. Prefer SFTP when the Climsoft host supports it: credentials and data are encrypted in transit. |
| Host / Port / Username / Password | The account from the prerequisites | |
| Remote Directory | e.g. `/climsoft` | ADL creates one sub-folder per station under it. Missing folders are created on first upload. |
| Use FTP Passive Mode | **On** | Works through the firewalls and NAT that usually sit between ADL and the FTP server. |
| Write Mode | **Append record to single daily file** | One file per station per day. *Create a new file for each record* would produce one file per station per hour, all of which Climsoft's import would have to pick up. |

Field-by-field reference, including the SFTP-only and FTPS options:
[Standard FTP/SFTP Upload](plugins/adl-ftp-plugin/guide.md#standard-ftpsftp-upload)
in the FTP plugin guide.

After saving, open the channel's **Station Links** page and use **Test
connection** to check the host and credentials (see
[Dispatch Troubleshooting](user_guide/dispatch_troubleshooting.md)).

(climsoft-parameter-mappings)=

### Parameter mappings (Part C)

Climsoft stores observations in their usual units (°C, hPa, mm), so unlike
the [WIS2Box channel](wis2box_integration.md) nothing is converted. Set
**Channel Unit** to the same unit as the ADL parameter anyway: the form
allows leaving it empty, but setting it records the intent and keeps the
output unchanged if someone later changes the ADL parameter's unit.

The recommended mappings, in this order:

| # | ADL parameter | Channel Parameter | Channel Unit | Aggregation Measure |
|---|---|---|---|---|
| 1 | Pressure | `atmospheric_pressure` | hPa | Average Value |
| 2 | Temperature | `air_temperature` | °C | Average Value |
| 3 | Relative Humidity | `relative_humidity` | % | Average Value |
| 4 | Wind Speed | `wind_speed` | m/s | Average Value |
| 5 | Wind Direction | `wind_direction` | ° | Average Value (circular mean, see below) |
| 6 | Wind Gust | `wind_gust` | m/s | Maximum Value |
| 7 | Rainfall | `precipitation` | mm | **Sum Value** |
| 8 | Solar Radiation | `solar_radiation` | W/m² | Average Value |

- **Only map what your stations measure.** A mapped parameter a station
  does not report produces an empty cell, which is harmless but is still a
  column the Climsoft administrator has to account for.
- **Rainfall must be *Sum Value*.** The hourly value is the total that fell
  in the hour; *Average Value* would report a fraction of it. See
  {ref}`Aggregation Measure <dispatch-aggregation-measure>` in Manage Dispatch Channels.
- **Wind direction** is averaged with a circular mean (so 350° and 10°
  average to 0°, not 180°) only when the ADL parameter's **Aggregation
  Method** is *Circular Mean*. Check it under **Settings → Data
  Parameters → Wind Direction**.
- **Channel Parameter names** are the CSV column headers. Climsoft does not
  require particular names; what matters is that they do not change once
  Climsoft's import is set up.
- **Optional:** hourly extremes for Climsoft setups that want them —
  Temperature again with *Maximum Value* as `air_temperature_max` and with
  *Minimum Value* as `air_temperature_min`. They are not part of the
  baseline.

```{warning}
**Treat the column list as frozen once Climsoft is importing.** The CSV
columns appear in the order of the mapping rows. If Climsoft's import maps
columns by position, reordering, inserting or deleting a mapping row in ADL
silently moves values into the wrong Climsoft elements — no error on either
side, just wrong data. Agree the list with the Climsoft administrator first,
and coordinate any later change with them.
```

(climsoft-file-contract)=

## The files ADL writes

This section is the hand-off: everything the Climsoft import needs to know
about ADL's output.

**Location and name.** One folder per station, one file per station per day:

```text
<Remote Directory>/<station id>/WIGOS_<station id>_<YYYYMMDD>.csv
```

`<station id>` is the station's **WIGOS identifier**, or its numeric ADL
station id if it has none. Changing a station's WIGOS identifier in ADL
therefore moves its files to a new folder. `<YYYYMMDD>` is the day of the
rows it contains, in the channel's timezone (UTC).

**Format.** Comma-separated, UTF-8, one header row, then one row per hour:

| Column | Content |
|---|---|
| `station_id` | The station's numeric ADL id. |
| `wigos_id` | The station's WIGOS identifier (empty if none). |
| `date` | `YYYY-MM-DD`, UTC. |
| `time` | `HH:MM:SS`, UTC — **the start of the hour the row summarises** (see below). |
| `atmospheric_pressure` … | One column per parameter mapping, in mapping order, named by *Channel Parameter*. |

Values are written as calculated, without rounding (an hourly average can
have many decimal places). A parameter with no data for the hour is an empty
cell. An hour with no data for any mapped parameter is not written at all,
so hours can be missing from a file.

**Sample** — `/climsoft/0-20000-0-12345/WIGOS_0-20000-0-12345_20261112.csv`
with the baseline mappings (illustrative values):

```text
station_id,wigos_id,date,time,atmospheric_pressure,air_temperature,relative_humidity,wind_speed,wind_direction,wind_gust,precipitation,solar_radiation
3,0-20000-0-12345,2026-11-12,00:00:00,1012.8333333333334,18.416666666666668,87.5,1.3,152.84,3.1,0.0,0.0
3,0-20000-0-12345,2026-11-12,01:00:00,1012.65,18.1,89.08333333333333,1.1,148.2,2.7,0.2,0.0
3,0-20000-0-12345,2026-11-12,02:00:00,1012.4166666666666,17.95,90.25,0.9,155.71,,1.4,0.0
```

### What each hourly row means

The `time` column is the **start** of the hour: the row at `10:00:00` holds
the observations from 10:00:00 to 10:59:59 — the average temperature over
that hour, the rain that fell in it, the highest gust in it.

```{important}
Climsoft, like WMO practice, often labels an hourly value by the **end** of
its period ("rainfall at 10:00" = rain from 09:00 to 10:00). If Climsoft's
import reads ADL's `time` that way, every row lands one hour early, which
matters most for rainfall totals and around midnight. The Climsoft
administrator must account for this. Whether ADL should change its labelling
is tracked in
[wmo-raf/adl#401](https://github.com/wmo-raf/adl/issues/401).
```

### How files change over the day

- **The day's file is rewritten in full on every run.** ADL downloads the
  existing file, merges in the new hours by time, and uploads the whole
  file again. Climsoft should read each file as a snapshot and import it so
  that re-reading rows it already has does no harm; it should not assume a
  file only grows at the end.
- **A day's file is complete** once the channel has run after the end of
  that day (UTC), plus the time the stations take to deliver their data.
- **Late data is not revisited.** Each run sends only hours after the last
  one sent for the station. If a station's data for an hour arrives after
  that hour was sent, the normal schedule does not send it again.

(climsoft-administrator-checklist)=

## Checklist for the Climsoft administrator

Give the Climsoft administrator this page, or at least this list. Each item
is something their import must be set up for; how to do it depends on the
Climsoft version and is outside ADL.

1. **Server and folder**: the FTP host, the account to read with, and the
   *Remote Directory*.
2. **Station folders and files**: one folder per station named by its WIGOS
   identifier, files named `WIGOS_<WIGOS id>_<YYYYMMDD>.csv`, a new file
   each UTC day.
3. **Station identity**: which column identifies the station to Climsoft
   (`wigos_id`, or the folder name), and the mapping from WIGOS identifier
   to Climsoft station.
4. **Header and columns**: one header row to skip; `station_id` and
   `wigos_id` first; then `date` and `time`; then the agreed parameter
   columns, each mapped to its Climsoft element.
5. **Date and time**: `YYYY-MM-DD` and `HH:MM:SS`, in **UTC**, with `time`
   being the **start** of the hour summarised.
6. **Units**: as in the [parameter mappings](#climsoft-parameter-mappings)
   table (hPa, °C, %, m/s, °, mm, W/m²).
7. **Re-reading**: the current day's file is rewritten every run; importing
   it again must not create duplicates.
8. **Changes**: any change to the column list is agreed in advance.

## Changing the configuration later

```{warning}
**Change parameter mappings just after 00:00 UTC.** In *Append* mode, when
ADL cannot read the existing day's file against the current column list —
which is the case right after a mapping is added or renamed — it starts the
file again with only the new hours, and the earlier hours of that day are
removed from the file. Removing or reordering a mapping does not cause this.
A failed download of the existing file (for example, an FTP timeout) can
cause the same loss. Making mapping changes at the start of a UTC day
limits what can be lost. Fixing this is tracked in
[wmo-raf/adl-ftp-plugin#51](https://github.com/wmo-raf/adl-ftp-plugin/issues/51).
```

When you change mappings anyway:

1. Agree the new column list with the Climsoft administrator, including
   the date it takes effect.
2. Make the change in ADL just after 00:00 UTC on that date.
3. Confirm with them that the next day's file imports correctly.

## Troubleshooting

**No files appear on the FTP server**
: Use **Test connection** on the channel's *Station Links* page, then see
  [Dispatch Troubleshooting](user_guide/dispatch_troubleshooting.md). Check
  that the stations are linked to the channel and that the channel has
  parameter mappings. With hourly aggregation, the first file appears only
  after the first complete hour.

**Rainfall in Climsoft is far too low**
: The rainfall mapping uses *Average Value*. Set it to *Sum Value*.

**Rainfall in Climsoft is one hour off from the station's records**
: Climsoft is reading `time` as the end of the hour; ADL writes the start.
  See [What each hourly row means](#what-each-hourly-row-means).

**Wind direction averages look wrong near north**
: The Wind Direction parameter's *Aggregation Method* is not *Circular
  Mean*. Change it under **Settings → Data Parameters**.

**Values appear under the wrong Climsoft elements**
: The mapping rows were reordered, inserted or deleted after Climsoft's
  import was set up. Restore the agreed order, or update the import with
  the Climsoft administrator.

**A day's file lost its earlier hours**
: A mapping was added or renamed during the day, or a download of the
  existing file failed. See [Changing the configuration later](#changing-the-configuration-later).

**FTP connection errors**
: See the feedback catalogue in the
  [FTP plugin guide](plugins/adl-ftp-plugin/guide.md).
