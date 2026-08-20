# Audit: reusing `adl_ftp_plugin` from the planned `adl-agent-plugin`

Research for wmo-raf/adl#263. Context: a new plugin repo (working name
`adl-agent-plugin`) will receive raw station data files uploaded by a Windows
desktop app, stage them server-side, and decode/ingest them reusing as much of
`adl-ftp-plugin`'s machinery as possible. The new plugin will depend on the
installed `adl_ftp_plugin` package the same way decoder plugins such as
`adl-vaisala-sc-ftp-decoder` do (see the precedent section at the end).

All file references below are into
`adl-plugins/adl-ftp-plugin/plugins/adl_ftp_plugin/src/adl_ftp_plugin/`
unless noted otherwise.

---

## 1. Decoder registry and decoder contract — importable as-is? Yes, with one caveat

`registries.py` (107 lines) defines:

- `FTPDecoder(Instance)` — the decoder base class. Contract:
  - `type` (registry key, required), `compat_type`, `display_name`.
  - `pre_process(file_path) -> file_path` — optional hook before decoding.
  - `decode(file_path) -> {"values": [ {"observation_time": datetime, "<var>": value, ...}, ... ]}`
    — **operates on a local file path only; fully transport-agnostic.**
  - `get_variables() -> list[dict]` — optional declaration of emitted
    variables (`name`, `unit`, optional `label`, `adl_unit`, `description`,
    `aggregation_method`, `custom_unit_context`) used by the "Populate
    variable mappings from decoder" admin action.
  - `get_matching_files(station_link, files, start_date, end_date)` — **the
    one FTP-coupled method** (see refactor R1 below). It reads
    `station_link.file_pattern`, `.listing_strategy`,
    `.filename_date_format`, `.filename_date_timezone` and imports
    `FTPListingStrategy` from `adl_ftp_plugin.models`.
- `FTPDecoderRegistry(Registry)` and the module-level singleton
  `ftp_decoder_registry` (name `"adl_ftp_decoder"`).

**Importability:** `registries.py` imports only `adl.core.registry`,
`django.core.exceptions`, `fnmatch`, and `ftp.ftp_utils.filter_files_by_date_range`
(pure Python; `ftp/__init__.py` pulls only stdlib `ftplib`/`ssl`, paramiko is
isolated in `ftp/sftp.py`). So `from adl_ftp_plugin.registries import
ftp_decoder_registry, FTPDecoder` works without touching FTP transport or
models. `.models` is imported lazily *inside* `get_matching_files`, so simply
registering/fetching decoders and calling `decode()` never loads the FTP
models — but the deployment must still have `adl_ftp_plugin` in
`INSTALLED_APPS` (it is, whenever the package is installed, via ADL's plugin
loader), which brings its migrations along. That is exactly the situation the
existing decoder plugins already run in.

**Registered decoders reusable as-is** (all decode local paths):

| Decoder | File | Notes |
|---|---|---|
| `standard_csv` | `decoders/standard_csv.py` | Needs a `StandardCSVConfig` instance injected as `decoder._config` before `decode()` (see R2) |
| `toa5` | `decoders/toa5.py` | Campbell Scientific TOA5; self-contained |
| `siapmicros` | `decoders/siapmicros.py` | Self-contained |
| plus third-party decoders | `adl-vaisala-sc-ftp-decoder`, `adl-lsi-bi-ftp-decoder`, `adl-kmd-kcsap-ftp-decoder`, `adl-bouy-sc-ftp-decoder`, `adl-vaisala-sudan-ftp-decoder`, ... | Register into the same `ftp_decoder_registry` from their own `apps.ready()` — the agent plugin gets them all for free |

The agent plugin should store a `decoder` choice on its connection model using
`adl_ftp_plugin.utils.get_ftp_decoder_choices()` (pure; reads the registry)
and resolve it with `ftp_decoder_registry.get(name)` — the same shape as
`NetworkFTP.decoder` / `NetworkFTP.get_decoder()` (`models.py` ~line 368/407).

## 2. date_formats.py, decoder_variables.py, time-resolution/aggregation

- **`date_formats.py` (320 lines): fully reusable, zero transport coupling.**
  `FILENAME_DATE_FORMAT_DEFINITIONS` (≈40 formats incl. Julian day and Unix
  timestamp, each with `format`, `label`, `has_time`, `length`, `strptime`),
  derived `FILENAME_DATE_FORMAT_CHOICES`, `format_has_time_component()`,
  `get_format_definition()`. Only Django dependency is `gettext_lazy`. The
  agent plugin can import these for any server-side re-validation of filename
  dates, and the definitions table doubles as the spec to port to the Windows
  app (section 6).
