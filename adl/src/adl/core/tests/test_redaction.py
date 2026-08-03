from django.test import SimpleTestCase

from adl.core.redaction import redact_json, redact_secrets


class RedactQueryStringTests(SimpleTestCase):
    def test_redacts_token_query_parameter_in_a_url(self):
        text = ("401 Client Error: Unauthorized for url: "
                "https://example.org/data?token=s3cr3t&station=42")
        self.assertEqual(
            redact_secrets(text),
            ("401 Client Error: Unauthorized for url: "
             "https://example.org/data?token=***&station=42"),
        )

    def test_redacts_a_first_query_parameter(self):
        self.assertEqual(
            redact_secrets("https://example.org/data?api_key=abc123&x=1"),
            "https://example.org/data?api_key=***&x=1",
        )

    def test_redacts_compound_key_names(self):
        for key in ("api_key", "apikey", "x-api-key", "client_secret",
                    "access_token", "refresh_token", "API_TOKEN", "passwd"):
            with self.subTest(key=key):
                self.assertEqual(
                    redact_secrets(f"https://e.org/?{key}=leaked&n=1"),
                    f"https://e.org/?{key}=***&n=1",
                )

    def test_keeps_non_sensitive_query_parameters(self):
        text = "https://example.org/data?station=42&start=2024-01-01"
        self.assertEqual(redact_secrets(text), text)

    def test_redacts_every_occurrence(self):
        self.assertEqual(
            redact_secrets("?token=a&x=1 and ?token=b&y=2"),
            "?token=***&x=1 and ?token=***&y=2",
        )

    def test_redacts_an_empty_valued_secret_parameter(self):
        self.assertEqual(redact_secrets("?token=&x=1"), "?token=***&x=1")


class RedactFreeTextTests(SimpleTestCase):
    def test_redacts_a_key_value_pair_outside_a_url(self):
        self.assertEqual(
            redact_secrets("connect failed (password=hunter2)"),
            "connect failed (password=***)",
        )

    def test_redacts_a_colon_separated_pair(self):
        self.assertEqual(
            redact_secrets('{"secret": "abc123"}'),
            '{"secret": ***}',
        )

    def test_redacts_a_bearer_credential(self):
        self.assertEqual(
            redact_secrets("Authorization: Bearer eyJhbGciOi.J9-x_y"),
            "Authorization: ***",
        )

    def test_redacts_a_basic_credential(self):
        self.assertEqual(
            redact_secrets("sent Basic dXNlcjpwYXNz to host"),
            "sent Basic *** to host",
        )

    def test_leaves_ordinary_prose_alone(self):
        text = "Station 42 returned no records between 10:00 and 11:00."
        self.assertEqual(redact_secrets(text), text)


class RedactUrlUserinfoTests(SimpleTestCase):
    def test_redacts_userinfo_credentials(self):
        self.assertEqual(
            redact_secrets("ftp://alice:hunter2@ftp.example.org/in/"),
            "ftp://***:***@ftp.example.org/in/",
        )

    def test_redacts_userinfo_with_an_empty_user(self):
        # The broker URL of a Redis secured with ``requirepass`` has no user
        # half. It reaches this function through kombu's connection errors,
        # so the form that carries a real deployment's password must not be
        # the one form the pattern misses.
        self.assertEqual(
            redact_secrets("Cannot connect to redis://:hunter2@adl_redis:6379/0"),
            "Cannot connect to redis://***:***@adl_redis:6379/0",
        )

    def test_leaves_a_url_without_userinfo_alone(self):
        text = "https://example.org:8443/data"
        self.assertEqual(redact_secrets(text), text)

    def test_leaves_a_port_and_path_that_resemble_userinfo_alone(self):
        # The user half went from "one or more" to "zero or more" characters;
        # a colon in a host:port or in a path must still not read as one.
        text = "Timed out reading https://example.org:8443/keys/a:b@2024"
        self.assertEqual(redact_secrets(text), text)


class RedactEdgeCaseTests(SimpleTestCase):
    def test_none_passes_through(self):
        self.assertIsNone(redact_secrets(None))

    def test_empty_string_passes_through(self):
        self.assertEqual(redact_secrets(""), "")

    def test_non_string_is_coerced(self):
        self.assertEqual(redact_secrets(ValueError("token=abc")), "token=***")


class RedactJsonTests(SimpleTestCase):
    def test_a_key_that_names_a_secret_loses_its_value(self):
        self.assertEqual(
            redact_json({"api_key": "abc123", "station": 42}),
            {"api_key": "***", "station": 42},
        )

    def test_nested_structures_are_walked(self):
        self.assertEqual(
            redact_json({"errors": [{"password": "hunter2"}, {"code": 401}]}),
            {"errors": [{"password": "***"}, {"code": 401}]},
        )

    def test_secrets_embedded_in_string_values_are_redacted(self):
        self.assertEqual(
            redact_json({"detail": "failed for url ?token=s3cr3t&x=1"}),
            {"detail": "failed for url ?token=***&x=1"},
        )

    def test_structure_and_non_string_leaves_survive(self):
        payload = {"records_sent": 12, "ok": True, "missing": None, "ids": [1, 2]}
        self.assertEqual(redact_json(payload), payload)

    def test_a_bare_string_is_redacted(self):
        self.assertEqual(redact_json("?token=abc"), "?token=***")
