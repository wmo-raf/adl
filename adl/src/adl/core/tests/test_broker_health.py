from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from kombu.exceptions import ChannelError

from adl.core.broker import (
    INGESTION_QUEUE_NAME,
    IngestionQueueHealth,
    get_ingestion_queue_health,
    running_task_stuck_after_seconds,
    running_task_warn_after_seconds,
)
from .factories import NetworkConnectionFactory


def make_connection_mock(message_count=0, declare_side_effect=None):
    """A kombu ``Connection`` stand-in whose passive declare is scriptable."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    declare = conn.default_channel.queue_declare
    if declare_side_effect is not None:
        declare.side_effect = declare_side_effect
    else:
        declare.return_value = MagicMock(message_count=message_count)
    return conn


class GetIngestionQueueHealthTests(SimpleTestCase):
    """
    All layer-2 broker interaction sits behind this one function; these tests
    substitute the kombu connection and the inspect API — never a live broker.
    """

    def call(self, conn, active_queues=None, active=None, inspect_side_effect=None):
        inspect = MagicMock()
        if inspect_side_effect is not None:
            inspect.active_queues.side_effect = inspect_side_effect
            inspect.active.side_effect = inspect_side_effect
        else:
            inspect.active_queues.return_value = active_queues
            inspect.active.return_value = active

        with patch("adl.core.broker.Connection", return_value=conn), \
                patch("adl.core.broker.app") as app_mock:
            app_mock.control.inspect.return_value = inspect
            return get_ingestion_queue_health()

    def test_healthy_broker_reports_all_three_signals(self):
        result = self.call(
            make_connection_mock(message_count=5),
            active_queues={"adl-worker@host": [{"name": INGESTION_QUEUE_NAME}]},
            active={
                "adl-worker@host": [
                    {
                        "id": "abc",
                        "name": "adl.core.tasks.process_station_link_batch",
                        "args": [1, [2, 3]],
                        "time_start": 1000.0,
                    }
                ]
            },
        )

        self.assertIsInstance(result, IngestionQueueHealth)
        self.assertEqual(result.queue_depth, 5)
        self.assertTrue(result.worker_consuming)
        self.assertEqual(len(result.running_tasks), 1)

    def test_empty_queue_reports_depth_zero_not_unknown(self):
        # On Redis an empty queue has no key, so the passive declare raises
        # ChannelError NOT_FOUND — a healthy idle system, not an unobservable
        # one. Mirrors kombu's virtual-transport raise: reply text and a
        # string '404' reply code.
        error = ChannelError(
            "NOT_FOUND - no queue 'adl' in vhost '/'",
            (50, 10), "Channel.queue_declare", "404",
        )
        result = self.call(
            make_connection_mock(declare_side_effect=error),
            active_queues={"adl-worker@host": [{"name": INGESTION_QUEUE_NAME}]},
            active={"adl-worker@host": []},
        )

        self.assertEqual(result.queue_depth, 0)

    def test_non_not_found_channel_error_is_unknown_not_empty(self):
        # Only NOT_FOUND means "no key, so empty". Any other channel error
        # must not manufacture a false healthy depth of zero.
        error = ChannelError(
            "ACCESS_REFUSED - access to queue 'adl' refused",
            (50, 10), "Channel.queue_declare", 403,
        )
        result = self.call(
            make_connection_mock(declare_side_effect=error),
            active_queues={"adl-worker@host": [{"name": INGESTION_QUEUE_NAME}]},
            active={"adl-worker@host": []},
        )

        self.assertIsNone(result.queue_depth)

    def test_depth_unknown_when_declare_fails_unexpectedly(self):
        result = self.call(
            make_connection_mock(declare_side_effect=OSError("connection reset")),
            active_queues={"adl-worker@host": [{"name": INGESTION_QUEUE_NAME}]},
            active={"adl-worker@host": []},
        )

        self.assertIsNone(result.queue_depth)
        # The other signals are independently observable.
        self.assertTrue(result.worker_consuming)
        self.assertEqual(result.running_tasks, ())

    def test_no_inspect_reply_is_unknown_not_down(self):
        result = self.call(
            make_connection_mock(message_count=2),
            active_queues=None,
            active=None,
        )

        self.assertEqual(result.queue_depth, 2)
        self.assertIsNone(result.worker_consuming)
        self.assertIsNone(result.running_tasks)

    def test_worker_replying_but_not_bound_to_ingestion_queue_is_false(self):
        result = self.call(
            make_connection_mock(),
            active_queues={"dispatch-worker@host": [{"name": "dispatch"}]},
            active={"dispatch-worker@host": []},
        )

        self.assertIs(result.worker_consuming, False)

    def test_idle_worker_reports_no_running_tasks_not_unknown(self):
        # Idle is {'worker': []}, never {} — a reply with no tasks means
        # "nothing running", which is different from no reply at all.
        result = self.call(
            make_connection_mock(),
            active_queues={"adl-worker@host": [{"name": INGESTION_QUEUE_NAME}]},
            active={"adl-worker@host": []},
        )

        self.assertEqual(result.running_tasks, ())

    def test_non_ingestion_tasks_are_filtered_out(self):
        result = self.call(
            make_connection_mock(),
            active_queues={"w@host": [{"name": INGESTION_QUEUE_NAME}]},
            active={
                "w@host": [
                    {
                        "id": "d1",
                        "name": "adl.core.tasks.dispatch_station",
                        "args": [1, 2],
                        "time_start": 1000.0,
                    },
                    {
                        "id": "b1",
                        "name": "adl.core.tasks.process_station_link_batch",
                        "args": [1, [2]],
                        "time_start": 1000.0,
                    },
                    {
                        "id": "c1",
                        "name": "adl.core.tasks.run_network_plugin",
                        "args": [1],
                        "time_start": 1500.0,
                    },
                ]
            },
        )

        self.assertEqual(
            sorted(task.task_id for task in result.running_tasks), ["b1", "c1"]
        )

    def test_running_task_age_is_wall_clock_since_time_start(self):
        with patch("adl.core.broker.time.time", return_value=1600.0):
            result = self.call(
                make_connection_mock(),
                active_queues={"w@host": [{"name": INGESTION_QUEUE_NAME}]},
                active={
                    "w@host": [
                        {
                            "id": "b1",
                            "name": "adl.core.tasks.process_station_link_batch",
                            "args": [1, [2, 3]],
                            "time_start": 1000.0,
                        }
                    ]
                },
            )

        task = result.running_tasks[0]
        self.assertEqual(task.age_seconds, 600.0)
        self.assertEqual(task.args, (1, (2, 3)))

    def test_task_without_time_start_has_unknown_age(self):
        result = self.call(
            make_connection_mock(),
            active_queues={"w@host": [{"name": INGESTION_QUEUE_NAME}]},
            active={
                "w@host": [
                    {
                        "id": "b1",
                        "name": "adl.core.tasks.process_station_link_batch",
                        "args": [1, [2]],
                    }
                ]
            },
        )

        self.assertIsNone(result.running_tasks[0].age_seconds)

    def test_inspect_raising_leaves_inspect_signals_unknown(self):
        result = self.call(
            make_connection_mock(message_count=3),
            inspect_side_effect=OSError("broker gone"),
        )

        self.assertEqual(result.queue_depth, 3)
        self.assertIsNone(result.worker_consuming)
        self.assertIsNone(result.running_tasks)

    def test_unreachable_broker_never_raises_and_reports_all_unknown(self):
        conn = MagicMock()
        conn.__enter__.side_effect = OSError("connection refused")

        with patch("adl.core.broker.Connection", return_value=conn), \
                patch("adl.core.broker.app") as app_mock:
            app_mock.control.inspect.side_effect = OSError("no broker")
            result = get_ingestion_queue_health()

        self.assertIsNone(result.queue_depth)
        self.assertIsNone(result.worker_consuming)
        self.assertIsNone(result.running_tasks)


class RunningTaskThresholdTests(TestCase):
    """Thresholds derive from the connection's own interval, never fixed seconds."""

    def test_five_minutely_connection(self):
        connection = NetworkConnectionFactory(plugin_processing_interval=5)
        self.assertEqual(running_task_warn_after_seconds(connection), 300)
        self.assertEqual(running_task_stuck_after_seconds(connection), 900)

    def test_daily_connection(self):
        connection = NetworkConnectionFactory(plugin_processing_interval=1440)
        self.assertEqual(running_task_warn_after_seconds(connection), 86400)
        self.assertEqual(running_task_stuck_after_seconds(connection), 259200)