- **`decoder_variables.py` (271 lines): mostly reusable; the last function is
  FTP-model-bound.** `normalise_decoder_variables`, `get_decoder_variables`
  (duck-types `connection.get_decoder()`), `get_unmapped_decoder_variables`
  (duck-types `connection.variable_mappings` with a `file_variable_name`
  field), `find_unit_by_symbol`, `find_parameter_for_variable`,
  `get_or_create_unit`, `get_or_create_parameter` — all generic over
  `adl.core.models`. Only `create_variable_mappings()` hard-codes
  `FTPVariableMapping` and the `network_ftp=` kwarg (see R3).
- **Time resolution / aggregation:** there is none in the FTP plugin itself —
  records flow through core's validation/aggregation. `FTPStationLink.panels`
  ends with `StationLink.aggregation_panels`, i.e. aggregation config lives on
  the **core** `StationLink` base; the agent plugin gets it the same way by
  appending `StationLink.aggregation_panels`. Interval logic that does exist
  (`direct_fetch_interval_minutes` stepping in `plugins.py
  _generate_direct_fetch_files`) is about *expected file cadence*, not data
  aggregation, and is FTP-strategy-specific.
- **`utils.py` date-tree helpers are pure and reusable** if the agent app
  mirrors date-structured folders: `get_dates_to_now`, `get_date_path(s)`,
  `add_date_info_to_path`, `get_month_dir_formatted`, `normalize_path`, and
  `resolve_variable_mappings(connection_mappings, station_mappings)` — the
  extracted Pattern-C merge (section 4).

## 3. The fetching strategy and the file → decode → records pipeline

Configuration lives on the models (`models.py`):

- `NetworkFTP(NetworkConnection)` — transport credentials + `decoder` choice +
  `csv_config` FK + connection-level `variable_mappings` InlinePanel.
- `FTPStationLink(StationLink)` — `ftp_path`, `file_pattern` (glob),
  `dir_structured_by_date`/`date_granularity`/`month_dir_format`,
  `listing_strategy` (`FTPListingStrategy`: `PATTERN_ONLY`, `FILTER_BY_DATE`,
  `DIRECT_FETCH`), the `filename_date_format`/`filename_date_timezone` pair
  (filter-by-date), the `direct_fetch_*` quintet (prefix, interval-minutes,
  datetime format/timezone, extension), `start_date`,
  `skip_already_downloaded_files`.
- `FTPStationDataFile` — the **file staging model**: FK to station link,
  `file_name`, `FileField`, `processed_at`, `values_saved`. Downloaded files
  are stored here and re-decoded from `db_data_file.file.path`; a daily Celery
  task (`tasks.py cleanup_old_ftp_files`) deletes processed files older than
  7 days.

Pipeline in `plugins.py` (`AdlFtpPlugin`):

1. `get_station_data(station_link, start, end)` — generator. Opens the FTP
   client, resolves the decoder (`_get_configured_decoder`, which injects
   `csv_config` for `standard_csv`), then iterates `_get_file_paths(...)`.
2. `_get_file_paths` — strategy dispatch. DIRECT_FETCH constructs filenames
   from the clock (`_generate_direct_fetch_files`, DST-safe stepping in
   absolute instants); listing strategies walk date directories
   (`get_dates_to_now` + `get_date_paths`), `ftp_client.list(...)`, then
   `decoder.get_matching_files(...)` (glob match + optionally
   `filter_files_by_date_range` on filename dates).
3. `_process_file` — download to a tempfile → save into `FTPStationDataFile`
   → `decoder.decode(local_path)` → yield each record → yield core's `FLUSH`
   marker so core persists before the generator resumes → stamp
   `processed_at` and `values_saved` (fed by `after_save_records`, which
   accumulates `len(saved_records)` into a transient
   `station_link._adl_ftp_values_saved`).
4. Sources-count bookkeeping (`adl_sources_count`) and `get_station_file_paths`
   dry-run for the admin preview.

**For the agent plugin, steps 1–2 are replaced entirely** (files arrive by
upload; there is no listing and no remote fetch). **Step 3's decode-side is
the reusable half**: "given a staged local file and a decoder, decode → yield
records → yield `FLUSH` → stamp `processed_at`/`values_saved`" is
transport-agnostic but currently welded to `FTPStationDataFile` and
`ftp_client.get()` inside one method (see R4). The `after_save_records`
per-file counter idiom and the `FLUSH` handshake are directly copyable, and
`FTPStationDataFile`'s field set (`processed_at`, `values_saved`, upload-path
scheme, cleanup task) is the template for the agent plugin's staging model.

## 4. Variable mapping (Pattern C hybrid): duplicate vs import

Implementation:

