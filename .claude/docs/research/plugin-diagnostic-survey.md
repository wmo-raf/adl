# What the 11 ingestion plugins actually expose to build diagnostic contracts on

Research findings for [issue #222](https://github.com/wmo-raf/adl/issues/222),
part of map [#221](https://github.com/wmo-raf/adl/issues/221) — *Retrofit the
ingestion diagnostic contracts across the plugin fleet*.

**Status:** research only. No plugin repo was modified, and nothing was dialled.
Every claim below comes from reading the source in
`adl-project/adl-plugins/<repo>/` and `adl/adl/src/adl/core/`.

---

## Where this file lives

Same reasoning as [`celery-worker-health.md`](celery-worker-health.md): `docs/` is a
published Sphinx tree aimed at NMHS operators, so internal engineering reference
material goes to `.claude/docs/`. This note joins the `research/` subtree that
file established.

Paths in citations are relative to the `adl-project/` container. The core repo is
`adl/adl/src/adl/core/`; a plugin's package source is
`adl-plugins/<repo>/plugins/<module>/src/<module>/`, abbreviated below as
`<repo>:<file>:<line>` after each repo's section header names its full root.

## Amendments

**Amended while resolving [#226](https://github.com/wmo-raf/adl/issues/226)**
(station-scope contract). Three claims in the original survey were too strong and
have been corrected in place — finding 4, finding 5, the summary table, the #226
recommendation, and the earthnetworks and microstep evidence sections:

1. **`adl-pulsoweb-plugin` was listed as having no station-scoped read.** It has a
   station list — `get_context()["stations"]` (`client.py:31`), already feeding its
   picker — so a membership scan is available on the same terms as tahmo and
   polarisweb. (The per-repo evidence section always said this; the cross-cutting
   finding overstated it.)
2. **`adl-earthnetworks-plugin` was listed as having nothing short of the real
   data call.** True, but that call is window-parameterised and returns
   `Result.Station` independently of the observations, so a minimal window is a
   usable station check.
3. **`adl-microstep-db-plugin`'s station-scope cache was missed.**
   `get_variables_for_station()` is cached 24h *per station*, not just the
   connection-wide `get_stations()`. Its docstring also misstates the window as
   2 months where the SQL says 1 year.

Net effect: station-scope support is materially wider than the original finding 5
concluded, and cache bypass matters more at station scope than at connection scope.

---

## Question

For each of the 11 ingestion plugin repos with a `NetworkConnection` and zero
diagnostic contracts, plus the three dispatch channels lacking
`test_connection()`, **what is actually there to build a diagnostic contract
on?** Eight sub-questions per target: archetype, addressable endpoint,
credentials and cheapest read-only authenticated call, station identity,
countable source items, exception classes, `clean()` overrides, test
infrastructure.

---

## The contract being retrofitted (what the survey was looking for)

Read first, because it determines what counts as an answer.

### Four ingestion contracts

| Surface | Lives on | Base default |
|---|---|---|
| `get_source_endpoint()` → `(host, port)` or `None` | `NetworkConnection` subclass | returns `None` (`core/models.py:627-636`) |
| `check_source()` → `SourceCheckResult` | `NetworkConnection` subclass | returns `UNSUPPORTED` (`core/models.py:638-653`) |
| `check_station_source()` → `SourceCheckResult` | `StationLink` subclass | returns `UNSUPPORTED` (`core/models.py:769-788`) |
| `station_link.adl_sources_count` (duck-typed attribute) | inside `get_station_data()` | initialised to `None` each run (`core/registries.py:829`) |

**Core owns layer 4 entirely.** `run_source_probe` performs DNS resolution then a
TCP connect against whatever `get_source_endpoint()` names, and only then calls
the plugin's `check_source()` (`core/source_checks.py:163-181`). A plugin never
implements network probing itself — it only *names its endpoint*. This is why
question 2 ("is there a host and port?") is the single highest-leverage question
in the survey: naming a host is a one-line change that buys two of the six
diagnostic layers for free.

**Nothing is trusted.** Every plugin return passes through
`normalise_source_check_result` (`core/source_checks.py:94-118`): a non-
`SourceCheckResult` or an unknown status degrades to `MALFORMED`, an unknown
category is dropped, and the message is redacted. A raised exception becomes a
`FAILED` step rather than a crash (`core/source_checks.py:283-290`), and the
whole probe shares one wall-clock budget.

**`UNSUPPORTED` is independently answerable per contract.**
`connection_implements_check_source` and
`station_link_implements_check_station_source`
(`core/source_checks.py:121-136`) compare the subclass's method identity against
the base class's, with no I/O. A plugin implementing `check_source()` has said
nothing about `check_station_source()` — the two retrofits can land separately.

**The sources-count handover is deliberately tri-state.**
`_sanitize_sources_count` (`core/registries.py:35-46`) accepts only a
non-negative `int`; anything else — missing, negative, float, string, bool —
degrades to `None`. `None` means *did not look*, `0` means *looked, found
nothing*, `n` means *found n*. `0` is the fault value and must never be
manufactured from a malformed report, which is why the FTP reference sets the
attribute only once listing actually starts (`adl-ftp-plugin:plugins.py:94`) and
increments per resolved item (`:98`).

### Exception classification

`classify_failure` (`core/classification.py:81-102`) checks a duck-typed
`adl_category` / `adl_layer` on the raised exception **first**, validating both
against closed vocabularies — `FAILURE_CATEGORIES` (`core/classification.py:31-41`:
`DNS_FAILURE`, `TCP_REFUSED`, `TCP_TIMEOUT`, `TLS_FAILURE`, `AUTH_FAILED`,
`PERMISSION_DENIED`, `PATH_NOT_FOUND`, `PROTOCOL_ERROR`, `UNKNOWN`) and
`FAILURE_LAYERS` (`:47`: 4 or 5). Duck-typing is how a plugin opts in without
importing from core, which would break at import time against an older core.

Failing that, an MRO walk over `EXCEPTION_TYPE_TABLE`
(`core/classification.py:60-69`) matches fully-qualified class names as
**strings**, so core recognises `requests.exceptions.ConnectTimeout` without
importing `requests`. Otherwise core declines with `(None, None)` rather than
guessing — a wrong write-time stamp is permanent.

Critically, the table's comment block (`core/classification.py:54-59`) names four
classes **deliberately absent** because one class spans several categories:
`ftplib.error_perm`, `psycopg2.OperationalError`,
`requests.exceptions.ConnectionError`, and `builtins.TimeoutError`. Two of those
four are the *primary* failure type of archetypes in this survey — see the
[direct-database](#the-psycopg2operationalerror-problem) note below.

### The dispatch contract

`DispatchChannel.test_connection()` must return a `Mapping` with keys `ok`,
`supported`, `message` (`core/dispatch_checks.py:39`), optionally `latency_ms`,
and never raise. `run_dispatch_connection_test` (`:111-159`) wraps it under the
shared wall-clock bound and passes the return through
`normalise_dispatch_test_result` (`:63-101`), which reports a non-conforming
return as a channel-side failure naming the offending type. Note the module
docstring's own history (`:6-11`): the contract had already drifted on its first
out-of-core implementation.

### The reference implementation

`adl-ftp-plugin` commit `dd9a7ba`, *feat: ingestion diagnostic source-check
contracts*, is the only plugin of 21 implementing any of this. Its shape is the
standard every retrofit inherits:

- `get_source_endpoint()` returns `(self.host, self.effective_port)`
  (`adl-ftp-plugin:models.py:486-489`).
- `check_source()` connects and authenticates, writes nothing, and closes
  (`:491-...`), mapping error status codes to categories through a module-level
  dict `SOURCE_CHECK_ERROR_CATEGORIES` that deliberately **omits** the ambiguous
  code 502 rather than guessing.
- `check_station_source()` resolves the station's remote path, lists it
  read-only, and reports the resolved path and match count (`:826-...`). **Zero
  matches is `OK` by design** — a date-structured directory is legitimately empty
  at every rollover, and the operator judges the resolved path better than a rule
  can.
- `adl.core.source_checks` is imported **lazily inside each method**, never at
  module level, so the plugin still imports cleanly against a core release
  predating the contracts.
- Tests are DB-free `SimpleTestCase` with stubbed clients
  (`adl-ftp-plugin:tests/test_source_checks.py`), plus an AST test
  (`:278-298`) that parses `models.py` and `plugins.py` and asserts no
  module-level import of `adl.core.source_checks` — treating `col_offset != 0` as
  proof an import is inside a function.

---

## Summary table

Ingestion plugins (11) — all currently report `UNSUPPORTED` on every contract.

| Repo | Archetype | Endpoint available? | Read-only auth call | Station-scope call | Countable point | Exceptions | `clean()` | Tests |
|---|---|---|---|---|---|---|---|---|
| `adl-adcon-db-plugin` | direct DB (psycopg2) | **Yes — fields** `db_host`/`db_port` | `psycopg2.connect()` alone; or `get_stations()` | `get_adcon_parameters_for_station()` | `fetchall()` `db.py:72` | none defined; `psycopg2.OperationalError` escapes | none | none |
| `adl-microstep-db-plugin` | direct DB (psycopg2) | **Yes — fields** `db_host`/`db_port` | `psycopg2.connect()` alone (`get_stations()` is 24h-cached) | `get_variables_for_station()` — exists, unused | `fetchall()` `db.py:166` | none defined; `psycopg2.OperationalError` escapes | none | none |
| `adl-tahmo-plugin` | HTTP/REST (basic auth) | No field — **hard-coded** `client.py:9` | `get_stations()` (`/services/assets/v2/stations`) | none; membership test on `get_stations()` | `values` `client.py:97` | none defined; `requests.HTTPError` escapes | none | none |
| `adl-weatherlink-plugin` | HTTP/REST (key + secret header) | **Yes — field** `api_base_url` | `get_stations()` (`/stations`) | **`get_station(id)` exists** `client.py:45` | `sensors` `client.py:147` | none defined; `requests.HTTPError` escapes | none | none |
| `adl-cimawebdrops-plugin` | HTTP/REST (OAuth2 password grant) | **Yes — fields** `token_endpoint`, `api_base_url` | `get_sensor_classes()` (`/sensors/classes/`) | `get_station_parameters()` — returns `[]`, never errors | `sensors_info` `plugins.py:56` | none defined; `requests.HTTPError` escapes | none | none |
| `adl-earthnetworks-plugin` | HTTP/REST (**no auth at all**) | No field — **hard-coded** `client.py:33` | **none exists** — no credential, no station-independent endpoint | `fetch_raw()` is the ingestion call, but **window-parameterised**; `Result.Station` is independent of the observations | `hist` `client.py:123` (inside client) | `RuntimeError` `client.py:108` (code in string only) | none | none |
| `adl-fieldclimate-plugin` | HTTP/REST (OAuth2 password grant) | No field — **hard-coded** `client.py:28-29` | client `__init__` authenticates (`client.py:72`); then `get_user_stations()` | `get_station_sensors(id)` exists, unused | `rows` `client.py:322` | `Exception`/`RuntimeError`, untyped | none | none |
| `adl-iosnet-plugin` | THREDDS catalog (siphon) — **non-functional stub** | No field — **hard-coded** `client.py:5` | **n/a — module does not parse** | n/a | n/a — `get_station_data()` returns `[]` | none | none | none |
| `adl-pulsoweb-plugin` | HTTP/REST (token in POST body) | **Yes — field** `api_base_url` | `get_context()` (POST `/get_context/`, 1h-cached) | none dedicated; membership scan over `get_context()["stations"]` `client.py:31` | inside `get_observation_data()` `client.py:176` | `PulsoWebConnectionError` **defined but never raised**; **no `raise_for_status()` anywhere** | none | none |
| `adl-siapmicros-polarisweb-plugin` | HTTP/REST (token query param) | **Yes — field** `host` (URL, may carry explicit port) | `get_stations()` (`/api/polaris/…`) | none; membership test on `get_stations()` | `measure_ids` `plugins.py:30-33` | none defined; `requests.HTTPError` escapes | none | none |
| `adl-collector-app-plugin` | **local DB — no upstream at all** | **Structurally none** | **n/a — nothing to authenticate against** | pending-submission count (local query) | `qs` / `records` `plugins.py:82-96`, `:122` | none relevant | `CollectorSubmission.clean()` — *not* a config model | **`tests/` exists** (`test_synop_utils.py`) |

Dispatch channels (3).

| Channel | Archetype | Destination fields | Read-only proof | Exceptions | `clean()` | Tests |
|---|---|---|---|---|---|---|
| `FTPUpload` (`adl-ftp-plugin`) | FTP/FTPS/SFTP | on `BaseFTPUpload`: `host` `:930`, `port` `:931`, `user`, `password`, `directory` | `get_client()` + `close()` — login happens in `__init__` | `FTPError`/`SFTPError`, **carry `.status`** | `BaseFTPUpload.clean()` `:962`, no I/O | **yes**, DB-free |
| `SmartMetFTPUpload` (`adl-ftp-plugin`) | same base, same client | same (`BaseFTPUpload`) | same; note `upload_stations_metadata()` **writes** on every save | same | same | same |
| `adl-smartmet-dispatch-plugin` | **empty scaffold** — `models.py` is 0 bytes | **none — no model exists** | n/a | none | none | none |

---

## Cross-cutting findings

These are what change the shape of the downstream design tickets.

### 1. Two of the eleven are not implemented plugins at all

**`adl-iosnet-plugin` does not parse.** `client.py` ends at line 16 with
`def get_countries_list(self):` and no body; `python3 -c "ast.parse(...)"` raises
`IndentationError: expected an indented block after function definition on line
16`. Beyond that: `station_link_model_string_label = ""` (`models.py:8`) — the
authoring guide's named failure mode, so the admin cannot link stations;
`get_station_data()` unconditionally `return []` (`plugins.py:12`); the class is
still the cookiecutter's `PluginNamePlugin` (`plugins.py:4`); there is no
`VariableMapping` model of any pattern; the connection's only field is `country`,
under a panel heading that reads `"TAHMO API Credentials"` (`models.py:15`) —
copy-paste residue. The repo has **no `.git` directory**, unlike its siblings.

**`adl-smartmet-dispatch-plugin` is empty scaffolding.** `models.py`, `views.py`
and `wagtail_hooks.py` are all 0 bytes; `plugins.py` (12 lines) is still
`PluginNamePlugin` with `get_station_data()` returning `[]`. There is **no
`DispatchChannel` subclass** — so `test_connection()` has nothing to attach to.
It is not "a channel lacking `test_connection()`"; it is a channel that does not
exist.

Neither can receive a retrofit. They need a decision — implement, or drop from
the fleet — before any contract work is scheduled against them.

### 2. `adl-collector-app-plugin` is an archetype the map did not anticipate

It has no upstream. `get_station_data()` queries **ADL's own database**:
`CollectorSubmissionRecord.objects.filter(submission__station_link=station_link,
submission__is_test_submission=False, is_processed=False)` (`plugins.py:82-96`).
`ManualObservationConnection` (`models/connection.py:8-32`) holds two booleans —
`enable_office_entry`, `enable_field_app` — and no credential, host, or URL of
any kind. Data arrives by human beings submitting through a PWA and office entry
forms.

Consequences, which are structural rather than a matter of effort:

- `get_source_endpoint()` — **permanently `UNSUPPORTED`**. There is no host.
- `check_source()` — layer 4/5 have no meaning. Any implementation would be a
  *local* readiness check (are there observers, is a schedule configured), which
  is a different question wearing the same method name. Recommend leaving it
  `UNSUPPORTED` rather than overloading the contract.
- `check_station_source()` — the one contract that *does* map, and usefully: the
  station-scoped question "is data available upstream" becomes "are there pending
  unprocessed submissions for this station", answerable from the same queryset.
- `adl_sources_count` — **the cheapest win in the entire fleet.** The count is
  already computed and already logged: `len(records)` at `plugins.py:122`. It is
  a one-line assignment.

The failure vocabulary (`DNS_FAILURE`, `TCP_REFUSED`, …) is entirely network-
shaped and has no member that fits "nobody submitted an observation." This
plugin is where the diagnostic's six-layer model stops describing reality.

### 3. Endpoint availability splits 6 / 4, and the hard-coded four are the tell

**Six name their endpoint in a model field** and can implement
`get_source_endpoint()` almost trivially: `adl-adcon-db-plugin` and
`adl-microstep-db-plugin` (`db_host` + `db_port`, already a literal host/port
pair), `adl-weatherlink-plugin` (`api_base_url`), `adl-cimawebdrops-plugin`
(`token_endpoint`, `api_base_url`), `adl-pulsoweb-plugin` (`api_base_url`), and
`adl-siapmicros-polarisweb-plugin` (`host`, whose help text example
`http://102.218.136.213:88` shows it carries an **explicit non-default port** —
so `urlparse` must honour `.port` and not assume 443/80).

**Four hard-code it in the client module**, with no field to read:

| Repo | Hard-coded at | Host | Port |
|---|---|---|---|
| `adl-tahmo-plugin` | `client.py:9` (constructor default, never overridden by `get_api_client()` `models.py:50-54`) | `datahub.tahmo.org` | 443 |
| `adl-fieldclimate-plugin` | `client.py:28-29` (class constants `OAUTH_URL`, `API_BASE_URL`) | `oauth.fieldclimate.com`, `api.fieldclimate.com` | 443 |
| `adl-earthnetworks-plugin` | `client.py:33` (dataclass field default) | `owc.enterprise.earthnetworks.com` | 443 |
| `adl-iosnet-plugin` | `client.py:5` | `galilee.univ-reunion.fr` | 443 |

This is still implementable — `get_source_endpoint()` may return a constant — but
it is a design decision, not a mechanical one: the returned host would be a
literal duplicated from the client, and the two can drift. Note also that
`adl-fieldclimate-plugin` has **two** hosts (auth and data are different names),
so a single `(host, port)` return cannot cover both; whichever is chosen, the
other is unprobed.

### 4. The "cheapest read-only call" already exists in most repos — as a station picker

Six plugins already have exactly the call `check_source()` needs, written for a
different purpose: the admin's station-select widget fetches a station list over
AJAX, which incidentally proves credentials and reachability.

| Repo | Method | Wired to |
|---|---|---|
| `adl-tahmo-plugin` | `get_stations()` `client.py:20-41` | `views.py:10-29` → `TahmoStationSelectWidget` |
| `adl-weatherlink-plugin` | `get_stations()` `client.py:22-43` | `views.py:8-37` → `WeatherLinkStationSelectWidget` |
| `adl-cimawebdrops-plugin` | `get_stations()` `client.py:181-206` | `views.py:9-28` → `CimaWebDropsStationSelectWidget` |
| `adl-siapmicros-polarisweb-plugin` | `get_stations()` `client.py:36` | `PolarisStationSelectWidget` (`models.py:112`) |
| `adl-adcon-db-plugin` | `get_stations()` `db.py:20-32` | `views.py:13-36` |
| `adl-microstep-db-plugin` | `get_stations()` `db.py:27-57` | `views.py:9-35` |

**But there is a trap: five of these are aggressively cached.** `adl-tahmo-plugin`
(`client.py:38-39`, 86400s), `adl-weatherlink-plugin` (`client.py:40-41`),
`adl-cimawebdrops-plugin` (`client.py:56-244`, 24h), `adl-microstep-db-plugin`
(`db.py:9,36-39,54`, 24h) and `adl-pulsoweb-plugin` (`client.py:150-161`, 1h) all
serve `get_stations()`/`get_context()` from `django.core.cache` by default.
`adl-microstep-db-plugin` caches at station scope too — `get_variables_for_station()`
(`db.py:91-129`) is cached 24h **per station** — so the trap is not confined to the
connection-scope list. A
`check_source()` built naively on these would **report OK from cache while the
source is down** — the exact false negative the diagnostic exists to prevent.
Worse, the connection's `get_api_client()` factories do not thread a
`use_cache=False` through (e.g. `TahmoConnection.get_api_client()`
`models.py:50-54`, `WeatherLinkConnection.get_api_client()` `models.py:44-48`),
so bypassing the cache requires changing the factory, not just the call site.

**This should be a stated rule in the plugin-author guide:** `check_source()`
must bypass any response cache. It is the single most likely way a retrofit ships
looking correct and is silently useless.

For the two direct-DB plugins there is a cheaper option than any query:
`psycopg2.connect()` completes authentication at connection time, so building the
client and closing it proves the credential — exactly the shape
`NetworkFTP.check_source()` uses (`adl-ftp-plugin:models.py:491-511`), and cache-free
by construction.

### 5. Station-scope support is thin — only two plugins have a real primitive

Only `adl-weatherlink-plugin` (`get_station(station_id)` `client.py:45-52`) and
`adl-microstep-db-plugin` (`get_variables_for_station()` `db.py:91-129`, which
joins against `values_f_hist` with a one-year window and therefore proves the
station has actually *produced data*) have a genuine station-existence call.
Both are currently **dead code** — neither is invoked anywhere in its plugin.

`adl-adcon-db-plugin`'s `get_adcon_parameters_for_station()` (`db.py:34-47`)
proves the station node has child tag nodes, but not that data exists.

`adl-cimawebdrops-plugin`'s `get_station_parameters()` (`client.py:208-244`)
**cannot fail**: a missing station returns `[]` (`client.py:219-222`). Used as-is
it would report `OK` for a typo'd station ID. It needs an explicit
"station not in `get_stations()`" branch before it can carry the contract.

For `adl-tahmo-plugin` and `adl-siapmicros-polarisweb-plugin` the honest cheap
implementation is a membership test against the (uncached) station list.

`adl-pulsoweb-plugin` has no *dedicated* station call, but it does have a station
list: `get_context()["stations"]` (`client.py:31`, wrapped by
`get_stations_metadata()` `client.py:29-32`), already feeding the picker at
`views.py:53`. A client-side membership scan is available on exactly the same
terms as tahmo and polarisweb above. Cached 1h, so it must be bypassed.

`adl-earthnetworks-plugin` has no station-independent endpoint at all, so the
*connection*-scope check is the one that cannot be built and the station-scope
check is the only one that can — the inverse of every other plugin. Its only
station-scoped read is the ingestion call, but that call is **window-parameterised**:
`fetch_raw(station_id, start_utc, end_utc)` (`client.py:94`), and `normalize()`
(`client.py:113`) reads `Result.Station` — `StationName`, `Inactive`, coordinates —
*independently* of `HistoricalObservations`. A minimal window therefore returns
station identity, the upstream's own label and an inactive flag for near-zero
payload, which is a usable station check rather than a dead end.

### 6. The countable point exists everywhere the plugin functions — but often inside the client

Nine of eleven have a materialised list before conversion. The complication is
*where*: for the two direct-DB plugins the count is `len(data)` right after
`fetchall()` (`adcon db.py:72`, `microstep db.py:166`), and for TAHMO, WeatherLink,
FieldClimate and EarthNetworks it is inside `client.py`, not inside
`get_station_data()`. The duck-typed handover writes to `station_link`, which the
client does not hold a reference to — so these retrofits require either passing
the station link down, returning a count alongside the records, or hoisting the
listing step up into the plugin.

Three are clean: `adl-cimawebdrops-plugin` counts `sensors_info` in
`plugins.py:45-56`; `adl-siapmicros-polarisweb-plugin` has `measure_ids` in
`plugins.py:30-33`; `adl-collector-app-plugin` already computes `len(records)` at
`plugins.py:122`.

Note that `adl-cimawebdrops-plugin` and `adl-siapmicros-polarisweb-plugin` would
be counting *configured variable mappings*, not items the source returned — a
count that is knowable without touching the network and therefore says nothing
about the source. That is a misuse of the field. The tri-state semantics
(`core/registries.py:35-46`) mean the count must describe *what the source
offered*; where a plugin can only count its own configuration, `None` is the
correct answer.

### 7. Exception classification has almost nothing to build on — and core's table already declines the two commonest types

**No ingestion plugin defines a single exception class carrying a status code.**
`adl-pulsoweb-plugin` defines `PulsoWebConnectionError` (`client.py:7`) — and
**never raises it**; grep across the repo finds only the class statement.

What escapes today:

- Seven HTTP plugins leak raw `requests` exceptions from `raise_for_status()`.
  `requests.HTTPError` does carry `.response.status_code`, so 401/403/404 → 
  `AUTH_FAILED`/`PERMISSION_DENIED`/`PATH_NOT_FOUND` is mechanical — but
  **`requests.exceptions.ConnectionError` is deliberately absent from core's
  `EXCEPTION_TYPE_TABLE`** (`core/classification.py:58`) because it collapses DNS,
  refused and reset into one class. That is the single commonest transport
  failure for this archetype, and core declines it by design.
- The two direct-DB plugins leak `psycopg2.OperationalError`, **also deliberately
  absent** (`core/classification.py:57`) because it spans refused, timeout and
  auth. Both plugins catch bare `Exception`, log, and `raise e` unchanged
  (`adcon plugins.py:41-43`, `microstep plugins.py:70-75`) — a pure pass-through
  with zero classification.

<a id="the-psycopg2operationalerror-problem"></a>
**So for both major archetypes, the exception type that actually fires most often
is one core refuses to classify.** Duck-typing `adl_category` onto a raw
third-party exception is not possible without wrapping it, which means the
classification retrofit is not a one-line opt-in for these plugins — it requires
each plugin to introduce its own exception type and a mapping, as
`adl-ftp-plugin` did with `SOURCE_CHECK_ERROR_CATEGORIES` (`models.py:44-49`) over
its own `FTPError.status`. Budget accordingly.

**`adl-pulsoweb-plugin` is worse than unclassified — it is undetectable.** Its
`post()` (`client.py:122-133`) calls `requests.post(...)` and returns
`response.json()` **without `raise_for_status()`**; grep confirms the method is
called nowhere in the repo. A 401 or a 500 HTML error page surfaces as a JSON
decode error, if at all. Before classification can mean anything here, the client
needs error checking at all.

The same call site (`client.py:132`) also passes **no `timeout`**. Requests
without a timeout block indefinitely, so `TCP_TIMEOUT` is not merely unmapped
here — it is unreachable, and a hung source would wedge the ingestion worker
rather than fail it. Fixing the timeout is a prerequisite for this plugin's
`check_source()` to be able to return at all within core's wall-clock budget.

`adl-earthnetworks-plugin` raises `RuntimeError` with the upstream code
interpolated into the **message string** (`client.py:108`) — recoverable only by
parsing text, which `core/classification.py`'s opening docstring explicitly rules
out ("matched on the exception's *type*, never its text").

### 8. `clean()` — the audit finding is that there is nothing to audit

**No `NetworkConnection` or `StationLink` subclass in any of the eleven ingestion
plugins overrides `clean()`.** Verified by grep across all plugin sources: the
only `clean()` overrides in the whole fleet are in `adl-ftp-plugin`
(`models.py:275, 384, 749, 962`), `adl-s3-plugin` (`models.py:122, 317`), and
`adl-collector-app-plugin` (`models/submission.py:96`).

The collector-app one **is not a config model**: it is on `CollectorSubmission`,
a per-observation record, asserting that an observer or office submitter is set
and that timestamps are timezone-aware and not in the future. Config-drift
detection re-runs `full_clean()` on stored *connection and station-link* rows, so
this override is invisible to it. The map's fleet-as-found line, "`clean()`
overrides exist only in `adl-ftp-plugin`, `adl-s3-plugin` and
`adl-collector-app-plugin`", is literally true but overstates collector-app's
relevance — for config-drift purposes the count is **two**, not three.

What all eleven have instead is a field-level `validators=[validate_start_date]`
on `start_date` — a pure in-memory comparison against `timezone.now()` with no
I/O, e.g. `adl-adcon-db-plugin:validators.py:8-19`. No plugin performs I/O in a
`clean()`, so the standing "no I/O in `clean()`" rule is currently unviolated
fleet-wide.

Given the map's standing decision that config drift is audit-and-recommend only,
the honest recommendation for most of these repos is **leave it**: adding
assertions now would retroactively flag stored rows as `MISCONFIGURED` across 26
deployments, and there is no existing rule whose absence is causing a fault.

### 9. Test infrastructure: one repo has the standard, one has a suite, nine have nothing

- `adl-ftp-plugin` has the reference suite (`tests/test_source_checks.py`,
  DB-free `SimpleTestCase`, stubbed clients, AST lazy-import guard).
- **`adl-collector-app-plugin` already has a `tests/` package**
  (`tests/test_synop_utils.py`) — the map did not record this. It is unrelated to
  the diagnostic contracts, and narrowly scoped: 108 lines of module-level
  `def test_*()` functions over pure helpers, with no `django.test.TestCase`, no
  `@pytest.mark.django_db` and no fixtures — so it is DB-free, but by pytest
  convention rather than the `SimpleTestCase` idiom the FTP standard uses. There
  is no `conftest.py` or `pytest.ini`, and `pytest` is not listed in
  `requirements/dev.in`. The packaging scaffolding is solved; the runner
  convention is not, and it differs from the reference.
- The other nine ingestion repos and `adl-smartmet-dispatch-plugin` have no
  `tests/` directory at all.

**There is no test runner configuration anywhere in the fleet, including in
`adl-ftp-plugin`.** No `pytest.ini`, no `tox.ini`, no `test_suite` in `setup.py`,
and **no `test` target in any plugin `Makefile`** — `adl-ftp-plugin`'s Makefile has
only `lint`, `lint-python` and `format`. The FTP suite runs via the container's
Django test runner (`adl test`), by convention, undocumented in the repo.

Two consequences for the retrofit:

- Every plugin Makefile's lint target is `flake8 src tests` — which references a
  `tests` directory that does not exist in nine of these repos, so **`make lint`
  already fails there today**, before any retrofit work.
- The cookiecutter at `adl/plugin-boilerplate/` ships **no `tests/` directory and
  no test target**. Since the map puts the boilerplate in scope so that plugin #22
  is diagnostic-ready on day one, the boilerplate needs the test scaffolding
  added, not just the contract stubs.

---

## Recommendations for the downstream design tickets

Stated as findings that constrain the design, not as decisions.

**#224 (direct DB).** The easiest archetype: both plugins already have
`db_host`/`db_port` as fields, and `psycopg2.connect()` is a cache-free credential
proof. The hard part is exclusively exception classification — see finding 7.
`adl-microstep-db-plugin` is Pattern C (hybrid connection + station variable
mappings, `models.py:51-91` and `:145-185`), not Pattern A as
`adl-project/.claude/CLAUDE.md`'s archetype table records; worth correcting there.

**#225 (HTTP/REST).** Split the ticket by endpoint availability (finding 3), and
make cache-bypass a mandatory acceptance criterion (finding 4). Note
`adl-fieldclimate-plugin` is **OAuth2 password grant, not HMAC** — and that its
client authenticates eagerly in `__init__` (`client.py:72`), so merely
constructing it is the credential check. `adl-earthnetworks-plugin` has **no
credentials at all** and belongs in its own bucket.

**#226 (station scope).** Only two plugins have a *dedicated* primitive, both dead
code (finding 5), but five more can run a membership scan over a station list they
already fetch, and `adl-earthnetworks-plugin`'s window-parameterised ingestion call
carries station identity separately from the observations. Every station list in
play is cached, so cache bypass is load-bearing here in a way it is not at
connection scope — a stale list turns a newly-added station into a confident false
"does not exist". `adl-cimawebdrops-plugin` needs a not-found branch added before
its existing call can carry the contract. `adl-earthnetworks-plugin` inverts the
usual shape: station scope is possible, connection scope is not.

**#227 (sources count).** Three plugins are one-liners; six need the count hoisted
out of `client.py` or threaded back (finding 6). Guard against the
count-your-own-config misuse in `adl-cimawebdrops-plugin` and
`adl-siapmicros-polarisweb-plugin`.

**#228 (exception classification).** Not a one-line opt-in for any of these
plugins. Core deliberately declines both dominant exception types, so each
retrofit means introducing a plugin-owned exception type — the
`adl-ftp-plugin` `FTPError.status` pattern. `adl-pulsoweb-plugin` needs
`raise_for_status()` before classification is even meaningful.

**#229 (dispatch).** `FTPUpload` and `SmartMetFTPUpload` are the cheapest work in
the whole map: `BaseFTPUpload.get_client()` (`models.py:1017`) already authenticates
on construction, and `SOURCE_CHECK_ERROR_CATEGORIES` (`models.py:44-49`) is already
in the same file. `adl-smartmet-dispatch-plugin` has no channel to fix and should
leave the ticket. Note `SmartMetFTPUpload.upload_stations_metadata()`
(`models.py:1125-1149`) **writes** on every save via a `post_save` signal
(`:1155-1177`) — do not reuse it as the read-only probe.

**A stale core docstring, found in passing.** `core/dispatch_checks.py:8-10`
states that `adl-s3-plugin` returns a `(bool, str)` tuple. It no longer does:
`BaseS3Upload.test_connection()` (`adl-s3-plugin:models.py:170-208`) returns the
documented dict with `ok`, `supported`, `message` and `latency_ms`, fixed in that
repo's commit `ce8e76a`. The containment in `dispatch_checks.py` remains correct
and worth keeping; only the docstring's present tense is wrong.

**A possible bug, found in passing.**
`adl-adcon-db-plugin`'s `ADCONVariableMapping.adcon_parameter_id` is declared
`unique=True` (`models.py:86`) — globally, across all stations, not per station
link. Out of scope here; worth its own issue.

---

## Per-repo evidence

Each section's citations are relative to that repo's package root,
`adl-plugins/<repo>/plugins/<module>/src/<module>/`, unless stated otherwise.

### `adl-adcon-db-plugin`

Models `ADCONDBConnection` (`models.py:12`), `ADCONStationLink` (`models.py:48`).

1. **Archetype** — direct database. `import psycopg2` (`db.py:3`),
   `psycopg2.connect(...)` (`db.py:8-14`), against an ADCON historian schema
   (`node_60`, `historiandata`).
2. **Endpoint** — `db_host` (`models.py:14`) and `db_port` (`models.py:15`) are
   model fields, alongside `db_name` (`:16`), `db_user` (`:17`), `db_password`
   (`:18`), passed to the client at `models.py:39-45`. Nothing hard-coded. This
   is the cleanest `get_source_endpoint()` in the fleet — a literal host/port
   pair with no parsing.
3. **Cheapest read-only call** — `psycopg2.connect()` itself: PostgreSQL
   authenticates at connection time, so constructing the client and closing it
   proves the credential without issuing a query. Next cheapest is
   `get_stations()` (`db.py:20-32`), `SELECT id, displayname, latitude, longitude,
   timezoneid FROM node_60 WHERE dtype='DeviceNode'`, already exposed at
   `views.py:13-36` and `wagtail_hooks.py:15-16`.
4. **Station identity** — `adcon_station_id` (`models.py:49-50`).
   `get_adcon_parameters_for_station()` (`db.py:34-47`) queries
   `node_60 WHERE dtype='AnalogTagNode' AND parent_id = %s`, wired at
   `views.py:39-54`. Proves the station node exists and has child tag nodes; does
   **not** prove data exists.
5. **Countable point** — `data = conn_cursor.fetchall()` (`db.py:72`), before the
   reshaping loop at `db.py:77-97`. Fully materialised, not streamed. Inside the
   client, not `get_station_data()` (`plugins.py:15-45`).
6. **Exceptions** — none defined. `plugins.py:41-43` catches bare `Exception`,
   logs, and `raise e` unchanged. `psycopg2.OperationalError` escapes from
   `db.py:8-14`; `psycopg2.Error` subclasses from `db.py:27,40,70`. One guard
   `raise ValueError` at `db.py:55`.
7. **`clean()`** — none. `validate_start_date` (`validators.py:8-19`) is a field
   validator on `models.py:51`, pure comparison, no I/O.
8. **Tests** — none.

Also noted: `ADCONVariableMapping.adcon_parameter_id` is `unique=True`
(`models.py:86`) globally rather than per station link.

### `adl-microstep-db-plugin`

Models `MicroStepDBConnection` (`models.py:11`), `MicroStepStationLink`
(`models.py:94`).

1. **Archetype** — direct database. `import psycopg2` (`db.py:3`), plus
   `django.core.cache` (`db.py:4`). Schema: `stations`, `variables`,
   `values_f_hist`.
2. **Endpoint** — `db_host` (`models.py:14`), `db_port` (`models.py:15`, default
   5432), `db_name`/`db_user`/`db_password` (`:16-18`), passed at
   `models.py:42-48`; client connects at `db.py:15-21`. Note the client import is
   already deferred inside the method (`models.py:41`), a precedent for the lazy
   import the contract requires.
3. **Cheapest read-only call** — `psycopg2.connect()` itself, as above.
   `get_stations()` (`db.py:27-57`) is **cached for 24h**
   (`db.py:9`, read `:36-39`, write `:54`) keyed on
   `self.connection.info.host`/`dbname` (`db.py:33`) — a cache hit does not touch
   the database, so it must not be the basis of `check_source()`.
4. **Station identity** — `microstep_station_id` (`models.py:95-98`).
   `get_variables_for_station()` (`db.py:91-129`) joins
   `variables v INNER JOIN values_f_hist vf ON v.id=vf.varid WHERE vf.stationid =
   %s AND vf.meastime >= NOW() - INTERVAL '1 year'` — genuinely proves the station
   has produced data. **Cached 24h per station** (`db.py:10`, key `:98`, read `:101`, write `:126`),
   so it carries the same cache trap as `get_stations()` in item 3. Its docstring
   claims "only checks the last 2 months of data" while the SQL says
   `INTERVAL '1 year'` — the SQL is what runs. It is **dead code**: `utils.py:6-25`
   deliberately calls
   `get_all_variables()` instead, per the comment "MicroStep does not have
   station-specific variables" (`utils.py:14`). The best station-scope primitive
   in the fleet, currently unused.
5. **Countable point** — `data = cursor.fetchall()` (`db.py:166`), before the
   reshape loop at `db.py:171-191`. The plugin separately logs the *post*-reshape
   count at `plugins.py:64-66` — a log line, not the handover.
6. **Exceptions** — none defined. `plugins.py:70-75` catches bare `Exception`,
   logs with `exc_info=True`, `raise e`. `psycopg2.OperationalError` from
   `db.py:15-21`; `psycopg2.Error` from `db.py:45,77,117,165`. Guard
   `raise ValueError` at `db.py:146`.
7. **`clean()`** — none. `validate_start_date` (`validators.py:8-14`) on
   `models.py:99-108`.
8. **Tests** — none.

Also noted: this plugin uses **variable-mapping Pattern C** (hybrid) —
`MicroStepConnectionVariableMapping` (`models.py:51-91`) and
`MicroStepStationVariableMapping` (`models.py:145-185`), merged in
`get_variable_mappings()` (`models.py:130-138`) — not Pattern A as
`adl-project/.claude/CLAUDE.md`'s archetype table records.

### `adl-tahmo-plugin`

Models `TahmoConnection` (`models.py:18`), `TahmoStationLink` (`models.py:57`).

1. **Archetype** — HTTP/REST. `import requests` (`client.py:1`), HTTP Basic auth
   (`from requests.auth import HTTPBasicAuth`, `client.py:3`; `HTTPBasicAuth(api_key,
   api_secret)`, `client.py:18`), passed on every call (`client.py:26,49,83`).
2. **Endpoint** — **no field.** Only `api_key` (`models.py:24`) and `api_secret`
   (`models.py:25`). Base URL is the client constructor default
   `base_url='https://datahub.tahmo.org'` (`client.py:9`), and
   `get_api_client()` (`models.py:50-54`) never overrides it. Host
   `datahub.tahmo.org`, port 443.
3. **Cheapest read-only call** — `get_stations()` (`client.py:20-41`,
   `GET /services/assets/v2/stations` at `:25-26`), already wired at
   `views.py:10-29` via `utils.get_stations` (`utils.py:1-14`) to
   `TahmoStationSelectWidget` (`widgets.py:5-15`), URL at `wagtail_hooks.py:14-15`.
   `get_variables()` (`client.py:43-65`) is a cheaper alternative.
   **Both cache for 86400s** (`client.py:38-39`, `:62-63`), with `use_cache=True`
   the default (`client.py`), and `get_api_client()` does not thread a bypass.
4. **Station identity** — `tahmo_station_code` (`models.py:61`). No single-station
   call; `get_measurements()` (`client.py:67-116`) is the real ingestion call. The
   honest cheap check is membership against the dict `get_stations()` returns
   (keyed by code, `client.py:32-35`) — not currently implemented.
5. **Countable point** — `values = data.get('values', [])` (`client.py:97`),
   before the loop at `:99-114`. Inside the client.
6. **Exceptions** — none defined. `requests.HTTPError` from `raise_for_status()`
   at `client.py:28,50,84`; `requests.ConnectionError`/`Timeout` from
   `client.py:26,49,83` unhandled. No `try/except` anywhere.
7. **`clean()`** — none.
8. **Tests** — none. `Makefile:2` lints `flake8 src tests` against a `tests`
   directory that does not exist.

### `adl-weatherlink-plugin`

Models `WeatherLinkConnection` (`models.py:18`), `WeatherLinkStationLink`
(`models.py:51`).

1. **Archetype** — HTTP/REST. `import requests` (`client.py:3`); API key as a
   query param and secret as a header (`self.headers = {"X-Api-Secret":
   api_secret}`, `client.py:18-20`; `client.py:27`).
2. **Endpoint** — **field present**: `api_base_url = models.URLField(...,
   default="https://api.weatherlink.com/v2")` (`models.py:24-25`), panelled at
   `:31`, passed through at `models.py:44-48`. Host derives by `urlparse`;
   default host `api.weatherlink.com`, port 443.
3. **Cheapest read-only call** — `get_stations()` (`client.py:22-43`,
   `GET {base}stations?api-key=…` at `:27-28`), wired at `views.py:8-37` to
   `WeatherLinkStationSelectWidget` (`widgets.py:6-16`), URL at
   `wagtail_hooks.py:15-16`. Caches at `client.py:40-41` (also `:74-75`,
   `:100-102`); `get_api_client()` (`models.py:44-48`) passes no cache bypass.
4. **Station identity** — `weatherlink_station_id` (`models.py:55`).
   **`get_station(station_id)` already exists** (`client.py:45-52`): calls
   `get_stations()` (`:47`) and does `stations.get(station_id)` (`:49-52`),
   returning `None` when absent. Read-only, proves existence, and is called
   nowhere else in the plugin.
5. **Countable point** — `sensors = data_json.get('sensors', [])`
   (`client.py:147`), and per-sensor `sensor.get("data", [])` (`:155`) before
   `data.extend(...)` (`:157`). Inside the client.
6. **Exceptions** — none defined. `requests.HTTPError` from `raise_for_status()`
   at `client.py:30,61,91,144`. All calls bare, no `try/except`.
7. **`clean()`** — none.
8. **Tests** — none. Same nonexistent-`tests` lint target (`Makefile:2`).

### `adl-cimawebdrops-plugin`

Models `CimaWebDropsConnection` (`models.py:13`), `CimaWebDropsStationLink`
(`models.py:52`).

1. **Archetype** — HTTP/REST with **OAuth2 resource-owner password grant**.
   `import requests` (`client.py:4`); `_ensure_token()` POSTs
   `grant_type: "password"` with `client_id`, `username`, `password`
   (`client.py:36-46`), caches the token in memory (`:26-27,48-50`), and
   `_auth_headers()` (`:52-54`) sets `Authorization: Bearer`.
2. **Endpoint** — **fields present**: `token_endpoint` (`models.py:19`),
   `api_base_url` (`models.py:23`), plus `client_id` (`:20`), passed at
   `models.py:43-49`. Nothing hard-coded in `client.py` (`:17-22`). Two hosts, as
   with FieldClimate — auth and data may differ.
3. **Cheapest read-only call** — `get_sensor_classes()` (`client.py:56-72`,
   `GET {api_base_url}/sensors/classes/` at `:62`): forces a token exchange but
   returns only a taxonomy. Cheaper than `get_stations()` (`:181-206`), which
   fans out one `get_sensors_list_for_class()` call per class (`:74-92`).
   **All four of these cache for 24h** (`client.py:56-244`), `use_cache=True` by
   default (`:17`).
4. **Station identity** — `cima_station_id` (`models.py:56`), a synthetic
   coordinate-derived ID (`generate_station_id`, `client.py:8-13`; used as the
   dict key at `:200`). `get_station_parameters(station_id)` (`client.py:208-244`)
   **cannot fail**: an unknown station returns `[]` (`:219-222`). Needs an
   explicit not-found branch before it can carry the contract.
5. **Countable point** — `sensors_info` is complete at `plugins.py:45-55`, so
   `len(sensors_info)` is knowable at `plugins.py:56`, before
   `get_data_for_sensors(...)` at `:57`. **In the plugin, not the client.** But it
   counts *configured variable mappings*, parsed from `"sensor_class:sensor_id"`
   strings (`plugins.py:47-55`) — knowable without touching the network, so it
   does not describe what the source offered.
6. **Exceptions** — none defined. `requests.HTTPError` from `raise_for_status()`
   at `client.py:46,64,83,268`. One `ValueError` at `client.py:297`.
7. **`clean()`** — none (full read of `models.py:1-115`).
   `validate_start_date` (`validators.py:8-19`) on `models.py:57`.
8. **Tests** — none.

Also noted: `get_data_for_sensor()` indexes `data[0]["timeline"]`/`data[0]["values"]`
(`client.py:272-273`) with no empty-response guard — a plausible `IndexError`.

### `adl-earthnetworks-plugin`

Models `EarthNetworksConnection` (`models.py:12`), `EarthNetworksStationLink`
(`models.py:61`).

1. **Archetype** — HTTP/REST via a `requests.Session` with retry/backoff
   (`client.py:7-9`, session at `:57-72`, GET at `:102`). **No authentication of
   any kind** — no key, token or credential appears in `client.py` or `models.py`.
   `EarthNetworksClient()` is constructed with zero arguments
   (`models.py:26-30`), and `EarthNetworksConfig` (`client.py:31-39`) has no auth
   field.
2. **Endpoint** — **no field.** `EarthNetworksConnection` has no host/URL field at
   all (`models.py:12-30`). Hard-coded at `client.py:33`:
   `base_url: str = "https://owc.enterprise.earthnetworks.com/Data/GetData.ashx"`.
   Host `owc.enterprise.earthnetworks.com`, port 443. `provider_id: int = 3`
   (`client.py:34`) is likewise hard-coded and sent as `pi` on every request
   (`:85`), with no admin field.
3. **Cheapest read-only call** — **none exists.** There is no credential to prove
   and no station-independent endpoint: `build_url()` (`client.py:74-92`) always
   requires `si` (station id) plus a start/end window, and `fetch_raw()`
   (`:94-109`) is the only network operation the client offers. `check_source()`
   has nothing connection-scoped to probe.
4. **Station identity** — `en_station_id` (`models.py:65`). No existence call
   short of `get_data()` (`client.py:209-216`) → `fetch_raw()`, the same call
   ingestion uses — but `fetch_raw(station_id, start_utc, end_utc)`
   (`client.py:94`) takes an explicit window, and `normalize()` (`client.py:113`)
   reads `Result.Station` (`StationName`, `Inactive`, lat/lon/elevation) from a
   different branch of the response than `HistoricalObservations`. A minimal
   window therefore proves station identity and yields the upstream's own label
   for near-zero payload, without fetching data. Note `views.py` and
   `wagtail_hooks.py` are **empty files**, so
   the field is a bare `FieldPanel` (`models.py:73`) with no lookup widget — an
   operator must know the ID out of band.
5. **Countable point** — `hist = result.get("HistoricalObservations") or []`
   (`client.py:123`), before the loop at `:138-182`. Inside the client. The
   response is one flat list of timestamped bundles, not per-variable series.
6. **Exceptions** — none defined. `requests.HTTPError` from `raise_for_status()`
   (`client.py:103`); `RuntimeError` at `client.py:108` carrying the upstream code
   **interpolated into the message string**, not as an attribute — unrecoverable
   by type, which is the only thing `core/classification.py` matches on. `Retry`
   (`client.py:59-67`, `max_retries=3` at `:37`) means transient faults surface
   only after exhaustion, as `ConnectionError`/`MaxRetryError`.
7. **`clean()`** — none (full read of `models.py:1-96`).
8. **Tests** — none.

Also noted: `_unwrap()` (`client.py:186-205`) returns `None` for unexpected value
shapes rather than raising, so upstream data-quality faults degrade silently.

### `adl-fieldclimate-plugin`

Models `FieldClimateConnection` (`models.py:12`), `FieldClimateStationLink`
(`models.py:48`).

1. **Archetype** — HTTP/REST with **OAuth2 password grant — not HMAC.**
   `authenticate()` (`client.py:77-95`) POSTs `grant_type: "password"` with
   `username`/`password`/`client_id`/`client_secret`/`scope`; refresh at
   `:97-123`; bearer header via `_headers()` (`:137-142`) and `_ensure_token()`
   (`:131-135`). No `hmac`/`hashlib`/signing code exists in the repo.
2. **Endpoint** — **no field.** Only `client_id`, `client_secret`, `username`,
   `password` (`models.py:18-21`). **Two** hard-coded class constants:
   `OAUTH_URL = "https://oauth.fieldclimate.com/token"` (`client.py:28`) and
   `API_BASE_URL = "https://api.fieldclimate.com/v2"` (`client.py:29`). A single
   `(host, port)` return cannot cover both.
3. **Cheapest read-only call** — the client's `__init__` calls
   `self.authenticate()` unconditionally (`client.py:72`), so **constructing the
   client is already the credential check** — the same shape as
   `NetworkFTP.check_source()`. Beyond auth, `get_user_stations()`
   (`client.py:223-240`, `GET /user/stations` at `:227`). Nothing is wired to the
   admin: `views.py` and `wagtail_hooks.py` are both empty and there is no
   `widgets.py`.
4. **Station identity** — `fc_station_code` (`models.py:53`), used at
   `plugins.py:15`. `get_station_sensors(station_id)` (`client.py:242-259`,
   `GET /station/{id}/sensors` at `:247`) would prove existence without fetching
   observations; it is defined but invoked nowhere.
5. **Countable point** — `rows` in `_format_hourly_data()` (`client.py:322`, one
   entry per timestamp), or `date_strings` (`:312`). Inside the client;
   `plugins.py:8-20` returns the formatted list directly.
6. **Exceptions** — none defined. Bare `Exception` at `client.py:92`,
   `RuntimeError` at `:141` and `:218`, `requests.HTTPError` from
   `raise_for_status()` at `:188`, and `requests.RequestException` caught
   generically at `:200-208` and re-raised at `:215`.
7. **`clean()`** — none.
8. **Tests** — none. `config/settings/settings.py` is an empty stub. `client.py`
   imports no Django at module scope, so it is testable DB-free once scaffolding
   exists.

### `adl-iosnet-plugin`

**This repo does not parse and cannot receive a retrofit.**

1. **Archetype** — intended THREDDS catalog client via `siphon.catalog.TDSCatalog`
   (`client.py:1,12`). No auth of any kind.
2. **Endpoint** — no field. `IOSNETConnection` (`models.py:7-20`) has only
   `country` (`:10`), under a panel headed **`"TAHMO API Credentials"`**
   (`models.py:15`). Hard-coded at `client.py:5`:
   `base_url="https://galilee.univ-reunion.fr/thredds"`.
3. **Cheapest read-only call** — moot: **the module has a syntax error.**
   `client.py` is 16 lines and ends with `def get_countries_list(self):` and no
   body; `ast.parse()` raises
   `IndentationError: expected an indented block after function definition on line 16`.
4. **Station identity** — `iosnet_station_dir` (`models.py:24`), referenced
   nowhere else in the repo.
5. **Countable point** — none. `get_station_data()` unconditionally `return []`
   (`plugins.py:11-12`).
6. **Exceptions** — none.
7. **`clean()`** — none.
8. **Tests** — none.

Further evidence the scaffold was never completed:
`station_link_model_string_label = ""` (`models.py:8`); the plugin class is still
the cookiecutter's `PluginNamePlugin` (`plugins.py:4`); `IOSNETStationLink`
overrides neither `get_variable_mappings()` nor `get_first_collection_date()`;
there is no `VariableMapping` model of any pattern; `views.py` and
`wagtail_hooks.py` are empty. The repo directory contains **no `.git`**.

### `adl-pulsoweb-plugin`

Models `PulsoWebConnection` (`models.py:14`), `PulsoWebStationLink`
(`models.py:77`).

1. **Archetype** — HTTP/REST, single-endpoint POST style. All calls route through
   `post(path, payload)` (`client.py:122-133`), `url = f"{self.baseurl}/{path}/"`
   (`:131`), `requests.post(url, json=payload)` (`:132`). Paths: `get_context`
   (`:156`), `get_data` (`:164`), `get_logs` (`:186`).
2. **Endpoint** — **field present**: `api_base_url` (`models.py:16-17`, default
   `"https://app.pulsonic.com/rest"`), plus `api_token` (`:18`). One opaque URL,
   no host/port split.
3. **Cheapest read-only call** — `get_context()` (`client.py:149-161`, POST to
   `get_context` at `:156`), which `get_observations_metadata` /
   `get_granularities_metadata` / `get_stations_metadata` (`client.py:17-32`) all
   wrap. **Cached 1h** (`client.py:150-161`). The admin "View Metadata" link
   (`models.py:32-42` → `views.py:8-20`, URL `wagtail_hooks.py:14-15`) exercises
   it but renders UI rather than returning a verdict.
4. **Station identity** — `pulsoweb_station_code` (`models.py:78`). No per-station
   lookup; `get_stations_metadata()` (`client.py:29-32`) returns the whole list
   via `get_context()["stations"]` (`client.py:31`), requiring a client-side scan.
   That list is what `views.py:53` already renders, so a membership check is
   composable — subject to the 1h cache in item 3.
5. **Countable point** — the `records` dict in `get_observation_data()` is
   complete at `client.py:183`, just before `return list(records.values())`.
   Inside the client; `plugins.py:51-53` returns it directly.
6. **Exceptions** — `PulsoWebConnectionError` (`client.py:7-8`) is **defined and
   never raised**; repo-wide grep finds only the class statement. `post()`
   (`client.py:122-133`) calls **neither `raise_for_status()` nor any `timeout`**.
   HTTP 401/403/404/5xx are never detected; a bad token surfaces as a downstream
   `KeyError` or JSON decode error. Authentication is a token in the POST body
   (`client.py:126-129`), not a header.
7. **`clean()`** — none. `validate_start_date` (`validators.py:19`) on
   `models.py:79-82`.
8. **Tests** — none.

### `adl-siapmicros-polarisweb-plugin`

Models `PolarisWebConnection` (`models.py:15`), `PolarisWebStationLink`
(`models.py:94`). Variable-mapping Pattern B (connection-level, `models.py:56-91`).

1. **Archetype** — HTTP/REST. `import requests` (`client.py:4`);
   `self.base_url = f"{host}/api/polaris/"` (`client.py:17`). Endpoints
   `/stations` (`:43`), `/base_measures` (`:60`), `/data/series` (`:91`).
2. **Endpoint** — **field present**: `host = models.URLField(...)`
   (`models.py:22-25`), help text `e.g. http://102.218.136.213:88` — so the URL
   **carries an explicit non-default port and an IP literal**, and any
   `get_source_endpoint()` must honour `urlparse(...).port` rather than assume
   443/80. The `/api/polaris/` path segment is hard-coded (`client.py:17`).
3. **Cheapest read-only call** — `get_base_measures()` (`client.py:53-68`,
   `GET /api/polaris/base_measures?limit=-1` at `:60`) — a shallow GET with no
   station or time argument. Token is a query param (`client.py:22,30`).
   `get_stations()` (`:36`) is equally shallow. **Both cache 24h**
   (`client.py:49,66`). Existing AJAX surfaces: `views.py:24-38` and `:41-62`,
   URLs at `wagtail_hooks.py:14-23`, widgets at `widgets.py:5-24`.
4. **Station identity** — `polaris_station_id` (`models.py:98`). No lookup call,
   but `get_stations()` returns a dict keyed by id
   (`stations_by_id = {str(s['id']): s for s in stations}`, `client.py:46`), so a
   membership test is trivial — just not written.
5. **Countable point** — `measure_ids` (`plugins.py:30-33`), with an empty check
   at `:35-40`, before `get_measurements()` at `:42-47`. **In the plugin.** But
   like cimawebdrops it counts *configured mappings*, not source items.
6. **Exceptions** — none defined. `raise_for_status()` at `client.py:25,33` yields
   `requests.HTTPError` with `.response.status_code` — the readiest
   status-code-to-category mapping in the fleet, and unimplemented. Malformed
   values and timestamps are logged and dropped, not raised
   (`client.py:105-112,114-119`). `views.py:65-101` has a bare `except Exception`
   in the admin path that falls back to an empty choice list.
7. **`clean()`** — none on any of the three models. `validate_start_date`
   (`validators.py:8-13`) on `models.py:103`.
8. **Tests** — none. `PolarisWebAPIClient` needs only two strings plus the Django
   cache, so a mocked-`requests` suite is feasible without a database.

Also noted: `get_measurements` sends a JSON body on a **GET** request
(`client.py:91`).

### `adl-collector-app-plugin`

Models `ManualObservationConnection` (`models/connection.py:8`),
`ManualObservationStationLink` (`models/station_link.py:16`).

1. **Archetype** — **inbound push; no upstream exists.** Repo-wide grep finds no
   `requests`/`httpx` import or call; `requirements/base.in:1` lists only
   `pymetdecoder==0.1.6`. Data arrives through DRF views —
   `SubmitManualObservation.post()` (`views/api.py:40-91`),
   `DecodeSynopView`/`SubmitSynopView` (`views/office.py:35-92`), routed at
   `urls.py:13-19`. `get_station_data()` (`plugins.py:69-125`) queries ADL's own
   database (`plugins.py:82-96`).
2. **Endpoint** — **structurally none.** `ManualObservationConnection`
   (`models/connection.py:8-33`) holds only `enable_office_entry` (`:14-18`) and
   `enable_field_app` (`:19-23`). `station_link_model_string_label` (`:12`) is a
   registry pointer, not an address.
3. **Cheapest read-only call** — **structurally none.** Authentication runs the
   other way: `permissions.IsAuthenticated` on `views/api.py:40-41` and
   `views/office.py:41,77`, using core Django/DRF machinery. No credential to any
   external system exists.
4. **Station identity** — no plugin-specific upstream field; the link inherits
   `station` from core (`core/models.py:701-704`) and adds only `start_date`
   (`station_link.py:21-29`) and `schedule` (`:31-41`). Existence checks are local
   ORM lookups (`views/api.py:30-37`, `views/office.py:268-270`). The meaningful
   station-scope question here is "are there pending unprocessed submissions",
   answerable from the queryset at `plugins.py:82-96`.
5. **Countable point** — **already computed and logged**:
   `records = list(grouped.values())` then `logger.debug(..., len(records))`
   (`plugins.py:119-123`). A one-line assignment away from the handover, and the
   cheapest win in the fleet.
6. **Exceptions** — structurally moot: no outbound socket, so no DNS/TCP/TLS layer
   can fail. Only Django/DRF built-ins appear —
   `ValidationError` (`models/submission.py:96-104`,
   `serializers/submission.py:36,43,48,58-59`), `DoesNotExist` caught defensively
   (`views/api.py:34`, `serializers/synop.py:43-44,118-119`), and
   `(ValueError, ImportError)` around `decode_fm12()` (`views/office.py:252`,
   `serializers/synop.py:48-49,106-107`).
   The `adl_category` grep hits in `synop_wizard_data.py` and
   `views/synop_wizard.py:252` are an unrelated `DataParameter.category` domain
   field — a **name collision** with the diagnostic contract's duck-typed
   attribute, not an implementation of it.
7. **`clean()`** — one override, on `CollectorSubmission`
   (`models/submission.py:96-104`): asserts an observer or office submitter is
   set, that `observation_time` and `submission_time` are timezone-aware, and that
   `observation_time` is not in the future. Pure, no I/O. **Not a config model** —
   neither `ManualObservationConnection` nor `ManualObservationStationLink`
   overrides `clean()`, so config-drift detection sees nothing here.
8. **Tests** — `tests/test_synop_utils.py` (108 lines) plus an empty
   `tests/__init__.py`. Module-level `def test_*()` functions over pure helpers
   (`extract_value_by_path`, `:10-80`; `FM12_ELEMENT_PATH_CHOICES` integrity,
   `:87-107`). No `TestCase`, no `django_db` marker, no fixtures — DB-free. No
   `conftest.py`, `pytest.ini` or `[tool.pytest.ini_options]`; `pyproject.toml`
   carries only `[tool.black]`, and `pytest` is not in `requirements/dev.in`.

### `FTPUpload` and `SmartMetFTPUpload` (`adl-ftp-plugin`)

Both defined in `models.py`: `FTPUpload` (`:1025`) and `SmartMetFTPUpload`
(`:1057`), each mixing the abstract `BaseFTPUpload` (`:917`) with
`DispatchChannel` — the `BaseXUpload` pattern.

1. **Archetype** — pushes CSVs over FTP/FTPS (stdlib `ftplib`, via the plugin's
   `FTPClient`, `ftp/__init__.py:57`) or SFTP (`paramiko`, `SFTPClient`,
   `ftp/sftp.py:38`), chosen by `connection_type`.
2. **Destination fields** — on `BaseFTPUpload`: `host` (`:930`), `port` (`:931`),
   `user` (`:933`), `password` (`:934`), `directory` (`:951`), plus SFTP-only
   `private_key_file` (`:941`) and `host_key_policy` (`:942`).
3. **Cheapest read-only proof** — `BaseFTPUpload.get_client()` (`models.py:1017`)
   returns `FTPClient(**self.connection_details)` or
   `SFTPClient(**self.connection_details)` (`connection_details` at `:990`), and
   **both clients authenticate in `__init__`** — `ftp.login(...)`
   (`ftp/__init__.py:83`) or `FTP_TLS` (`:73`); `ssh.connect()` then `open_sftp()`
   (`ftp/sftp.py:94-107`). So build-and-close proves the credential without
   listing or writing — exactly `NetworkFTP.check_source()`
   (`models.py:491-511`), already in the same file.
4. **Send path** — both `send_station_data()` (`:1053`, `:1117`) call
   `dispatch_to_ftp()` (`dispatchers/ftp.py:357`), which builds the client
   (`:373`), uploads via `client.put()`, and closes in a `finally` (`:412`).
   `SmartMetFTPUpload.upload_stations_metadata()` (`models.py:1125-1149`)
   **writes** (`client.put()` at `:1148`) and fires on every save via a
   `post_save` signal (`:1155-1177`) — not usable as a read-only probe.
5. **Exceptions** — `FTPError` (`ftp/__init__.py:24`) and `SFTPError`
   (`ftp/sftp.py:26`) both carry `.message` and a numeric `.status`, set by
   `map_ftp_error()` (`ftp/__init__.py:214`) and `map_sftp_error()`
   (`ftp/sftp.py:418`). The mapping to the shared vocabulary already exists at
   `models.py:44-49` (401→`AUTH_FAILED`, 403→`PERMISSION_DENIED`,
   404→`PATH_NOT_FOUND`, 504→`TCP_TIMEOUT`; 502 and 503 deliberately unmapped)
   and is reusable verbatim.
6. **`clean()`** — `BaseFTPUpload.clean()` (`models.py:962`) checks password /
   private-key presence; no I/O. Siblings: `StandardCSVConfig.clean()` (`:275`),
   `NetworkFTP.clean()` (`:384`), `FTPStationLink.clean()` (`:749`) — all pure.
7. **Tests** — `tests/test_source_checks.py`, the DB-free reference suite. No
   runner config; the `Makefile` has only `lint`, `lint-python`, `format`.
8. **Existing equivalent** — none for dispatch. `check_source()` (`:491`) and
   `check_station_source()` (`:826`) are the ingestion-side analogues on
   `NetworkFTP`/`FTPStationLink`, not on the upload channels.

### `adl-smartmet-dispatch-plugin`

**Empty cookiecutter scaffold.** `models.py`, `views.py`, `wagtail_hooks.py`,
`__init__.py` and `config/settings/__init__.py` are all **0 bytes**;
`plugins.py` is 12 lines and still declares `PluginNamePlugin` with
`get_station_data()` returning `[]`; `apps.py` (13 lines) registers that same
unrenamed class.

There is **no `DispatchChannel` subclass**, no client, no destination fields, no
exceptions, no `clean()`, and no `tests/`. A grep for
`test_connection|check_|ping|probe|validate` across `src/` returns zero matches.

It also shares **no code** with `adl-ftp-plugin`'s `SmartMetFTPUpload`, which uses
that repo's internal `smartmet_utils.get_station_metadata_csv()`
(`adl-ftp-plugin:smartmet_utils.py:6`). Only the name "SmartMet" is common, so a
single implementation cannot serve both.

`test_connection()` cannot be added here — there is nothing to add it to.

---

## Method and limitations

**Method.** Source reading only, against the working copies in
`adl-project/adl-plugins/` as of this commit. For each target: `models.py`,
`plugins.py`, and every client/validator/widget/view module in the package were
read, plus repo-wide greps for `def clean`, `get_source_endpoint`,
`check_source`, `check_station_source`, `adl_sources_count`, `test_connection`,
`adl_category`, `adl_layer`, `raise_for_status`, and each plugin's own exception
names. Two claims that would change a design decision were re-verified directly
rather than taken on report: `adl-iosnet-plugin`'s syntax error was confirmed by
running `ast.parse()` over `client.py`, and `adl-smartmet-dispatch-plugin`'s empty
`models.py` by `wc -l` over every file under `src/`.

**Nothing was executed or dialled.** No plugin was run, no external service
contacted, and no plugin repo modified. Statements about what a call *would*
prove are inferences from the code path, not observations of a live response.

**Limitations.**

- **No upstream API documentation was consulted.** Where this note says a call is
  "cheap", that means cheap in the code — few round trips, small response, no
  observation payload. The vendor's own rate limits, quotas or auth semantics may
  disagree, and for a probe fired by operators across 26 deployments that matters.
  Each design ticket should confirm its chosen call against the vendor's docs.
- **Line numbers drift.** These are independently versioned repos on their own
  release schedules; citations are true of the working copies read here.
- **Cache behaviour is read from code, not measured.** The 24h/1h TTLs quoted
  are the values passed to `cache.set`; whether a given deployment's cache backend
  honours them was not tested.
- **`adl-project/.claude/CLAUDE.md`'s archetype table has at least one error**
  (`adl-microstep-db-plugin` is Pattern C, not Pattern A). Other entries in that
  table were not systematically audited against source, so it should not be
  treated as authoritative for the remaining plugins.
