"""
Tests for the read-time classification fallback: ordered, first-match text
rules with binary confidence, run only over rows the write-time contract did
not stamp. The layer belongs to the rule, not the category — an ambiguous
message declines rather than guesses — and every outcome carries the rule's
normalised text, never the raw message.
"""

from django.test import SimpleTestCase

from adl.core.classification import FAILURE_CATEGORIES
from adl.monitoring.classification import (
    READ_TIME_RULES,
    category_message,
    classify_failure_text,
)


class ReadTimeRuleTableTests(SimpleTestCase):
    def test_every_rule_draws_from_the_closed_category_vocabulary(self):
        for rule in READ_TIME_RULES:
            self.assertIn(rule.category, FAILURE_CATEGORIES, rule.needle)

    def test_every_rule_layer_is_external_or_declined(self):
        for rule in READ_TIME_RULES:
            self.assertIn(rule.layer, (4, 5, None), rule.needle)


class ClassifyFailureTextTests(SimpleTestCase):
    def test_auth_failure_text_classifies_to_the_source_layer(self):
        outcome = classify_failure_text("530 Login authentication failed")

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.category, "AUTH_FAILED")
        self.assertEqual(outcome.layer, 5)

    def test_dns_failure_text_classifies_to_the_network_layer(self):
        outcome = classify_failure_text(
            "[Errno -2] Name or service not known"
        )

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.category, "DNS_FAILURE")
        self.assertEqual(outcome.layer, 4)

    def test_connection_refused_classifies_to_the_network_layer(self):
        outcome = classify_failure_text("[Errno 111] Connection refused")

        self.assertEqual(outcome.category, "TCP_REFUSED")
        self.assertEqual(outcome.layer, 4)

    def test_timeout_text_claims_the_category_but_declines_the_layer(self):
        # A plugin that collapses a connect timeout and a read timeout into
        # one string: the text rule must decline where a type rule could
        # claim — a rule with no layer stays layer-6 detail
        outcome = classify_failure_text("Connection timed out")

        self.assertEqual(outcome.category, "TCP_TIMEOUT")
        self.assertIsNone(outcome.layer)

    def test_missing_path_classifies_to_the_source_layer(self):
        outcome = classify_failure_text(
            "550 /data/observations: No such file or directory"
        )

        self.assertEqual(outcome.category, "PATH_NOT_FOUND")
        self.assertEqual(outcome.layer, 5)

    def test_genuinely_ambiguous_text_yields_no_classification(self):
        # The headline must never confidently name the wrong layer
        self.assertIsNone(classify_failure_text("Something went wrong"))
        self.assertIsNone(classify_failure_text(""))
        self.assertIsNone(classify_failure_text(None))

    def test_matching_is_case_insensitive(self):
        outcome = classify_failure_text("CONNECTION REFUSED by remote host")

        self.assertEqual(outcome.category, "TCP_REFUSED")

    def test_first_match_wins_over_later_rules(self):
        # Both an auth needle and a timeout needle appear; the earlier,
        # more specific rule claims the row
        outcome = classify_failure_text(
            "Login incorrect (control connection timed out)"
        )

        self.assertEqual(outcome.category, "AUTH_FAILED")

    def test_outcome_carries_normalised_text_never_the_raw_message(self):
        raw = "530 Login incorrect: user 'nma-user' password 'hunter2'"

        outcome = classify_failure_text(raw)

        self.assertNotIn("hunter2", outcome.message)
        self.assertEqual(outcome.message, category_message("AUTH_FAILED"))


class CategoryMessageTests(SimpleTestCase):
    def test_every_category_has_a_normalised_message(self):
        for category in FAILURE_CATEGORIES:
            self.assertTrue(category_message(category), category)