- `FTPVariableMapping(Orderable)` — ParentalKey to `NetworkFTP`
  (`related_name="variable_mappings"`), fields `adl_parameter`,
  `file_variable_name`, `file_variable_unit`, plus the duck-typed
  `source_parameter_name` / `source_parameter_unit` properties.
- `FTPStationLinkVariableMapping(Orderable)` — identical shape, ParentalKey to
  `FTPStationLink`.
- `FTPStationLink.get_variable_mappings()` — merges connection-level defaults
  with station overrides per `adl_parameter_id` (same logic is also available
  as the importable `utils.resolve_variable_mappings`).

**Must duplicate** (Django models cannot be shared across apps because the
ParentalKey must point at the agent plugin's own connection/station-link
models): both `Orderable` mapping classes (≈20 lines each) and the two
InlinePanels. This is the same duplication every plugin carries; it is cheap
and keeps migrations independent.

**Can import**: `utils.resolve_variable_mappings` for the merge;
`decoder_variables.py` helpers for the "populate from decoder" flow (all but
`create_variable_mappings`, per R3); the duck-typed property pattern.

## 5. FTP-transport entanglements — concrete refactors proposed for adl-ftp-plugin

Each refactor keeps backward compatibility (old import paths re-export).

- **R1 — Split file matching out of `FTPDecoder.get_matching_files`**
  (`registries.py` lines 66–96). Extract the body into a module-level
  transport-neutral helper, e.g.
  `adl_ftp_plugin/file_matching.py::match_files(files, pattern,
  filename_date_format=None, start_date=None, end_date=None, tz=utc)`, and
  have `get_matching_files` delegate to it after reading the FTPStationLink
  fields. Today the method imports `FTPListingStrategy` from `.models` and
  reads four FTP-model fields, so a non-FTP consumer cannot call it without
  faking an `FTPStationLink`. (The agent plugin may not need server-side
  matching at all — see section 6 — but the helper also becomes the reference
  spec for the Windows app.)

