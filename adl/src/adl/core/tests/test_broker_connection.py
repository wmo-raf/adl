"""
The bounds themselves. Every other broker caller is tested against its own
behaviour; this module pins the numbers those callers inherit, so a silent
loss of a timeout — the actual bug in #166 — fails here rather than as a
hung request in production.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from adl.core.broker_connection import (
    BROKER_CONNECT_TIMEOUT_SECONDS,
    BROKER_SOCKET_TIMEOUT_SECONDS,
    INSPECT_TIMEOUT_SECONDS,
    bounded_broker_connection,
    bounded_inspect,
)


@override_settings(CELERY_BROKER_URL="redis://broker-under-test:6379/0")
class BoundedBrokerConnectionTests(SimpleTestCase):
    def build(self):
        with patch("adl.core.broker_connection.Connection") as connection_cls:
            bounded_broker_connection()
        return connection_cls.call_args

    def test_connects_to_the_configured_broker(self):
        args, _kwargs = self.build()
        self.assertEqual(args, ("redis://broker-under-test:6379/0",))

    def test_bounds_the_connect_attempt(self):
        _args, kwargs = self.build()
        self.assertEqual(kwargs["connect_timeout"], BROKER_CONNECT_TIMEOUT_SECONDS)
        self.assertEqual(
            kwargs["transport_options"]["socket_connect_timeout"],
            BROKER_CONNECT_TIMEOUT_SECONDS,
        )

    def test_bounds_an_established_but_silent_socket(self):
        # The blackholed-broker case: the TCP connect succeeds and then
        # nothing ever comes back. Without this the caller blocks for minutes
        _args, kwargs = self.build()
        self.assertEqual(
            kwargs["transport_options"]["socket_timeout"],
            BROKER_SOCKET_TIMEOUT_SECONDS,
        )

    def test_does_not_retry(self):
        # Retries are what turn a 4 s connection timeout into ~6 s of backoff
        _args, kwargs = self.build()
        self.assertEqual(kwargs["transport_options"]["max_retries"], 0)
        self.assertFalse(kwargs["transport_options"]["retry_on_timeout"])

    def test_every_bound_is_at_most_a_couple_of_seconds(self):
        self.assertLessEqual(BROKER_CONNECT_TIMEOUT_SECONDS, 2.0)
        self.assertLessEqual(BROKER_SOCKET_TIMEOUT_SECONDS, 2.0)
        self.assertLessEqual(INSPECT_TIMEOUT_SECONDS, 2.0)


class BoundedInspectTests(SimpleTestCase):
    def test_binds_the_inspect_to_the_given_connection_and_timeout(self):
        connection = MagicMock()
        with patch("adl.core.broker_connection.app") as app_mock:
            inspect = bounded_inspect(connection)

        app_mock.control.inspect.assert_called_once_with(
            timeout=INSPECT_TIMEOUT_SECONDS, connection=connection
        )
        self.assertIs(inspect, app_mock.control.inspect.return_value)

    def test_never_passes_a_limit(self):
        # limit truncates silently and returns only the first worker's reply,
        # so on a scaled deployment it hides whole workers. Correctness over
        # the second — this seam does not offer the knob at all
        connection = MagicMock()
        with patch("adl.core.broker_connection.app") as app_mock:
            bounded_inspect(connection)

        self.assertNotIn("limit", app_mock.control.inspect.call_args.kwargs)

    def test_callers_can_wait_longer_for_a_slow_fleet(self):
        connection = MagicMock()
        with patch("adl.core.broker_connection.app") as app_mock:
            bounded_inspect(connection, timeout=2.0)

        self.assertEqual(app_mock.control.inspect.call_args.kwargs["timeout"], 2.0)
