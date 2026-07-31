"""
The coupling between the pinned broker stack and the version guards.

There is no CI in this repo, so the load-bearing test is the one that fails
when someone bumps a pin in requirements.txt and forgets the tested ranges
in ``adl.core.broker`` (or the constraints file that binds plugin installs).
Without it, a stale range makes the guard report UNSUPPORTED on a stack that
works fine — the false alarm that is the strongest argument against version
predicates. No test here asserts a timing; the measured figures are the
rationale for the pins, not a contract.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

import adl
from adl.core.broker import (
    BROKER_LIBRARIES,
    TESTED_LIBRARY_RANGES,
    version_in_tested_range,
)

_PIN_PATTERN = re.compile(r"^([A-Za-z0-9._-]+)==(\S+)\s*$")


def _project_root():
    """The directory holding requirements.txt — the checkout's ``adl/`` in
    development, ``/adl/app`` inside the containers."""
    candidates = (Path(adl.__file__).resolve().parents[2], Path("/adl/app"))
    for candidate in candidates:
        if (candidate / "requirements.txt").exists():
            return candidate
    raise AssertionError(
        "requirements.txt not found beside the adl package (looked in %s)"
        % ", ".join(str(c) for c in candidates)
    )


def _pins(filename):
    pins = {}
    for line in (_project_root() / filename).read_text().splitlines():
        match = _PIN_PATTERN.match(line.strip())
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


class BrokerStackPinTests(SimpleTestCase):
    def test_broker_libraries_are_pinned_exactly_in_requirements(self):
        pins = _pins("requirements.txt")
        for name in BROKER_LIBRARIES:
            self.assertIn(
                name, pins,
                "%s must be a direct, exactly-pinned dependency: first-party "
                "code calls its APIs, so it must not arrive transitively" % name,
            )

    def test_constraints_file_mirrors_the_requirements_pins(self):
        # The constraints file is what binds plugin installs to the tested
        # stack; a drifted copy would let a plugin resolve past the pins
        requirement_pins = _pins("requirements.txt")
        constraint_pins = _pins("constraints.txt")
        for name in BROKER_LIBRARIES:
            self.assertEqual(
                constraint_pins.get(name), requirement_pins.get(name),
                "constraints.txt must carry the same %s pin as "
                "requirements.txt" % name,
            )

    def test_every_pin_is_inside_its_tested_range(self):
        # THE coupling test: bumping a pin without re-testing and widening
        # TESTED_LIBRARY_RANGES must fail here, or the guard would report
        # UNSUPPORTED on the very stack the deployment ships
        pins = _pins("requirements.txt")
        for name in BROKER_LIBRARIES:
            self.assertIs(
                version_in_tested_range(name, pins.get(name)), True,
                "%s==%s is outside the tested range %s declared in "
                "adl.core.broker.TESTED_LIBRARY_RANGES — re-test and widen "
                "the range together with the pin" % (
                    name, pins.get(name), TESTED_LIBRARY_RANGES[name],
                ),
            )