- **R2 — Give `StandardCSVDecoder` an explicit config argument.**
  `decoders/standard_csv.py` reads `self._config`, which
  `AdlFtpPlugin._get_configured_decoder` (`plugins.py` lines 39–58) mutates on
  the **registry singleton** before each run — any second consumer (the agent
  plugin's Celery worker included) can race or clobber it. Change to
  `decode(self, file_path, config=None)` with `config = config or
  getattr(self, "_config", None)`, and extract `_get_configured_decoder` into
  a shared helper, e.g. `adl_ftp_plugin/decoder_resolution.py::
  resolve_decoder(decoder_name, csv_config=None)`, that both plugins call.
  `StandardCSVConfig` itself (`models.py` lines 104–316) has no FTP fields and
  is reusable as-is via FK from the agent connection.

- **R3 — Parametrise `create_variable_mappings`**
  (`decoder_variables.py` lines 203–271). It hard-codes `FTPVariableMapping`
  and the `network_ftp=connection` kwarg. Accept `mapping_model` and
  `connection_field_name` parameters (defaulting to the current values), or
  move the loop to operate through `connection.variable_mappings` (the related
  manager already encodes both). Everything above it in the module is already
  generic. The companion admin view
  `views.py::populate_variable_mappings_from_decoder` would need the same
  parametrisation or a thin agent-side wrapper.

- **R4 — Extract the decode-and-stamp half of `_process_file`**
  (`plugins.py` lines 326–440). Split into (a) FTP-specific
  "ensure file is local" (download via `ftp_client.get` into
  `FTPStationDataFile`) and (b) a transport-neutral generator, e.g.
  `adl_ftp_plugin/processing.py::decode_and_yield(data_file, decoder,
  station_link, logger)` that decodes `data_file.file.path`, yields records,
  yields `FLUSH`, and stamps `processed_at`/`values_saved` through a small
  duck-typed interface (`file.path`, `processed_at`, `values_saved`,
  `save(update_fields=...)`). The agent plugin's staging model satisfies the
  same interface and reuses the exact FLUSH/values-saved semantics instead of
  re-deriving them. `after_save_records` (lines 313–324) moves alongside it
  (the `_adl_ftp_values_saved` attribute name could become
  `_adl_file_values_saved`, keeping the old name as an alias).

- **R5 (cosmetic, low priority) — Move `parse_date_from_filename` /
  `filter_files_by_date_range` out of `ftp/ftp_utils.py`.** They are pure
  (only `date_formats` + stdlib) but live under the `ftp/` transport package,
  whose `__init__` defines the ftplib client; importing them executes that
  module (stdlib-only, so it works today, but the placement misleads).
  Relocate to the `file_matching.py` of R1; re-export from `ftp/ftp_utils.py`.

- **No refactor needed** for: `registries.py` (minus R1), `date_formats.py`,
  `utils.py`, `validators.py` (`validate_start_date`), `StandardCSVConfig` +
  its chooser viewset, the `test_decoder_config` admin tool
  (`views.py::test_decoder_config` decodes an *uploaded* file against a
  decoder+config — already file-upload-shaped and useful verbatim from the
  agent plugin's admin), and the third-party decoder ecosystem.

- **Never imported by the agent plugin** (FTP-only): `ftp/__init__.py`
  (`FTPClient`/`FTPError`), `ftp/sftp.py`, `dispatchers/ftp.py`,
  `smartmet_utils.py`, `BaseFTPUpload`/`FTPUpload`/`SmartMetFTPUpload`,
  `NetworkFTP`/`FTPStationLink` and their source-check methods, the
  direct-fetch preview/probe views, `widgets.py` (FTP directory tree),
  `forms.py`, `wagtail_hooks.py`.

## 6. Agent-side logic (reimplemented in the Windows app, not reused)

Everything the FTP plugin does *against the remote server* becomes local-disk
logic inside the desktop app, in the app's own language:

- **File discovery**: glob matching against `file_pattern`
  (`fnmatch.fnmatch` equivalent), walking date-structured directory trees
  (`get_dates_to_now` + `get_date_path` + `get_month_dir_formatted`
  equivalents, including the month-format table `m/n/M/b/F/f`).
- **Filename date filtering**: the `parse_date_from_filename` /
  `filter_files_by_date_range` algorithm — date at the *end* of the basename,
  fixed-length slice per format, date-only vs datetime comparison semantics,
  filename timezone handling. The `FILENAME_DATE_FORMAT_DEFINITIONS` table in
  `date_formats.py` is the porting spec.
- **Direct-fetch filename generation** if that mode is supported: cadence
  stepping in absolute instants with per-step conversion into the filename
  timezone (the DST correctness note in `plugins.py` lines 296–300 applies
  verbatim).
- **Upload-side dedup/idempotency**: the analogue of
  `skip_already_downloaded_files` — remembering which files were already
  uploaded (name + size/mtime/hash) so restarts don't re-send.

The server should treat agent uploads as authoritative and at most
re-validate; pushing this config from ADL to the app (so the operator
configures patterns once, in ADL admin) is a design question for the new
plugin, not a refactor of adl-ftp-plugin.

## adl-collector-app-plugin: the staging + after_save_records precedent

`adl-plugins/adl-collector-app-plugin/plugins/adl_collector_app_plugin/src/adl_collector_app_plugin/`
already demonstrates the exact server-side shape the agent plugin needs:

- **Staging models** (`models/submission.py`): `CollectorSubmission`
  (`idempotency_key`, `content_hash`, `submission_time`,
  `observation_time`, `is_test_submission`, raw `data` JSON, uniqueness
  constraint on observer+time+hash) and `CollectorSubmissionRecord`
  (`is_processed`, `processed_at`, `error_message`). For the agent plugin the
  staged unit is a *file* rather than a value row, so the model is closer to
  `FTPStationDataFile` + `CollectorSubmission`'s idempotency fields combined.
- **Pull-from-staging ingestion** (`plugins.py::get_station_data`): reads
  unprocessed staged rows for the station link and returns records —
  no external I/O in the ingestion path.
- **`after_save_records` marking staged rows processed**
  (`plugins.py` lines 33–67): carries a correlation id (`submission_id`) in
  each yielded record and flips `is_processed`/`processed_at` only for rows
  whose data core actually upserted. The agent plugin should carry a
  `staged_file_id` (or use the FLUSH-per-file idiom from `_process_file`,
  which gives stronger per-file `values_saved` accounting).
- **Upload API surface**: `Plugin.get_urls()` mounting DRF views
  (`urls.py`, `views/api.py`, `serializers/`) shows how the desktop app's
  upload endpoint plugs into ADL without touching core URLs.

## Bottom line

Reusable by import today: the decoder registry + all decoders (core and
third-party), `date_formats.py`, the pure date-path and mapping-merge helpers
in `utils.py`, most of `decoder_variables.py`, `StandardCSVConfig`, the
filename-date filter functions, and the test-decoder admin tool. Must be
duplicated (by design): the connection/station-link models, the two ≈20-line
mapping classes, and a staging-file model modelled on `FTPStationDataFile` +
collector-app idempotency. Refactors R1–R4 in adl-ftp-plugin (R5 optional)
would let the agent plugin share the file-matching spec, decoder resolution,
mapping auto-population, and the decode→FLUSH→stamp pipeline instead of
copying them.
