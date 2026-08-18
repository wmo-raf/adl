"""
Tests for the ingestion-diagnostic contracts: ``get_source_endpoint()``,
``check_source()``, ``check_station_source()`` and the ``adl_sources_count``
duck-typed handover. See the "Ingestion Diagnostic Contracts" page in the ADL
developer guide.

Convention for everything added to this module: **the tests touch no database**.
Build model instances unsaved and stub the source client, so the seam under test
is exactly the contract core consumes. That means ``SimpleTestCase``, never
``TestCase`` — no fixtures, no per-test migrations. Django still calls
``setup_databases()`` whatever the test class, so the suite is run on this
plugin's own compose stack with ``make test`` from the repo root; "DB-free" is
about what the tests touch, not where they run.

Add one test class per surface this plugin implements, each with a happy path
plus every failure branch it classifies. Surfaces the plugin deliberately
declines get no test: asserting that core still returns ``UNSUPPORTED`` tests
core, not this plugin.

The guard below ships with the scaffold and is correct before any plugin code
exists — it parses the source rather than running it.
"""

import ast
import os

from django.test import SimpleTestCase


class OlderCoreImportSafetyTests(SimpleTestCase):
    """The plugin must import cleanly on a core release that predates the
    source-check contracts, so nothing may import ``adl.core.source_checks``
    at module level.

    The contracts import it lazily instead, inside the method that needs it::

        def check_source(self):
            from adl.core.source_checks import SourceCheckResult
            ...

    Never wrap that import in ``try/except ImportError``: on an older core the
    method is never called, so the handler is unreachable, and it would turn a
    genuine import failure into a silent "this plugin does not support the
    check".
    """

    # Every module this plugin ships. Extend it as the plugin grows more.
    MODULES = ["models.py", "plugins.py", "apps.py", "views.py",
               "wagtail_hooks.py"]

    DENIED = "adl.core.source_checks"

    def test_no_module_level_import_of_source_checks(self):
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in self.MODULES:
            path = os.path.join(package_dir, name)
            if not os.path.exists(path):
                continue  # a module this plugin does not (yet) ship
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
                    self.DENIED, [module] + names,
                    f"{name} imports {self.DENIED} at module level")
