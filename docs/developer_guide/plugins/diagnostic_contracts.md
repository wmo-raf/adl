# Ingestion Diagnostic Contracts

When a connection goes silent, ADL's ingestion diagnostic names the **first
failing layer** of six rather than reporting "no data". Four of those layers
are core's own business. Two — **layer 4, the network path** and **layer 5, the
source** — and part of layer 6 can only be answered by the plugin, because only
the plugin knows what host it dials, what a valid credential looks like there,
and what the source offered.

This page is the spec for the plugin side of that diagnostic: seven contract
surfaces, what each one means for each source archetype, and the rules a
retrofit is measured against.

```{note}
Every surface here is **optional in the mechanical sense** — core detects
support by checking whether your subclass overrides the method, and a plugin
that overrides nothing keeps ingesting exactly as before while the diagnostic
reports `UNSUPPORTED`. Optional does not mean free: an `UNSUPPORTED` layer is a
layer the operator has to debug by hand.
```

Each section names the decision that fixed it, so the rules can be re-derived
when core moves. The decisions live on
[map #221](https://github.com/wmo-raf/adl/issues/221); the diagnostic itself is
specified in [#171](https://github.com/wmo-raf/adl/issues/171).

---

(dc-archetype)=

## 0. Which archetype am I?

Answer this **before** reading anything below, because it decides whether four
of the seven surfaces apply to you at all.

> **Does ADL dial out to fetch this data?**

**No** — observations arrive at ADL by someone else's action and "ingestion" is
a local sweep of what landed. A webhook receiver, an inbound API endpoint, a
mobile collector app writing into ADL's own database, a file-drop-into-ADL
plugin. This is the **internal / push-fed** archetype. Jump to
{ref}`§0.1 <dc-push-fed>` — you are done in one line and the rest of the
external half does not apply to you.

**Yes** — you have a host, and one of three shapes:

| Archetype | You fetch by | Typical client |
|---|---|---|
| **HTTP/REST** | calling a vendor web API | `requests` |
| **Direct database** | querying the vendor's database directly | `psycopg2`, `pyodbc`, … |
| **File-based** | listing and reading files off a server | FTP / FTPS / SFTP |

```{important}
The gate is **push versus pull**, not storage. "Reads a database" does not make
you the direct-database archetype — a plugin that reads *ADL's own* database
because submissions were pushed into it is push-fed. The question is whether
ADL dials out.
```

(dc-push-fed)=

### 0.1 The internal / push-fed archetype in one line

Decided by [#233](https://github.com/wmo-raf/adl/issues/233).

```python
class MyConnection(NetworkConnection):
    # No host to dial, no credential we hold, nothing to be addressable.
    has_external_source = False
```

That declaration is the whole external half of your retrofit. Layers 4 and 5
are reported as **not applicable** — a distinct state from `UNSUPPORTED`, which
means *not implemented yet*. Here there is nothing to implement, now or ever.

**Do not implement the four external surfaces "for completeness".** They have
no subject:

- `get_source_endpoint()` — no host to name.
- `check_source()` — no credential to present.
- `check_station_source()` — the "station" is an ADL row that always exists, so
  `PATH_NOT_FOUND` has no referent.
- `adl_sources_count` — its only two readers sit inside layer 5, so a number
  written here is never read. And the thing it would report ("nobody
  submitted") is already exactly what **layer 6** reports for this archetype,
  where data staleness *is* observer silence. The count exists to split "the
  source offered nothing" from "we mishandled what it offered"; with no source
  there is no such split.

Exception stamping ({ref}`§7 <dc-stamping>`) declines for the same reason: its
whole basis is a code the *server* sent, and there is no server. Ingestion
failures here are Django ORM errors — internal faults, not source faults.

Layers 1–3 and 6 apply to you unchanged, and layer 6 is the *interesting* one:
a stale push-fed connection means its observers have gone quiet, which is the
fault an operator actually wants named.

```{note}
`has_external_source` is read by core as of
[#235](https://github.com/wmo-raf/adl/issues/235). Setting it on an older core
is inert but harmless — an unread class attribute —
so the declaration is correct to write in advance.

Alongside the two layer verdicts, the declaration also withdraws the on-demand
**Probe source** button on the connection's diagnostic page and the
**Check source** button on each of its station links: there is no host to dial,
so nothing offers to.
```

---

(dc-matrix)=

## 1. The matrix

Find your archetype's column and read down. Each cell links to the rule.

**Verdicts:** *implement* — write it; *decline* — leave core's default in
place, deliberately; *audit* — review what you already have, add nothing new;
*N/A* — the surface has no subject for this archetype.

| Surface | HTTP/REST | Direct database | File-based | Internal / push-fed |
|---|---|---|---|---|
| {ref}`get_source_endpoint() <dc-endpoint>` | implement — data host & port | implement — `db_host`, `db_port` | implement — host & effective port | **N/A** — {ref}`§0.1 <dc-push-fed>` |
| {ref}`check_source() <dc-check-source>` | implement — {ref}`cheapest read-only data call <dc-check-source-http>` | implement — {ref}`connect, read-only, one round trip <dc-check-source-db>` | implement — {ref}`connect and authenticate <dc-check-source-file>` | **N/A** |
| {ref}`check_station_source() <dc-station-source>` | implement — {ref}`membership test or station resource <dc-station-source-http>` | implement — {ref}`two queries <dc-station-source-db>` | implement — {ref}`resolve path and list <dc-station-source-file>` | **N/A** |
| {ref}`adl_sources_count <dc-sources-count>` | implement — parsed entries for the window | implement — `len(rows)` | implement — matching files | **N/A** |
| {ref}`Exception stamping <dc-stamping>` | implement — {ref}`HTTP status <dc-stamping-http>` | implement — {ref}`SQLSTATE <dc-stamping-db>` | implement — {ref}`reply code <dc-stamping-file>` | decline |
| {ref}`clean() <dc-clean>` | audit | audit | audit | audit |
| {ref}`test_connection() <dc-test-connection>` | dispatch channels only | dispatch channels only | dispatch channels only | dispatch channels only |

```{note}
`test_connection()` is a **dispatch-channel** surface. It lives on
`DispatchChannel` subclasses and is orthogonal to the ingestion archetype above
— a repo that only ingests has nothing to do there, and a repo that only
dispatches does nothing else on this page.
```

(dc-ftp-warning)=

```{warning}
**`adl-ftp-plugin` is the only shipped implementation of these contracts, and
it is wrong on two of the seven surfaces. Do not copy it.** All three defects
are open at the time of writing:

- [adl-ftp-plugin#4](https://github.com/wmo-raf/adl-ftp-plugin/issues/4) —
  `adl_sources_count` is set to `0` *before* the directory listing succeeds, so
  a failed `LIST` logs a source-empty run and layer 5 blames the partner's
  server for our own network failure. Violates {ref}`§6.2 <dc-count-zero>`.
- [adl-ftp-plugin#5](https://github.com/wmo-raf/adl-ftp-plugin/issues/5) —
  `map_ftp_error()` collapses DNS failures, connection refusals and TLS errors
  into a single status `502`, destroying classification core would have made
  for free. Violates {ref}`§7.1 <dc-stamping-wrapper>`.
- [adl-ftp-plugin#6](https://github.com/wmo-raf/adl-ftp-plugin/issues/6) — FTPS
  dials port 21 regardless of the configured port, so `get_source_endpoint()`
  and the client disagree and the diagnostic contradicts itself.

Read it for the *shape* of a retrofit if you like; take the rules from this
page.
```

---

(dc-version-skew)=

## 2. Version skew: no new module-level `adl.core` import

Decided by [#223](https://github.com/wmo-raf/adl/issues/223).

Plugins ship on their own release schedule and the 26 ADL deployments run
pinned images. A plugin that imports a core module which does not exist on the
deployed core **fails at import time** — the whole plugin dies, not just the
diagnostic.

> **The rule: a retrofit introduces no *new* module-level import from
> `adl.core`.**

Your existing `from adl.core.models import NetworkConnection` at the top of
`models.py` is fine and must stay — it is a base class, and a core old enough
to lack it is a core your plugin never ran on. What must not move to module
level is anything the *contracts* need.

The tax is smaller than it looks. Only two of the seven surfaces need a core
symbol at all:

| Surface | Returns | Core import needed |
|---|---|---|
| `get_source_endpoint()` | `(host, port)` tuple | none |
| `check_source()` | `SourceCheckResult` | **`adl.core.source_checks`** |
| `check_station_source()` | `SourceCheckResult` | **`adl.core.source_checks`** |
| `adl_sources_count` | `int` | none |
| `adl_category` / `adl_layer` | `str` / `int` | none |
| `clean()` | — | none |
| `test_connection()` | plain `dict` | none |

So the pattern is two function-local import lines, in two methods:

```python
def check_source(self):
    # Lazy: this module does not exist on a core release predating the
    # source-check contracts, and on such a core this method is never called.
    from adl.core.source_checks import SourceCheckResult, SourceCheckStatus
    ...
```

On an older core, `NetworkConnection` has no `check_source` for core to call,
nothing invokes your override, and the import never executes. Your plugin
ingests normally; the diagnostic reports `UNSUPPORTED`. That is the designed
degradation.

```{important}
**No `try/except ImportError`. Ever.** The handler is unreachable by
construction, and it has a live cost: it converts a *genuine* import failure — a
typo in the module path, a half-installed core, a circular import introduced
later — into a silent "this plugin doesn't support the check". That is exactly
the class of bug the diagnostic exists to stop the fleet from hiding. A loud
`ImportError` naming the missing module is something an operator can act on;
`UNSUPPORTED` is not.
```

```{important}
**Never import `FAILURE_CATEGORIES` — use the literal strings.** The one
tempting reason to reach into `adl.core.classification` is to avoid a typo in a
category name. Don't. Core validates every value against its closed vocabulary
and drops what it does not recognise, so a typo degrades to unclassified and
falls through to the read-time tier — the designed fallback, and strictly
better than coupling to the module this rule exists to avoid. The vocabulary is
reproduced in {ref}`§7.4 <dc-vocabulary>` so you never need to open core's
source.
```

The rule binds **shipped modules only**. Your `tests/` package may import
`adl.core.source_checks` at module level: tests run in dev against current
core and never ship into a deployment.

### The AST guard

The rule is enforced mechanically by a small test that parses your source
rather than running it. It is generated into new plugins by the cookiecutter,
and copied per repo into existing ones —
`adl/plugin-boilerplate/` holds the canonical copy.

```python
class OlderCoreImportSafetyTests(SimpleTestCase):
    """The plugin must import cleanly on a core release that predates the
    source-check contracts, so nothing may import ``adl.core.source_checks``
    at module level."""

    MODULES = ["models.py", "plugins.py"]

    def test_no_module_level_import_of_source_checks(self):
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in self.MODULES:
            path = os.path.join(package_dir, name)
            if not os.path.exists(path):
                continue
            with open(path) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                if node.col_offset != 0:
                    continue  # indented imports are lazy, inside a function
                names = [a.name for a in node.names]
                module = getattr(node, "module", "") or ""
                self.assertNotIn(
                    "adl.core.source_checks", [module] + names,
                    f"{name} imports adl.core.source_checks at module level")
```

Set `MODULES` to **your own** shipped module list. The denylist is the
*implementation* of the rule, not the rule — when core grows a module a future
contract needs, the rule still reads correctly and the guard gets one more
string.

---

(dc-endpoint)=

## 3. `get_source_endpoint()`

Lives on your `NetworkConnection` subclass. Returns `(host, port)`, or `None`.

Core owns the generic **DNS → TCP** probe built on this — layer 4 of the
diagnostic. A plugin only ever *names* its endpoint; it never implements
network probing itself.

Decided per archetype: [#225](https://github.com/wmo-raf/adl/issues/225)
(HTTP/REST), [#224](https://github.com/wmo-raf/adl/issues/224) (direct
database), [#233](https://github.com/wmo-raf/adl/issues/233) (push-fed).

```{eval-rst}
.. automethod:: adl.core.models.NetworkConnection.get_source_endpoint
   :noindex:
```

### The shared rule

> **Name the host the *data* call dials.** Host and port come from whichever
> URL or field the ingestion path actually uses — the explicit port when one is
> configured, otherwise 443/80 from the scheme.

**A hard-coded host is not a guess.** If the host is written as a Python
constant, that constant is the literal string your client dials, so probing it
is exactly as truthful as probing a model field. Name it.

**Naming a *wrong* host is much worse than naming none.** Core's health
evaluator reads activity-log evidence regardless of whether the endpoint is
supported, so returning `None` forfeits only the on-demand DNS/TCP probe and
rests non-blocking. A wrong host produces `blocking=True` failure evidence that
short-circuits layers 5 and 6 and sends the operator hunting a network fault
that does not exist. That asymmetry is what makes "name it" safe rather than
merely convenient.

```{important}
There is one second-order consequence that the later rules depend on. With an
endpoint named, core runs **DNS → TCP → `check_source()` in order and stops on
the first failure**. So `check_source()` only ever executes once the data host
is already connectable, and a codeless failure inside it is genuinely
post-connect.
```

(dc-endpoint-http)=

### HTTP/REST

Decided by [#225](https://github.com/wmo-raf/adl/issues/225).

```python
def get_source_endpoint(self):
    """The (host, port) core's DNS -> TCP probe dials (layer 4)."""
    from urllib.parse import urlparse
    parsed = urlparse(self.api_base_url)
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
```

**Where two hosts exist — an identity provider and a data API — name the data
host.** Layer 4 is the path to *the source*, and the source is where
observations come from. The accepted cost is that an IdP outage surfaces at
layer 5 rather than layer 4; {ref}`§4.5 <dc-check-source-messages>` mitigates it
by requiring the message to name the host it failed to reach, so the operator is
never misled about which box is down.

(dc-endpoint-db)=

### Direct database

Decided by [#224](https://github.com/wmo-raf/adl/issues/224).

The configured host and port, returned unchanged:

```python
def get_source_endpoint(self):
    return self.db_host, self.db_port
```

If your connection is configured by DSN or Unix socket instead, parse host and
port out where you can and return `None` where you cannot — core skips DNS and
TCP cleanly on `None` rather than guessing.

```{warning}
libpq accepts a **comma-separated multi-host string** in `host=`, and the model
field does not validate against it. An operator who types two hosts gets a false
`DNS_FAILURE` from core's resolver step. Worth knowing when you read a
surprising layer-4 verdict; not worth building for.
```

(dc-endpoint-file)=

### File-based

The configured host and the effective port (the explicit port when set,
otherwise the protocol default):

```python
def get_source_endpoint(self):
    return self.host, self.effective_port
```

```{warning}
Make sure the port you *report* is the port your client actually **dials**. A
client that ignores a non-default port — ftplib's `FTP_TLS` does this unless
carefully constructed — makes the diagnostic contradict itself: layer 4 passes
against the configured port while `check_source()` fails against the default,
and the operator is told the partner refused credentials it never received.
See the {ref}`warning above <dc-ftp-warning>`.
```

---

(dc-check-source)=

## 4. `check_source()`

Lives on your `NetworkConnection` subclass. Returns a `SourceCheckResult`.
Connection-scoped, strictly **read-only**, run **on demand only** — never on a
schedule.

Decided per archetype: [#225](https://github.com/wmo-raf/adl/issues/225)
(HTTP/REST), [#224](https://github.com/wmo-raf/adl/issues/224) (direct
database), [#233](https://github.com/wmo-raf/adl/issues/233) (push-fed).

```{eval-rst}
.. automethod:: adl.core.models.NetworkConnection.check_source
   :noindex:
```

### 4.1 What core does with your return

You supply only `status`, `category` and `message`. Core:

- stamps the result **layer 5** unconditionally;
- drops any `category` outside its closed vocabulary;
- redacts the message centrally through `redact_secrets`;
- degrades a non-`SourceCheckResult` return to `MALFORMED`;
- bounds the whole probe — DNS, TCP and your check together — by a shared
  15-second wall clock, and **abandons** (does not kill) a worker that
  overruns it.

That last point has teeth. See {ref}`§4.4 <dc-check-source-bounded>`.

### 4.2 The shared rule

> **Make the cheapest read-only call that proves the source *accepts our
> credentials* **and** *offers data*, with any cache bypassed. Claim `OK` only
> from a parsed response of the expected shape.**

Three parts, each load-bearing.

**Cheapest read-only call on the data host.** Where authentication is a
discrete token exchange, a token call would be cheaper — and it proves only
half the contract. A valid token against a dead data API reads `OK` at layer 5
and `OK` at layer 4, leaving a real outage to surface as stale data at layer 6,
two layers away from its cause. So the call goes to the data host, and where
auth is a token exchange it happens as a side effect of that same call. **Never
an observation-data call.**

(dc-cache-bypass)=

**Cache bypass is not optional.** Most metadata calls in the fleet — station
lists, sensor lists, sensor classes — are served from `django.core.cache` with
TTLs of 1 to 24 hours. Those are exactly the calls this check wants to make, so
the obvious implementation ships looking correct and reports `OK` while the
source is down: the precise failure the diagnostic exists to prevent.

**`OK` requires a parsed body carrying the key the call exists to return** —
never a bare 2xx. `requests` follows redirects by default, so an expired
session that 302s to an HTML login form arrives as a 200 that passes
`raise_for_status()`. The same shape check catches the 200-with-error-body
case. `allow_redirects=False` is *not* the fix: a 3xx declines a category so
the operator learns nothing, and it breaks against vendors whose legitimate API
redirects.

### 4.3 Categories are only ever claimed from something the server said

This holds across all three external archetypes and it is the single most
important classification rule on this page.

- A code the server sent → a category from the table for that protocol.
- No code — a TLS error, a connection error, a read timeout, a JSON decode
  failure, a failed shape check → `FAILED` with **`category=None`** and an
  explanatory message.

```{important}
**Never return `DNS_FAILURE`, `TCP_REFUSED` or `TLS_FAILURE` from
`check_source()`.** Core stamps every result layer 5 by construction, and those
are layer-4 statements — returning one puts a layer-4 category in a layer-5 slot
and has the diagnostic contradict itself about which layer failed.

`TCP_TIMEOUT` is the one apparent exception, and it is legitimate: the same
category is layer 4 as a connect timeout and layer 5 as a *post-connect*
handshake or read stall, which is what you would be reporting here.
```

(dc-check-source-bounded)=

### 4.4 Bound your call — this is a precondition, not a nicety

Core's probe budget is 15 seconds for DNS, TCP and your check together, and an
overrunning worker is abandoned rather than killed. Almost every client in the
fleet as written would blow it: several pass **no timeout at all**, and others
carry 30–60 second timeouts with three exponential-backoff retries.

Written the obvious way, your check returns *"did not complete within the
probe's 15-second budget"* — a non-verdict where a real one was available — and
leaks a live thread on every press.

> **Bound the check through an optional argument on the existing client
> factory, defaulting to today's behaviour.**

```python
def get_api_client(self, use_cache=True, timeout=None, retries=None):
    ...
```

Defaults preserve ingestion behaviour **exactly**, so nothing changes for the
26 deployments; the check passes `use_cache=False, timeout=5, retries=0`. Three
sequential 5-second bounds still fit inside 15.

```{note}
**Not a model field.** An operator who raises a configurable timeout to 300 for
a slow partner silently re-breaks the probe.
```

**Whoever times out first owns the message.** At 5 seconds your timeout fires
inside the remaining budget and the operator gets a specific sentence with a
category attached. If core's wall clock fires first they get the generic budget
message with **no category at all**. The specific message is worth engineering
for.

```{warning}
**Bounding the *check* does not bound *ingestion*.** Several plugins pass no
timeout anywhere on the ingestion path, which wedges a worker on a hung source
and makes `requests.ReadTimeout` — the fleet's only free layer-5 signal —
unreachable. That is shipped behaviour wrong on its own terms, so it is filed
as its own issue per repo rather than folded into the retrofit. Fix it; just
don't let it hide inside a diagnostic PR.
```

(dc-check-source-messages)=

### 4.5 Messages name the host and path, never a query string

Core redacts every plugin message centrally, and its redactor covers every
credential in the current fleet by name. This rule is defence in depth for the
two surfaces core cannot reach: **your own `logger` calls**, which core's
redaction never sees, and a future vendor whose credential parameter the suffix
list does not recognise.

So: name the host and path you dialled, never the query string, and log no URL
of your own. It costs nothing and makes the messages more readable.

(dc-check-source-http)=

### 4.6 HTTP/REST

Decided by [#225](https://github.com/wmo-raf/adl/issues/225).

The status table is {ref}`§7.3's <dc-status-table>`, verbatim — one table for
both the probe path and the ingestion path.

```python
def check_source(self):
    """Ask whether the source accepts our credentials and offers data
    (layer 5 of the ingestion diagnostic)."""
    from adl.core.source_checks import SourceCheckResult, SourceCheckStatus

    try:
        client = self.get_api_client(use_cache=False, timeout=5, retries=0)
        stations = client.get_stations()
    except requests.HTTPError as e:
        return SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category=SOURCE_CHECK_ERROR_CATEGORIES.get(e.response.status_code),
            message=_("%(host)s returned HTTP %(code)s for %(path)s.") % {
                "host": self.source_host, "code": e.response.status_code,
                "path": "/services/assets/v2/stations",
            },
        )
    except requests.RequestException as e:
        # No code from the server: decline the category (§4.3).
        return SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            message=_("%(host)s could not be reached: %(error)s") % {
                "host": self.source_host, "error": e,
            },
        )

    # §4.2: OK is claimed from a parsed body of the expected shape, never a
    # bare 2xx — a session that 302s to a login page arrives as a clean 200.
    if not isinstance(stations, dict) or "data" not in stations:
        return SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            message=_("%(host)s answered but the response was not a station "
                      "list.") % {"host": self.source_host},
        )

    return SourceCheckResult(
        status=SourceCheckStatus.OK,
        message=_("%(host)s accepted our credentials and returned "
                  "%(count)s station(s).") % {
            "host": self.source_host, "count": len(stations["data"]),
        },
    )
```

**Client construction goes inside the guarded region.** Several clients
authenticate eagerly in `__init__`, so a credential fault must surface as a
check failure rather than as an unhandled exception.

```{note}
**`UNSUPPORTED` is a legitimate answer at connection scope, and one plugin in
the fleet gives it.** Where a vendor has no credential and no
station-independent call — every endpoint requires a station id and a time
window — any connection-scope check would be a fiction. Borrowing the first
enabled station link would report a station-specific fault as a whole-connection
failure; an unauthenticated liveness GET proves only what core's TCP step
already proved while looking like a real source check. Such a plugin still
{ref}`names its endpoint <dc-endpoint-http>` and still implements
{ref}`§5's station-scope check <dc-station-source>`, so it is well covered — just
not here. Say so in the docstring, so `UNSUPPORTED` reads as a decision rather
than an omission.
```

(dc-check-source-db)=

### 4.7 Direct database

Decided by [#224](https://github.com/wmo-raf/adl/issues/224).

Three driver-neutral rules:

1. **Endpoint** is the configured host and port ({ref}`§3 <dc-endpoint-db>`).
2. **The check** connects under an explicit connect timeout, makes the session
   read-only **server-side**, issues one trivial round trip, and closes.
   Read-only must be *server-enforced*; where a driver or server cannot offer
   that, say so in the per-repo issue rather than substituting discipline.
3. **Classification** happens only on a code the server sent, from a table the
   plugin owns. Every other failure — including every client-side one —
   declines.

Connect alone would nearly do: libpq completes the full startup handshake,
credential *and* database selection, inside `PQconnectdb`, so there is no
lazy-auth problem on this driver. One round trip is still worth it — it catches
a server in recovery, a connection limit hit at first statement, and a pooler
such as pgbouncer that accepts the startup packet and fails on first query.

````{admonition} Worked instance — PostgreSQL / psycopg2
:class: tip

The rules above transfer to any driver. **This table does not** — `28000` and
`3D000` are standard SQLSTATE and carry to pyodbc, `28P01` is Postgres-only, and
MySQL does not expose SQLSTATE the same way and needs its own errno table.

```python
def check_source(self):
    from adl.core.source_checks import SourceCheckResult, SourceCheckStatus
    try:
        conn = self.get_client(connect_timeout=5)
        conn.set_session(readonly=True)          # server-enforced, not a promise
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        conn.close()
    except psycopg2.OperationalError as e:
        return SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category=SQLSTATE_CATEGORIES.get(e.pgcode),   # None when declined
            message=str(e),
        )
    return SourceCheckResult(
        status=SourceCheckStatus.OK,
        message=_("Connected to %(db)s on %(host)s:%(port)s as %(user)s.") % {...},
    )
```

| SQLSTATE | Meaning | Category |
|---|---|---|
| `28P01` | `invalid_password` | `AUTH_FAILED` |
| `28000` | `invalid_authorization_specification` (incl. `pg_hba` rejection) | `AUTH_FAILED` |
| `3D000` | `invalid_catalog_name` — the named database does not exist | `PATH_NOT_FOUND` |
| anything else, or `pgcode is None` | — | **decline** (`category=None`) |

`3D000` → `PATH_NOT_FOUND` is a judgement call: the vocabulary is
FTP-flavoured, but the semantics line up exactly — the operator named a thing on
the server, the server says it is not there, and the fix is one config field.

`53300 too_many_connections` and `57P03 cannot_connect_now` stay **declined**
even though they are unambiguous: no category fits, and `UNKNOWN` would claim a
classification we did not make. The raw message is already legible.

`pgcode is None` means the failure was client-side — libpq never received an
ErrorResponse. Those are DNS, refused and connect timeout, which core's own
steps already named and which cannot reach this method anyway. Declining there
is not a gap; it is refusing to re-report a layer-4 fault at layer 5.
````

```{important}
**Catch `psycopg2.OperationalError` only.** Everything else propagates to core.
A `TypeError` from a malformed field or an `InterfaceError` from misusing a
closed connection is *our* bug, not the source's — core's container names the
type and logs a full traceback, and a plugin-side `except Exception` would
flatten that into a friendly sentence and lose the traceback. That is the
diagnostic hiding a bug in the diagnostic.
```

**Accepted gap:** `SELECT 1` cannot distinguish "server healthy" from "server
healthy but our grants on the data tables are gone". That question is
{ref}`§5.4's <dc-station-source-db>`, and it is answered there.

(dc-check-source-file)=

### 4.8 File-based

**Connect and authenticate, read-only. Nothing is listed, fetched or written.**

Both FTP and SFTP clients authenticate during construction, so the body is
`get_client(); close()`. Path and directory questions belong to
{ref}`§5 <dc-station-source>`, which is where the operator's per-station
configuration actually lives.

Categories come from the FTP reply code ({ref}`§7.3 <dc-status-table>`); a
client-observed timeout carries no server code and **declines**.

---

(dc-station-source)=

## 5. `check_station_source()`

Lives on your `StationLink` subclass. Returns a `SourceCheckResult`. Layer 5,
station-scoped, read-only, on demand, one station at a time.

Decided by [#226](https://github.com/wmo-raf/adl/issues/226).

```{eval-rst}
.. automethod:: adl.core.models.StationLink.check_station_source
   :noindex:
```

> **The subject of this check is *external addressability*: does the identifier
> the operator typed resolve to a real, reachable station at the source?**

Every rule below follows from that one sentence, and so does the fact that this
check has no meaning for the {ref}`push-fed archetype <dc-push-fed>`.

```{note}
Core makes `UNSUPPORTED` **independently answerable** here — implementing
`check_source()` says nothing about this method, deliberately, so the one-line
opt-in does not die for plugins that can only do one of the two.
```

### 5.1 Compose, don't integrate

Build the check from calls your plugin **already knows how to make**: wire up
dead code, membership-test an existing station list, add a not-found branch to
an existing call. Do **not** stand up a new vendor endpoint integration — a new
URL, a new response shape, vendor-doc reading, and usually no credentials on
hand to test against.

`UNSUPPORTED` stays a legitimate terminal answer where no read short of the real
data call exists. In practice, none of the nine functional ingestion plugins in
the current fleet needs it — the retrofit surface here is larger than early
survey work projected.

### 5.2 Report the identifier, plus the upstream's own label

Not the request URL. Host and path shape are connection-scope information
already covered by {ref}`§3 <dc-endpoint>` and {ref}`§4 <dc-check-source>`, and
the URL is where a query-string credential would live.

> **Report the station identifier as sent upstream, plus the upstream's own
> label for that station when the call already returns it.**

The label is the part that earns its place:

```
Station 5faab2c1 found upstream as "Nairobi — Dagoretti Corner".
```

A bare existence check is blind to a **valid-but-wrong** identifier — a real
station ID belonging to a different site — and that is the failure that produces
silent, plausible, *wrong* data rather than an outage. Include the label
**when the call already returns one**; it is a conditional, not a required
field.

### 5.3 Proven absence is `FAILED` / `PATH_NOT_FOUND` — on positive proof only

Non-existence is not suspicion, it is proof: a station link whose upstream
identifier does not exist can never ingest anything.

> **`PATH_NOT_FOUND` may only be claimed on positive proof from a response we
> successfully received and parsed** — the station absent from a station list
> that returned `200`, or a station-addressed resource returning `404` against a
> base URL the plugin has no reason to doubt.

It must **never be inferred from a failure**. A `404` that might equally mean a
wrong endpoint path, an API version bump, or a routing fault is a
`PROTOCOL_ERROR` or an unclassified `FAILED`. A wrong claim here sends the
operator to re-type a station ID that was correct all along.

```{important}
**A cached response is not proof.** This is the precondition on the rule above,
not a separate requirement — and it bites harder here than at connection scope.
At connection scope a cached response is a false `OK`. Here it is a false
`PATH_NOT_FOUND`: an operator adds a station upstream, links it, runs the check,
and a 24-hour-old list produces a confident *"this station does not exist
upstream"*. The check would actively cause the misconfiguration it exists to
detect.

Bypass the cache **unconditionally over the whole check**, not just on the
`FAILED` branch. A rule with a carve-out is a rule that gets implemented wrong,
and the `OK` path has its own cached-data problem anyway — a station deleted
upstream still sitting in a 24-hour list reads as present.
```

**A soft-empty response is never proof of absence.** Where you cannot
distinguish "station missing" from "station present with nothing to report",
report `OK` with the count and do not guess. A call that returns `[]` for a
missing station **must** gain an explicit not-found branch, or it manufactures
the exact false confidence this check exists to prevent — and if that branch is
not composable, the honest answer is `UNSUPPORTED`, not a check that always
passes.

### 5.4 The count is an optional byproduct, and zero is `OK`

Report what the call already materialised, name it for what it is, and **never
add a call to obtain one**. A membership-test implementation carries identity
and outcome and no number, and that is complete.

```{warning}
The number must be **what the upstream reported**, never a count of your own
configured variable mappings. A number knowable without touching the network
says nothing about the source and is worse than no number, because it looks like
evidence.
```

**Zero sensors is `OK`**, with the zero stated plainly so the operator sees it
and decides. The principle: *the check reports `FAILED` only for what it can
prove is wrong, and `OK` with the number otherwise, leaving the operator to
judge.*

(dc-station-source-http)=

### 5.5 HTTP/REST

A membership test over the station list, or a station-addressed resource call
where one exists:

```python
def check_station_source(self):
    """Ask whether this station's upstream identifier resolves at the source
    (layer 5, station-scoped)."""
    from adl.core.source_checks import SourceCheckResult, SourceCheckStatus

    connection = self.network_connection
    try:
        # §5.3: unconditional cache bypass — a cached list is not proof.
        client = connection.get_api_client(use_cache=False, timeout=5, retries=0)
        stations = client.get_stations()
    except requests.RequestException as e:
        # §5.7: propagate or report, but never swallow into OK.
        return SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            message=_("Could not read the station list from %(host)s: %(error)s")
                    % {"host": connection.source_host, "error": e},
        )

    match = next((s for s in stations["data"]
                  if s["code"] == self.station_code), None)
    if match is None:
        return SourceCheckResult(
            status=SourceCheckStatus.FAILED,
            category="PATH_NOT_FOUND",
            message=_("Station %(code)s was not found in the source's station "
                      "list.") % {"code": self.station_code},
        )

    return SourceCheckResult(
        status=SourceCheckStatus.OK,
        # §5.2: identifier as sent upstream, plus the upstream's own label.
        message=_("Station %(code)s found upstream as \"%(label)s\".") % {
            "code": self.station_code, "label": match.get("name", ""),
        },
    )
```

Where the plugin already has a dead-code `get_station(id)` or
`get_station_sensors(id)` helper, wire that up instead — it is cheaper and
usually carries a sensor list for the {ref}`§5.4 <dc-station-source>` count.

Where the upstream flags a station **inactive**, report `OK` and say so: a
station that exists but is disabled upstream is the operator's call, not the
check's.

(dc-station-source-db)=

### 5.6 Direct database — two queries, not one

The station-table half is settled by the rules above: a cache-bypassed
membership test against the station table gives {ref}`§5.3 <dc-station-source>`
positive proof of absence — a station table is *authoritative*, unlike a
soft-empty data join — and a label for free.

**The second query closes a gap nothing else in the diagnostic can see.**
`check_source()` proves the credential authenticates and one round trip
returns; a membership test adds the station table. Neither touches the data
table your ingestion actually reads. A DBA granting `SELECT` per table and
missing one is an ordinary fault that produces a permanently silent connection:
layer 4 is fine, layer 5 says fine, layer 6 sees no records arriving with
nothing to blame.

So run the plugin's existing per-station query too — **for its error, not its
result**:

| SQLSTATE | Verdict |
|---|---|
| `42501` `insufficient_privilege` | `FAILED` / **`PERMISSION_DENIED`** |
| `42P01` `undefined_table`, everything else | `FAILED`, **decline the category** — schema drift is a plugin bug, not an operator misconfiguration |

Row count is a byproduct only, and zero rows is `OK`: a year-window query
returning nothing means "quiet for a year", which may be exactly the fault under
investigation but is not proof of one. Bypass the cache here too — per-station
queries in this archetype are often themselves cached for 24 hours, so a naive
implementation proves nothing at all.

(dc-station-source-file)=

### 5.7 File-based

Resolve the station's remote path, `cd` into it read-only, list it, and report
the **resolved** path and the match count. The resolved path is the right thing
to echo here precisely because it is *composed* — base directory plus a date
template — and therefore invisible on the edit screen.

A `cd` that fails is {ref}`§5.3 <dc-station-source>` positive proof:
`FAILED` / `PATH_NOT_FOUND`.

Zero matching files is `OK`, and here the reason is structural rather than a
judgement call: a date-structured directory is legitimately empty at every
rollover.

### 5.8 The last resort: the real data call, narrowest window

Where a plugin's **only** station-scoped read is the ingestion call itself, that
call is permitted — under two conditions:

1. **Only where no cheaper station-scoped read exists.** A plugin with a station
   list or a station-resource call uses that. This is not a shortcut around
   writing the membership test.
2. **The narrowest window the API accepts**, chosen so the call proves
   addressability rather than fetching data.

The check is read-only either way, so the objection is cost, not safety, and a
minimal window removes it. A response envelope that carries station identity
independently of the observations gives {ref}`§5.2 <dc-station-source>`'s
identifier-and-label echo directly; an empty observation list under a narrow
window is legitimately empty and stays `OK`; an absent or empty station block
against a `200` is positive proof of absence.

### 5.9 Propagate, never swallow

You are **not** required to catch and classify here — that is
{ref}`§7's <dc-stamping>` business, and requiring typed classification in every
station check would inflate every retrofit with exception-class design. Core
already catches everything and returns `FAILED` with the exception type and a
redacted message: no category, but honest and non-crashing.

```{important}
**The one rule that does belong here: never convert an error into `OK`.** A
bare `except: return OK`, a `.get()` chain that quietly yields `None`, or
treating an unparseable response as presence manufactures the false confidence
this check exists to destroy.
```

**Client construction goes inside the guarded region** — several clients
authenticate eagerly, so a credential fault must surface as a check failure
rather than an unhandled error.

---

(dc-sources-count)=

## 6. `adl_sources_count`

A duck-typed integer attribute set on the station link **from inside
`get_station_data()`**. Feeds layer 5's ability to say *"the source offered
nothing"* as distinct from *"we mishandled what it offered"*.

Decided by [#227](https://github.com/wmo-raf/adl/issues/227).

### 6.1 The unit: source items, not responses and not records

> **One source item = one thing the upstream offered that we would have to read
> to get observations out of it** — counted **for the requested window**,
> **after the response is parsed**, and **before any mapping, unit conversion,
> filtering or validation.**

A file, an API entry, a DB row.

| Unit | Why not |
|---|---|
| transport responses | never `0` when we got a reply, so it cannot detect "the source offered nothing" |
| **source items before conversion** | **← this one** |
| records after conversion | duplicates `records_count`, and moves with *our* mapping and validation, so a mapping bug reads as a source fault |

"Before conversion" is load-bearing, and it is the rule most often broken by
accident. A client that collapses raw rows into per-timestamp dicts **and
filters on a quality flag** can return `0` while the source returned a full
payload. Count the raw entries the response carried. Likewise, where a client
filters by *your configured sensor types*, count **all** sensors in the
response, not the mapped ones — and never count loop iterations over your own
mapping list.

(dc-count-zero)=

### 6.2 `0` means the source answered and its answer was empty

> **Commit the count only once a response is in hand and parsed. Never before
> the call.**

A call that errored is already layer-4/5 failure evidence with a category
stamped on it; it must not *also* assert the source offered nothing. `None` is
safe by construction — core's evidence rule abstains on `NULL` — so every
failure path has a free correct answer and there is never a reason to reach for
`0`.

Get this wrong and a connection that is down across the whole freshness window
logs an unbroken run of zeros, and layer 5 reports *"the source is offering no
data"* when the truth is we never got an answer. That is the diagnostic
accusing the partner's server of our own network failure — and it is one of the
{ref}`open defects in the reference implementation <dc-ftp-warning>`.

### 6.3 One idiom, fleet-wide

```python
# after each response is received and parsed, before conversion
if station_link.adl_sources_count is None:
    station_link.adl_sources_count = 0
station_link.adl_sources_count += len(entries)
```

The lazy initialise-on-first-parsed-response *is* the rule in §6.2, and it
resolves every shape without a second rule:

| Situation | Result | Reading |
|---|---|---|
| bailed early, first call raised, auth failed | stays `None` | silence — no claim made |
| every call answered, all empty | `0` | the honest source-empty |
| call 4 of 7 raises after 3 returned entries | `n > 0` on a `FAILED` row | **acquits** the source — right bias, we did see it offering data |
| call 1 of 7 raises | `None`, not `0` | no accusation from a run that barely looked |

Use it for single-call plugins too. There is no straight-assignment variant, and
the count deliberately does **not** scale by how many calls you intended to
make: `0` means "every answer we got was empty", never "we managed one of
seven".

### 6.4 The count leaves `client.py` by return value

`station_link.adl_sources_count = ...` appears only in `get_station_data()` —
one place per repo for the duck-typed contract. The client **returns** the count
alongside its records.

Rejected alternatives, so you don't rediscover them:

- **Passing `station_link` into the client** puts an ORM object in the client
  and breaks the DB-free test standard ({ref}`§10 <dc-tests>`).
- **`self.last_source_count` on the client** avoids signature churn, but a value
  left by a *previous* call is readable if the next one raises — manufacturing a
  number from stale state.

Signature churn is accepted. If a repo genuinely cannot lift the count out
otherwise, the fallback is hoisting fetch-and-parse up into `get_station_data()`
and leaving the client transport-only — correct, but a real refactor, and not
the default.

### 6.5 The window rule

> The count is of source items **for the requested window**. Where the source
> restricts to the window itself — a query API, a DB `WHERE`, a path pattern —
> the response *is* the count. **Where the source cannot, the plugin applies the
> window bound itself, on timestamps as received**, before any mapping, unit
> conversion or validation.

This exists for the **latest-snapshot** endpoint: a `current/<station_id>` call
that ignores the window and returns the console's last known reading whether it
is 4 minutes or 4 weeks old. A naive entry count there is always ≥ 1 for a
configured station, so layer 5 would permanently resolve *"found source data on
offer — the fault is downstream"* precisely when a dead console is the fault. A
constant that always acquits the source is worse than silence.

The bound is not our config smuggled in: `[start_date, end_date]` is the same
bound every other plugin's *source* applies on its behalf. Enforcing it locally
makes the archetypes comparable. Under this rule a dead console yields `0` and
layer 5 correctly reports `FAILED`.

The direct-database archetype needs no special rule: `len(rows)` after
`fetchall()`, committed once the fetch returns, because the `WHERE` clause
carries the window.

### 6.6 Mandatory across a connection

```{important}
**This contract only pays off when every station link on a connection
implements it.** Core's evidence rule abstains the moment **any single run** in
the freshness window reports `NULL`, so one unretrofitted station link silences
the check for the whole connection.

This is why `adl_sources_count` must land on a whole connection at once, and it
is the main sequencing constraint on this page ({ref}`§11 <dc-sequencing>`).
```

```{note}
{ref}`§4's cache-bypass rule <dc-cache-bypass>` is **not** inherited here. Every
cached path in the fleet's clients is a metadata picker — station lists, sensor
lists, sensor classes. No observation-data call is cached, so the count is read
off a live response by construction. Verified, not assumed; verify it again for
your own client before relying on it.
```

---

(dc-stamping)=

## 7. Exception stamping

When an ingestion run fails, core stamps the activity log with *what kind* of
failure it was. Your plugin can raise the precision of that stamp by tagging the
exception it re-raises.

Decided by [#228](https://github.com/wmo-raf/adl/issues/228).

**No plugin needs a new exception type.** `psycopg2.OperationalError` and
`requests.exceptions.HTTPError` instances both accept attribute assignment, so
the whole retrofit is:

```python
except requests.HTTPError as e:
    e.adl_category = "AUTH_FAILED"   # literal — never import FAILURE_CATEGORIES
    e.adl_layer = 5
    raise
```

Stamping **in place** keeps the original type (so core's own type table still
applies to everything left unstamped) and keeps the traceback.

**Where the stamp lives: `client.py`**, at the boundary that holds the code —
deliberately unlike {ref}`§6's count <dc-sources-count>`, which lives in
`plugins.py`. The split is principled: the count needs the station link, the
stamp needs the code.

(dc-stamping-wrapper)=

### 7.1 A wrapper must never be less classifiable than what it wraps

> **Where core's exception-type table already resolves the underlying type, you
> must either let it propagate unwrapped, or carry the same `(category, layer)`
> forward onto your wrapper.**

Core classifies `socket.gaierror` → `DNS_FAILURE`/4,
`builtins.ConnectionRefusedError` → `TCP_REFUSED`/4,
`requests.exceptions.ConnectTimeout` → `TCP_TIMEOUT`/**4** and
`requests.exceptions.ReadTimeout` → `TCP_TIMEOUT`/**5** — for free, with no
plugin involvement.

A plugin that catches those and re-raises its own flat error type **deletes**
that. It is the cheapest bug to introduce and the cheapest win to avoid: a
`try/except requests.RequestException` that re-raises a custom class silently
destroys the fleet's only free layer-5 read-timeout signal. See the
{ref}`reference-implementation warning <dc-ftp-warning>` for a shipped example
that collapses four distinct causes into one unclassifiable code.

(dc-stamping-invariant)=

### 7.2 The server-code invariant

> **A code from the server is proof the server answered.** Any category derived
> from a server-sent code is **layer 5**. Where there is no code, we never got an
> answer, the type alone cannot say why, and the plugin **declines**.

This removes raise-site layer plumbing entirely — you never thread
phase-awareness through your client.

| Type | Server code? | Stamp |
|---|---|---|
| `requests.HTTPError` from `raise_for_status()` | `.response.status_code` | category from status, **layer 5** |
| `requests.ConnectionError` | none | **decline** |
| `psycopg2.OperationalError`, `pgcode` set | SQLSTATE | category from SQLSTATE, **layer 5** |
| `psycopg2.OperationalError`, `pgcode is None` | none | **decline** |
| FTP error carrying a reply code | yes | category from the code, **layer 5** |
| FTP error from a client-observed timeout | none | **decline** |

**Accepted cost: no layer-4 stamping at plugin level, anywhere.** That is
correct rather than a compromise — layer 4 is exactly where core's type table is
already good and the plugin knows nothing extra.

(dc-status-table)=

### 7.3 The shared status table

Canonical default. A retrofit may **drop** an entry its vendor misuses; nobody
invents a new meaning for an existing code.

| Status | Category | Layer |
|---|---|---|
| 401 | `AUTH_FAILED` | 5 |
| 403 | `PERMISSION_DENIED` | 5 |
| 404 | `PATH_NOT_FOUND` | 5 |
| 5xx | `PROTOCOL_ERROR` | 5 |
| **400, 422** | **decline** | a malformed request is *our* bug; any stamp blames the source |
| **429** | **decline** | rate limiting is our polling schedule; every candidate category misattributes it |
| **3xx** | **decline** | |

`404` is safe despite reading as a station-scope answer: its rendered text is
*"the configured remote path was not found on the source"*, which is honest for
a wrong base URL at connection scope.

(dc-vocabulary)=

### 7.4 The closed vocabulary

Reproduced here so you never need to open core's source — and, per
{ref}`§2 <dc-version-skew>`, never import it either.

```
DNS_FAILURE   TCP_REFUSED   TCP_TIMEOUT   TLS_FAILURE   AUTH_FAILED
PERMISSION_DENIED   PATH_NOT_FOUND   PROTOCOL_ERROR   UNKNOWN
```

Layers: `4` (network path), `5` (source).

```{important}
**A plugin never stamps `UNKNOWN`**, even though it is a legal member.

A write-time stamp **suppresses** core's read-time classification tier
entirely. So stamping `UNKNOWN` permanently blocks the one tier that is
recomputed on every read and improves retroactively, and renders *"the run
failed with an unclassified connection error"* forever on rows a later text rule
would have classified correctly.

**Declining is the only outcome that stays revisable.** `UNKNOWN` exists for
core's own use, not the plugin's.
```

(dc-stamping-http)=

### 7.5 HTTP/REST

Stamp from `e.response.status_code` using {ref}`§7.3's table <dc-status-table>`.

**Vendors that return HTTP 200 with an in-body error code** are the one case
needing care: capture the code **while it is still an integer**, before it
becomes message text. Core matches on exception type and never on text, so a
code stringified into a `RuntimeError` message is unreadable to the whole
diagnostic. A body code is server-sent, therefore layer 5; its code *space* is
vendor-specific, so a per-plugin table is legitimate there.

```{warning}
A client that calls `requests.post()` and returns `response.json()` with **no
`raise_for_status()`** cannot stamp anything, because no exception is raised.
Adding `raise_for_status()` is a prerequisite for this contract — and it
**changes runtime behaviour**: runs that today surface a 401 or a 500 HTML page
as a downstream JSON decode error, or as silently absent data, will start
failing loudly. That is the correct outcome and exactly what the diagnostic
exists to expose, but it must be a deliberate, announced change rather than a
side effect of a classification retrofit.
```

(dc-stamping-db)=

### 7.6 Direct database

Stamp from `e.pgcode` using {ref}`§4.7's SQLSTATE table <dc-check-source-db>` —
the same table the probe path uses. Decline when `pgcode is None`.

(dc-stamping-file)=

### 7.7 File-based

Stamp from the FTP reply code where your client preserves one. Where your client
maps several distinct causes onto a single status, {ref}`§7.1 <dc-stamping-wrapper>`
applies: fix the mapping or let the original propagate.

### 7.8 Two boundaries

**Not mandatory, and safe to ship alone.** Unlike
{ref}`adl_sources_count <dc-sources-count>`, classification is **per-row** — an
unstamped failure simply falls to the read-time tier, which is where every row
sits today. So partial adoption harms nothing, and this is the safest of the
seven surfaces to ship first.

**Ingestion-only.** Dispatch failures write to the same activity log, but the
ingestion diagnostic reads `direction="pull"` rows only, so a dispatch-side
stamp lands in a column no consumer reads. Do not retrofit dispatch channels for
classification. If a dispatch-side diagnostic ever lands, these rules transfer
unchanged. Dispatch's surface is {ref}`test_connection() <dc-test-connection>`.

---

(dc-clean)=

## 8. `clean()` — audit, don't add

`clean()` is the one archetype-invariant surface, and the one where the right
answer is usually **change nothing**. Scoped at charting on
[map #221](https://github.com/wmo-raf/adl/issues/221); the mechanics are
core's, specified in [#171](https://github.com/wmo-raf/adl/issues/171) §10.

The mechanics are documented with the models, at
{doc}`plugin_implementation` §4.1 — `clean()` must be a pure check over the
model's own fields, raising `ValidationError` keyed by field name, with **no
I/O**, because the diagnostic re-runs `full_clean()` on stored rows outside the
request cycle to detect configuration drift.

What this map adds is a scoping rule for retrofits:

```{important}
**Config drift is audit-and-recommend only.** A retrofit reviews what its models
already validate and records the finding. It does **not** add new `clean()`
rules, because a new rule retroactively flags stored rows as `MISCONFIGURED`
across 26 deployments — rows that were valid when written and that nobody has
touched.

Adding validation is ordinary, welcome plugin work. It is just not *diagnostic
retrofit* work, and it should not ride in on a retrofit PR where an operator
will read it as the diagnostic breaking.
```

Note that a plugin with no `clean()` override is reported as **declaring no
configuration rules** (`UNSUPPORTED`), not as validated. That is honest, and it
is a perfectly acceptable end state.

---

(dc-test-connection)=

## 9. `test_connection()` — dispatch channels only

Lives on your `DispatchChannel` subclass. Returns a plain `dict`.

Decided by [#229](https://github.com/wmo-raf/adl/issues/229).

```{eval-rst}
.. automethod:: adl.core.models.DispatchChannel.test_connection
   :noindex:
```

### 9.1 The subject is that the destination *answers us*

> **Connect and authenticate. Nothing else.**

Both the reachability question and the credential question are answered by
construction, since these clients authenticate inside `__init__` — the body is
`get_client(); close()`.

**Do not probe writability.** Two tempting options are both wrong:

- **A read-only `cd` into the destination directory** fails ambiguously between
  "not there" and "denied" — and "not there" is a case production handles
  silently, because the upload path creates missing directories as it descends.
  So it would report `ok: False` for a channel that dispatches perfectly: the
  check *inventing* an alarm. And the result dict has only `ok: bool` — no third
  state in which to say *"reached it, path unconfirmed, probably fine"*.
- **A write-and-delete probe** puts side effects on a **third party's** server,
  under a 60-second cooldown and a 15-second kill that can abandon a
  half-written file.

**Writability is unprovable read-only over FTP. State the limit rather than
papering over it with a probe that either lies or litters.**

### 9.2 The message carries its own limit

```
Connected and authenticated to {host}:{port} as {user}.
Write access to {directory} was not tested.
```

The limit clause is carried here even though `check_source()` omits its own, and
the asymmetry is deliberate. `check_source()` reports into a diagnostic whose
*other layers* cover what it omits. **This message has no such context — it is
the entire output of a button, read once, by a human, with nothing else on
screen.** One clause against an operator concluding "test passed, so dispatch
works" and then hunting the wrong layer when files stop arriving.

Exactly **one** omission is named — the channel's primary purpose, writing —
which keeps it from becoming a disclaimer.

### 9.3 Bound it — dispatch has no timeout at all

Same precondition as {ref}`§4.4 <dc-check-source-bounded>`, and worse here.
Clients typically fall back to a signature default of 20 seconds, already over
core's 15-second wall clock before the check does anything. **SFTP is far
worse:** `SSHClient.connect(timeout=…)` bounds only TCP and the handshake, while
paramiko's `Transport` independently sets `banner_timeout = 15` and
`auth_timeout = 30` and leaves them alone when not passed. Sequential worst case
is around 65 seconds.

The fix is {ref}`§4.4's <dc-check-source-bounded>` verbatim — a factory
argument, `get_client(timeout=None)`, defaulting to today's behaviour so
dispatch is untouched; the probe passes `timeout=5`. For SFTP, pass
`banner_timeout`, `auth_timeout` and `channel_timeout` through as well.

```{note}
**A model field was rejected.** An operator who raises a configurable timeout to
300 for a slow partner silently re-breaks the probe.
```

```{warning}
**For a multi-phase protocol, per-phase timeouts make the ~10-second contract
*likely*, never *guaranteed*. Core's wall clock is the only guarantee.** That
headroom between the contract and the wall clock is deliberate — but do not
treat the wall clock as your bound.
```

### 9.4 Catch the client's own error type only

`except (FTPError, SFTPError)` and nothing wider — {ref}`§4.7's rule
<dc-check-source-db>` again. Core's container is the designated handler and logs
strictly more than you would; a bare `except Exception` flattens a traceback
into a friendly sentence.

```{important}
**Never return a `SourceCheckResult` from `test_connection()`.** In a repo that
implements both surfaces, a `failed_source_check_result()`-style helper sits a
few dozen lines away in the same file and looks like the obvious thing to reuse.
It is rejected by core as *"…returned SourceCheckResult instead of a
test-connection dict"* — legible, and useless to the operator.

The two shapes differ because they have two readers. `test_connection()` has
exactly one caller in the whole codebase — the admin button — and its result
becomes a flash message and is discarded. Nothing persists it, nothing
machine-reads it, and per {ref}`§7.8 <dc-stamping>` the diagnostic reads pull
rows only, so a dispatch-side category would be **write-only by construction**.
```

### 9.5 Keep the mixin first in the bases

The documented pattern for a dispatch channel is an abstract config-and-client
mixin combined with `DispatchChannel`:

```python
class MyUpload(BaseMyUpload, DispatchChannel):   # mixin FIRST
    ...
```

Reverse them and `DispatchChannel.test_connection` wins the MRO, your override
vanishes, and core's support probe returns `False` — so the button reports *"not
supported for this channel type"*. Legible, wrong, and silent.

```{note}
The version-skew tax here is **zero**. `test_connection()` returns a plain dict
and imports nothing from `adl.core`, so there is no lazy-import line and nothing
for the AST guard to check.
```

---

(dc-tests)=

## 10. Tests and lint baseline

Decided by [#234](https://github.com/wmo-raf/adl/issues/234).

```{note}
Very little here is new practice. Most of what looked like a plugin standard was
never real: the cookiecutter's `make lint` target has never run green in **any**
repo, and core itself carries no lint configuration at all. This section makes
an existing practice work rather than introducing one.
```

### 10.1 Running the tests

Each plugin repo carries a **repo-root `Makefile`** with a `test` target that
runs against the plugin's own compose stack:

```make
test:
	docker compose exec adl adl test --keepdb <module>.tests
```

Everything it needs already ships in the repo — the compose stack,
`dev.Dockerfile`, the dev-installed plugin, and the dev settings module. The
target **declares what already works implicitly**; nothing new is stood up. The
invocation is identical in every repo, differing only in the module name.

```{important}
**"DB-free" does not mean "no database".** Django's test runner calls
`setup_databases()` unconditionally regardless of test class, so `SimpleTestCase`
buys you no fixtures, no per-test migrations, and speed — it does **not** make
the tests runnable outside the stack. There is no configuration that does. Write
`SimpleTestCase` tests with unsaved model instances and stubbed clients, and run
them on the stack.
```

### 10.2 What to test

One module, at `src/<module>/tests/test_source_checks.py`:

- for **each surface the plugin implements**, a happy path plus each failure
  branch it classifies;
- the copied {ref}`AST lazy-import guard <dc-version-skew>`.

```{important}
**Surfaces the plugin declines get no test.** Asserting that the base class
still returns `UNSUPPORTED` tests *core*, not the plugin — and pinning core's
default from a dozen repos means one legitimate core change breaks every
plugin's suite at once.

The carve-out: where the entire answer **is** a declaration — the push-fed
archetype's `has_external_source = False` — that attribute is the thing to
assert, because the plugin genuinely asserts nothing else.
```

Test scaffolding is copied **per repo**, with `adl/plugin-boilerplate/` as the
canonical source — the same policy as the AST guard, not a second one. A shared
testkit was rejected: a stubbed `requests.Session`, a stubbed `psycopg2`
connection and a fake FTP client have nothing structurally in common, and
putting helpers in `adl.core.testing` would make a plugin's tests require a core
new enough to contain them — reintroducing version skew at the one place where
testing against an *older* core matters most.

### 10.3 Lint

`make lint` is `flake8 src`, and `.flake8`'s `per-file-ignores` targets
`src/*/tests/*`.

The stock target is broken three independent ways in every repo: it names a
top-level `tests/` directory that exists nowhere (tests live at
`src/<module>/tests/`, already covered by `src`), and it invokes `black` and
`bandit`, which ship in no requirements file.

`black --check` and `bandit` come **out** of the target; `make format` stays as
opt-in black.

```{note}
**Black is deferred, not dropped.** Measured with each repo's own excludes
applied, roughly **40% of every repo's source is not black-clean, including the
reference plugin**. Enabling `--check` means a mass-reformat commit landing
immediately before each retrofit diff, wrecking blame across the fleet and
burying the change under noise. A dedicated formatting sweep after the retrofits
ship costs far less.
```

### 10.4 Enforcement

**Developer-run, no CI.** There is no CI anywhere in the project today, and the
base image is built locally and published to no registry — so a per-plugin
workflow would have to clone core and build a PostGIS + TimescaleDB image on
every push, in a dozen repos.

`make test` and `make lint` are run by the implementer and named explicitly in
each repo's implementation-issue acceptance criteria. "Mandatory" means checked
at review, which is how the whole project already works — and it is why the
acceptance criteria have to be checkable by reading.

---

(dc-sequencing)=

## 11. Sequencing constraints

There is **no rollout order**. The constraints below are a partial order at
best: they say which things are safe to go first, not what follows what. Pick up
any repo's issue in any order and these are the facts that bind you.

1. **Exception stamping is safe alone and safe first.** Classification is
   per-row, so an unstamped failure just falls to the read-time tier — where
   every row is today. Partial adoption harms nothing.
   ({ref}`§7.8 <dc-stamping>`)
2. **`adl_sources_count` must land on a whole connection at once.** Core's
   evidence rule abstains on a single `NULL`, so one unretrofitted station link
   silences the check for the entire connection. ({ref}`§6.6 <dc-sources-count>`)
3. **Every retrofit PR opens with the lint fix.** It is one line, and you cannot
   claim a green gate without it. ({ref}`§10.3 <dc-tests>`)
4. **The first repo to ship proves the root-`Makefile` `test` target.** Nobody
   has run it as a declared target before. ({ref}`§10.1 <dc-tests>`)
5. **`plugin-boilerplate` is not in the ordering at all.** It serves the *next*
   plugin, not the existing fleet, so it can land at any point — during the
   rollout or after it.
6. **The dispatch surface is the cheapest item on this page.** One method, on
   one abstract mixin, in one repo, with zero version-skew tax.
   ({ref}`§9 <dc-test-connection>`)

Beyond these, each repo's implementation issue states **its own** gates and
nothing else.
