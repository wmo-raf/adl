"""
Tests for the source-check contract: the base-class defaults on
``NetworkConnection``, the normaliser that refuses to trust a malformed
plugin return, and the core-owned DNS -> TCP -> ``check_source`` probe.

The probe never dials a real host in tests — DNS and TCP sit behind the
module's ``socket`` reference and are patched there.
"""

import socket
from unittest.mock import patch

from django.test import TestCase

from adl.core.source_checks import (
    CHECK_DNS,
    CHECK_SOURCE,
    CHECK_TCP,
    SourceCheckResult,
    SourceCheckStatus,
    normalise_source_check_result,
    run_source_probe,
)
from adl.core.tests.factories import NetworkConnectionFactory


class BaseContractDefaultTests(TestCase):
    """No existing plugin implements the contract; the defaults must keep
    all of them working untouched."""

    def setUp(self):
        self.connection = NetworkConnectionFactory()

    def test_base_get_source_endpoint_returns_none(self):
        self.assertIsNone(self.connection.get_source_endpoint())

    def test_base_check_source_reports_unsupported(self):
        result = self.connection.check_source()

        self.assertEqual(result.status, SourceCheckStatus.UNSUPPORTED)

    def test_base_connection_does_not_support_the_probe(self):
        self.assertFalse(self.connection.source_probe_supported)


class NormaliserTests(TestCase):
    """A plugin return is never trusted: anything that is not a well-formed
    SourceCheckResult degrades to MALFORMED rather than crashing or lying."""

    def test_a_well_formed_result_passes_through_unchanged(self):
        result = SourceCheckResult(
            status=SourceCheckStatus.OK,
            category=None,
            message="Listed 3 files.",
            latency_ms=120,
        )

        self.assertEqual(normalise_source_check_result(result), result)

    def test_result_is_frozen(self):
        result = SourceCheckResult(status=SourceCheckStatus.OK)

        with self.assertRaises(Exception):
            result.status = SourceCheckStatus.FAILED

    def test_a_non_result_return_degrades_to_malformed(self):
        for malformed in (None, {"ok": True}, "fine", 200, (True, "ok")):
            result = normalise_source_check_result(malformed)
            self.assertEqual(result.status, SourceCheckStatus.MALFORMED, malformed)

    def test_an_unknown_status_degrades_to_malformed(self):
        result = normalise_source_check_result(
            SourceCheckResult(status="GREAT_SUCCESS")
        )

        self.assertEqual(result.status, SourceCheckStatus.MALFORMED)

    def test_a_category_outside_the_shared_vocabulary_is_dropped_not_trusted(self):
        result = normalise_source_check_result(
            SourceCheckResult(status=SourceCheckStatus.FAILED, category="EATEN_BY_BEARS")
        )

        self.assertEqual(result.status, SourceCheckStatus.FAILED)
        self.assertIsNone(result.category)

    def test_a_valid_category_survives(self):
        result = normalise_source_check_result(
            SourceCheckResult(status=SourceCheckStatus.FAILED, category="AUTH_FAILED")
        )

        self.assertEqual(result.category, "AUTH_FAILED")


class ProbeTestCase(TestCase):
    def setUp(self):
        self.connection = NetworkConnectionFactory()

    def with_endpoint(self, host="ftp.example.org", port=21):
        self.connection.get_source_endpoint = lambda: (host, port)

    def with_check_source(self, result):
        self.connection.check_source = lambda: result

    def steps_by_id(self, steps):
        return {step.check_id: step for step in steps}


