# Prototype: diagnostic contracts at plugin birth

Sketch for [#230](https://github.com/wmo-raf/adl/issues/230), map
[#221](https://github.com/wmo-raf/adl/issues/221). Files as they would be
generated, not descriptions of them.

## The finding that reshapes the ticket

`plugin-boilerplate`'s generated `models.py` is **0 bytes**. There is no
`NetworkConnection` subclass and no `StationLink` subclass, so three of the
four ingestion contracts have no class to sit on; `plugins.py` is a five-line
stub whose `get_station_data()` is `return []`, so the fourth has no loop to
attach to. The cookiecutter does not produce a working plugin — it produces a
package skeleton.

The models are written by **`adl-project/.claude/commands/new-plugin.md` §4**,
per archetype, by copying the reference plugin. That command knows the
archetype; the cookiecutter never does (`cookiecutter.json` has four inputs:
name, slug, module, description).

**So the surface splits by what each carrier can honestly know.**

| Carrier | Ships | Because |
|---|---|---|
| `plugin-boilerplate` | `tests/` package + AST guard, root `Makefile`, fixed lint | true for every plugin, archetype-blind |
| `/new-plugin` §1 | push-vs-pull gate | routes to #233's fourth archetype |
| `/new-plugin` §4 | contract bodies, surface tests, README checklist | needs the archetype |

---

## Part 1 — what the cookiecutter ships

### `plugins/{{ cookiecutter.project_module }}/src/{{ cookiecutter.project_module }}/tests/__init__.py`

Empty. New file — no `tests/` package exists in the boilerplate today.

### `.../tests/test_source_checks.py`

The AST guard alone. It parses source rather than running it, so it is the one
test that is correct before any code exists, passes vacuously on an empty
`models.py`, and goes live the moment the author writes a lazy import. Copied
per repo with the boilerplate canonical, per [#223](https://github.com/wmo-raf/adl/issues/223)
and [#234](https://github.com/wmo-raf/adl/issues/234).

```python
"""
Tests for the ingestion-diagnostic contracts.

All tests run without fixtures: model instances are built unsaved and the
source client is stubbed, so the seam under test is exactly the contract
core consumes.
"""

import ast
import os

from django.test import SimpleTestCase


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

Two deltas from `adl-ftp-plugin`'s copy: the `os.path.exists` skip (the
boilerplate ships no `models.py` content, and a hand-run cookiecutter may not
add one for a while), and the docstring stating the DB-free convention up
front so the author inherits it as shape rather than as prose.

### `Makefile` — new, at the repo root

No repo-root `Makefile` exists in the boilerplate today. #234 named the
boilerplate canonical for the runner it decided on.

```make
test:
	docker compose exec adl adl test --keepdb {{ cookiecutter.project_module }}.tests

lint:
	docker compose exec adl make -C /adl/plugins/{{ cookiecutter.project_module }} lint
```

### `plugins/{{ cookiecutter.project_module }}/Makefile` — #234's one-line fix

```diff
 lint:
-	flake8 src tests && \
-	black . --extend-exclude='/generated/' --check && \
-	bandit -r src/ \
-	|| exit;
+	flake8 src || exit;
```

`tests` names a top-level directory that exists in zero repos — tests live at
`src/<module>/tests/` and are already covered by `src`. `black` and `bandit`
ship in no requirements file. `make format` stays; `black --check` is deferred
per #234, not dropped.

### `plugins/{{ cookiecutter.project_module }}/.flake8`

```diff
 per-file-ignores =
-    tests/*: F841
+    src/*/tests/*: F841
```

---

## Part 2 — what `/new-plugin` §1 gains

The gate, ahead of the existing seven-option list, so push-vs-pull is answered
before the author reads four contracts that may not apply
([#233](https://github.com/wmo-raf/adl/issues/233)):

```markdown
### 1. Confirm inputs

**First, ask: does ADL dial out to fetch this data, or is the data pushed to
ADL / written in place?** This is asked before the archetype because it decides
whether the diagnostic's external layers have a subject at all.

- **Pushed / written in place** → *internal / push-fed source*. There is no
  upstream to reach, so `models.py` declares `has_external_source = False` and
  none of the four ingestion contracts is stubbed. Reference:
  `adl-collector-app-plugin`. Skip to step 4c.
- **ADL dials out** → ask which archetype applies:

  [existing seven-option list unchanged]
```

**Dependency.** `has_external_source` is core-side and not yet shipped —
[#235](https://github.com/wmo-raf/adl/issues/235) is open. Until it lands, the
generated attribute is inert but harmless (an unread class attribute), and the
generated code is correct in advance. The `/new-plugin` text should say so in
one line rather than wait.

---

## Part 3 — what `/new-plugin` §4 writes

Structure real, vendor call `TODO` — mirroring how §4 already treats
`client.py` (*"stub out the methods... with TODOs for endpoint URLs and auth"*).
Everything the archetype decisions fixed is written for real: the lazy import,
the narrow `except`, the status/category table, a `SourceCheckResult` on every
path, the accumulate idiom. The one unknowable line calls into the client stub
§4 generates alongside.

### `models.py` — worked instance, `http-per-station` / `http-shared`

```python
# Shared by check_source() and check_station_source(); #228's narrow table,
# literals only — never imports FAILURE_CATEGORIES (#223).
_STATUS_CATEGORIES = {
    401: "AUTH_FAILED",
    403: "AUTH_FAILED",
    404: "PATH_NOT_FOUND",
}


def _category_for_status(status_code):
    """A code from the server is proof the server answered, so any
    code-derived category is layer 5. Codes outside the table decline."""
    if status_code in _STATUS_CATEGORIES:
        return _STATUS_CATEGORIES[status_code]
    if 500 <= status_code < 600:
        return "SOURCE_ERROR"
    return None


class {{ Name }}Connection(NetworkConnection):
    # ... credential fields, panels, Meta, get_api_client() ...

    def get_source_endpoint(self):
        # #225: every HTTP plugin names an endpoint, hard-coded hosts
        # included — a hard-coded host is not a guess, it is the literal
        # string `requests` dials. Where two hosts exist, name the DATA
        # host, never the IdP.
        return (urlparse(self.base_url).hostname,
                urlparse(self.base_url).port or 443)

    def check_source(self):
        from adl.core.source_checks import SourceCheckResult, SourceCheckStatus

        # Bounded: core's probe budget is 15s and the ingestion defaults
        # blow it. Defaults on get_api_client preserve ingestion behaviour.
        client = self.get_api_client(use_cache=False, timeout=5, retries=0)
        try:
            # TODO: the cheapest read-only call on the DATA host, cache
            # bypassed. See the plugin-author guide, HTTP/REST archetype.
            payload = client.list_stations()
        except requests.HTTPError as e:
            status_code = e.response.status_code
            return SourceCheckResult(
                status=SourceCheckStatus.FAILED,
                category=_category_for_status(status_code),
                # #225: name host and path, never a query string.
                message=_("%(host)s%(path)s answered %(code)s.") % {...},
            )
        except requests.RequestException as e:
            return SourceCheckResult(
                status=SourceCheckStatus.FAILED, message=str(e))

        # #225: OK requires a parsed response of the expected shape, never a
        # bare 2xx — this one rule kills both the 200-with-error-body and the
        # login-page redirect.
        if not isinstance(payload, list):
            return SourceCheckResult(
                status=SourceCheckStatus.FAILED,
                message=_("%(host)s%(path)s answered 200 with an unexpected "
                          "body.") % {...},
            )
        return SourceCheckResult(
            status=SourceCheckStatus.OK,
            message=_("%(host)s%(path)s returned %(count)s stations.") % {...},
        )


class {{ Name }}StationLink(StationLink):
    # ... upstream id field, start_date, panels, Meta,
    #     get_variable_mappings(), get_first_collection_date() ...

    def check_station_source(self):
        from adl.core.source_checks import SourceCheckResult, SourceCheckStatus

        # #226: the subject is external addressability. Cache bypass is
        # unconditional — a stale list turns a newly-added station into a
        # confident false PATH_NOT_FOUND, so the check would cause the
        # misconfiguration it detects. Client construction goes inside the
        # guarded region.
        try:
            client = self.network_connection.get_api_client(
                use_cache=False, timeout=5, retries=0)
            # TODO: the call that lists or fetches this one station.
            stations = client.list_stations()
        except requests.RequestException as e:
            # #226: propagate rather than classify, and NEVER swallow an
            # error into OK — absence is only ever proven from a parsed
            # response, never inferred from a failure.
            return SourceCheckResult(
                status=SourceCheckStatus.FAILED, message=str(e))

        # TODO: the field holding the upstream's own label for the station.
        match = next(
            (s for s in stations if s["id"] == self.station_upstream_id), None)
        if match is None:
            return SourceCheckResult(
                status=SourceCheckStatus.FAILED,
                category="PATH_NOT_FOUND",
                message=_("The source does not list station %(id)s.")
                        % {"id": self.station_upstream_id},
            )
        # #226: report the identifier as sent upstream PLUS the upstream's
        # own label — the label is what catches a valid-but-wrong ID, the
        # failure that yields silent plausible wrong data.
        return SourceCheckResult(
            status=SourceCheckStatus.OK,
            message=_("The source lists station %(id)s as %(name)s.")
                    % {"id": self.station_upstream_id, "name": match["name"]},
        )
```

### `models.py` — the other archetypes

Same shape, three substitutions, each one line in the guide:

- **`db`** ([#224](https://github.com/wmo-raf/adl/issues/224)) — endpoint is
  `(self.db_host, self.db_port)`; `check_source()` is
  `get_client(connect_timeout=5)` → `set_session(readonly=True)` → `SELECT 1`
  → close, catching `psycopg2.OperationalError` **only**, classifying on
  server-sent SQLSTATE (`28P01`/`28000` → `AUTH_FAILED`, `3D000` →
  `PATH_NOT_FOUND`) and declining `pgcode is None`. `check_station_source()`
  runs **two** queries: cache-bypassed membership test, then the existing
  per-station query for its error (`42501` → `PERMISSION_DENIED`).
- **`ftp`** — `adl-ftp-plugin` verbatim, minus the two defects the map filed
  against it ([#4](https://github.com/wmo-raf/adl-ftp-plugin/issues/4),
  [#5](https://github.com/wmo-raf/adl-ftp-plugin/issues/5)).
- **`internal`** (#233) — one line, and the four contracts are **absent**, not
  stubbed:

  ```python
  class {{ Name }}Connection(NetworkConnection):
      # No upstream: the diagnostic's external layers have no subject here,
      # now or ever. Core suppresses layer-4/5 evidence gathering on this
      # declaration (adl#235) rather than letting it fabricate an OK.
      has_external_source = False
  ```

### `plugins.py` — the count

```python
def get_station_data(self, station_link, start_date=None, end_date=None):
    client = station_link.network_connection.get_api_client()
    # ... resolve the window ...

    # TODO: the call returning this window's observations.
    entries = client.get_measurements(...)

    # #227: one source item is one thing the upstream offered that we would
    # have to read to get observations out of it — counted for the requested
    # window, after parsing and BEFORE any mapping, conversion, filtering or
    # validation. Set only once an answer is in hand: leaving the attribute
    # unset is how "we never looked" stays distinguishable from "we looked
    # and the source offered nothing". Do NOT initialise it above the call.
    if getattr(station_link, "adl_sources_count", None) is None:
        station_link.adl_sources_count = 0
    station_link.adl_sources_count += len(entries)

    for entry in entries:
        # ... map to {"observation_time": ..., "<source_param>": ...} ...
        yield record
```

Two comments carry the traps #227 identified: the count is **not** a count of
yielded records (that duplicates `records_count` and turns a mapping bug into a
source fault), and where the source will not restrict to the window, **the
plugin applies the bound itself on timestamps as received**.

### `tests/test_source_checks.py` — appended below the guard

Archetype-shaped, `skipTest` until the vendor `TODO` is filled, so the first
`make test` is green-with-skips rather than red-at-birth.

```python
class FakeClient:
    """A stub source client capturing read-only calls."""

    def __init__(self, payload=(), error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def list_stations(self):
        self.calls.append("list_stations")
        if self.error is not None:
            raise self.error
        return self.payload


class CheckSourceTests(SimpleTestCase):

    def test_ok_on_expected_shape(self):
        self.skipTest("Fill the TODO in check_source(), then delete this line.")

    def test_401_is_auth_failed(self):
        self.skipTest("Fill the TODO in check_source(), then delete this line.")

    def test_200_with_unexpected_body_is_failed(self):
        self.skipTest("Fill the TODO in check_source(), then delete this line.")


class CheckStationSourceTests(SimpleTestCase):

    def test_ok_reports_upstream_label(self):
        self.skipTest("Fill the TODO in check_station_source().")

    def test_unlisted_station_is_path_not_found(self):
        self.skipTest("Fill the TODO in check_station_source().")


class SourcesCountTests(SimpleTestCase):

    def test_count_is_zero_when_source_answers_empty(self):
        self.skipTest("Fill the TODO in get_station_data().")

    def test_count_unset_when_the_call_raises(self):
        self.skipTest("Fill the TODO in get_station_data().")
```

For the `internal` archetype the whole module is the guard plus one assertion,
per #234's carve-out that where the answer **is** a declaration, that attribute
is the test:

```python
class InternalSourceTests(SimpleTestCase):
    def test_declares_no_external_source(self):
        self.assertFalse({{ Name }}Connection.has_external_source)
```

### `README.md` — appended section

Written by `/new-plugin`, not the cookiecutter: the checklist names the
archetype and the specific stubs left behind, neither of which the cookiecutter
knows. It tracks state the code cannot — which TODOs are still unfilled — and
shrinks to nothing as the author works. It is **not** a second copy of the
guide.

```markdown
## Before you ship

This plugin was scaffolded with the ingestion-diagnostic contracts stubbed for
the **<archetype>** archetype. Until these are done, the diagnostic reports
`UNSUPPORTED` for this connection's source layers. See the plugin-author guide
for what each contract means for this archetype.

- [ ] Fill the TODO in `check_source()` — the cheapest read-only call on the
      data host, cache bypassed
- [ ] Fill the TODO in `check_station_source()` — the station membership test
- [ ] Fill the TODO in `get_station_data()` — `adl_sources_count`
- [ ] Un-skip the tests in `src/<module>/tests/test_source_checks.py`
- [ ] `make test` green, `make lint` clean
```

---

## What this costs

Five new or edited files in `plugin-boilerplate` (two new: `tests/__init__.py`,
`tests/test_source_checks.py`, root `Makefile`; two edited: `plugins/*/Makefile`,
`.flake8`) and one section rewrite plus one section addition in
`new-plugin.md`. No core change, no migration, and nothing that the twelve
retrofits depend on — this ticket is about plugin #22, so it can ship at any
point in the rollout.
