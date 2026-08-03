"""
The Celery task-result surface is redacted on read.

``django_celery_results`` writes the exception text and traceback of a
re-raised task itself, so core has no write point on that row — the
monitoring API is where it has to be caught.
"""

import json

from django.test import SimpleTestCase
from django_celery_results.models import TaskResult

from adl.monitoring.serializers import TaskResultSerializer

LEAKY_URL = "https://api.example.org/data?token=s3cr3t-value&station=42"


def serialize(**kwargs):
    return TaskResultSerializer(TaskResult(**kwargs)).data


class TaskResultRedactionTests(SimpleTestCase):
    def test_traceback_is_redacted(self):
        data = serialize(
            traceback=f"Traceback (most recent call last):\n  HTTPError: 401 for url: {LEAKY_URL}"
        )

        self.assertNotIn("s3cr3t-value", data["traceback"])
        self.assertIn("token=***", data["traceback"])
        self.assertIn("Traceback", data["traceback"])

    def test_json_result_is_redacted_and_keeps_its_shape(self):
        data = serialize(
            result=json.dumps({"exc_message": [f"401 for url: {LEAKY_URL}"], "records": 0})
        )

        self.assertNotIn("s3cr3t-value", json.dumps(data["result"]))
        self.assertEqual(data["result"]["records"], 0)

    def test_non_json_result_is_still_redacted(self):
        data = serialize(result=f"401 Client Error for url: {LEAKY_URL}")

        self.assertNotIn("s3cr3t-value", data["result"])
        self.assertIn("token=***", data["result"])

    def test_absent_result_and_traceback_do_not_break_serialisation(self):
        data = serialize()

        self.assertIsNone(data["result"])
        self.assertIsNone(data["traceback"])