class ProbeOrchestrationTests(ProbeTestCase):
    def test_probe_reports_dns_and_tcp_separately_then_the_source_check(self):
        self.with_endpoint()
        self.with_check_source(SourceCheckResult(status=SourceCheckStatus.OK,
                                                 message="Listed files."))

        with patch("adl.core.source_checks.socket.getaddrinfo", return_value=[("stub",)]), \
                patch("adl.core.source_checks.socket.create_connection"):
            steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertEqual(set(steps), {CHECK_DNS, CHECK_TCP, CHECK_SOURCE})
        self.assertEqual(steps[CHECK_DNS].result.status, SourceCheckStatus.OK)
        self.assertEqual(steps[CHECK_TCP].result.status, SourceCheckStatus.OK)
        self.assertEqual(steps[CHECK_SOURCE].result.status, SourceCheckStatus.OK)
        # The layer is stamped by the producer: DNS and TCP are the network
        # path (4), the credential/data check is the source (5)
        self.assertEqual(steps[CHECK_DNS].layer, 4)
        self.assertEqual(steps[CHECK_TCP].layer, 4)
        self.assertEqual(steps[CHECK_SOURCE].layer, 5)

    def test_dns_failure_is_not_reported_as_a_dead_host(self):
        self.with_endpoint()

        with patch("adl.core.source_checks.socket.getaddrinfo",
                   side_effect=socket.gaierror("no such host")):
            steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertEqual(steps[CHECK_DNS].result.status, SourceCheckStatus.FAILED)
        self.assertEqual(steps[CHECK_DNS].result.category, "DNS_FAILURE")
        # TCP and the source check never ran, so the probe must not claim
        # anything about them
        self.assertNotIn(CHECK_TCP, steps)
        self.assertNotIn(CHECK_SOURCE, steps)

    def test_tcp_refused_stops_before_the_source_check(self):
        self.with_endpoint()

        with patch("adl.core.source_checks.socket.getaddrinfo", return_value=[("stub",)]), \
                patch("adl.core.source_checks.socket.create_connection",
                      side_effect=ConnectionRefusedError()):
            steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertEqual(steps[CHECK_TCP].result.status, SourceCheckStatus.FAILED)
        self.assertEqual(steps[CHECK_TCP].result.category, "TCP_REFUSED")
        self.assertNotIn(CHECK_SOURCE, steps)

    def test_tcp_timeout_is_its_own_category(self):
        self.with_endpoint()

        with patch("adl.core.source_checks.socket.getaddrinfo", return_value=[("stub",)]), \
                patch("adl.core.source_checks.socket.create_connection",
                      side_effect=socket.timeout()):
            steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertEqual(steps[CHECK_TCP].result.status, SourceCheckStatus.FAILED)
        self.assertEqual(steps[CHECK_TCP].result.category, "TCP_TIMEOUT")

    def test_unimplemented_endpoint_still_runs_an_implemented_source_check(self):
        # get_source_endpoint stays the base default (None); the plugin only
        # implements check_source
        self.with_check_source(SourceCheckResult(status=SourceCheckStatus.OK))

        steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertNotIn(CHECK_DNS, steps)
        self.assertNotIn(CHECK_TCP, steps)
        self.assertEqual(steps[CHECK_SOURCE].result.status, SourceCheckStatus.OK)

    def test_malformed_check_source_return_degrades_to_malformed(self):
        self.with_check_source({"ok": True})

        steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertEqual(steps[CHECK_SOURCE].result.status, SourceCheckStatus.MALFORMED)

    def test_a_raising_check_source_reports_failed_not_a_crash(self):
        def boom():
            raise RuntimeError("decoder exploded")

        self.connection.check_source = boom

        steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertEqual(steps[CHECK_SOURCE].result.status, SourceCheckStatus.FAILED)
        self.assertIn("decoder exploded", steps[CHECK_SOURCE].result.message)

    def test_base_connection_with_nothing_implemented_reports_unsupported(self):
        steps = self.steps_by_id(run_source_probe(self.connection))

        self.assertEqual(set(steps), {CHECK_SOURCE})
        self.assertEqual(steps[CHECK_SOURCE].result.status, SourceCheckStatus.UNSUPPORTED)

    def test_probe_is_bounded_by_wall_clock(self):
        import time

        def slow():
            time.sleep(0.5)
            return SourceCheckResult(status=SourceCheckStatus.OK)

        self.connection.check_source = slow

        steps = self.steps_by_id(run_source_probe(self.connection, timeout_seconds=0.05))

        self.assertEqual(steps[CHECK_SOURCE].result.status, SourceCheckStatus.FAILED)
        self.assertIn("did not complete", steps[CHECK_SOURCE].result.message)
