"""Synthetic inputs only; pure hashing with no Firestore or configuration reads."""
from dataclasses import asdict
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from app.domain.email import normalize_email
from app.domain.email_identity import derive_email_identity, EMAIL_IDENTITY_PURPOSE

SECRET = "synthetic-test-secret-not-an-operational-key"


class EmailIdentityTests(unittest.TestCase):
    def identity(self, email="buyer@example.com", **kwargs):
        return derive_email_identity(normalize_email(email), secret=SECRET, **kwargs)

    def test_determinism_and_case_spaces(self):
        expected = self.identity()
        for _ in range(5):
            self.assertEqual(expected, self.identity(" Buyer@EXAMPLE.COM "))

    def test_distinct_addresses_aliases_and_dots(self):
        pairs = [("buyer@example.com", "other@example.com"),
                 ("buyer@example.com", "buyer+alias@example.com"),
                 ("first.last@example.com", "firstlast@example.com")]
        for first, second in pairs:
            with self.subTest(first=first):
                self.assertNotEqual(self.identity(first).identity_id, self.identity(second).identity_id)

    def test_key_and_each_version_change_identity(self):
        base = self.identity()
        other = derive_email_identity("buyer@example.com", secret="another-synthetic-secret")
        self.assertNotEqual(base.identity_id, other.identity_id)
        for field in ("hmac_key_version", "identity_version", "normalization_version"):
            with self.subTest(field=field):
                other = self.identity(**{field: 2})
                self.assertNotEqual(base.identity_id, other.identity_id)
                self.assertEqual(getattr(other, field), 2)
        self.assertEqual((base.normalization_version, base.identity_version, base.hmac_key_version), (1, 1, 1))

    def test_invalid_secrets_controlled_and_redacted(self):
        for secret in (None, "", "   ", 42, True, b"bytes", {}, "synthetic-\ud800-secret"):
            with self.subTest(kind=type(secret).__name__):
                with self.assertRaises(ValueError) as error:
                    derive_email_identity("buyer@example.com", secret=secret)
                self.assertNotIn("buyer@example.com", str(error.exception))
                self.assertNotIn("synthetic-", str(error.exception))

    def test_invalid_versions_and_raw_addresses(self):
        for field in ("hmac_key_version", "identity_version", "normalization_version"):
            for value in (None, True, "1", 0, -1, 1.0):
                with self.assertRaises(ValueError):
                    self.identity(**{field: value})
        for email in (None, "bad", " Buyer@Example.com ", "BUYER@example.com"):
            with self.assertRaises(ValueError):
                derive_email_identity(email, secret=SECRET)

    def test_result_allowlist_and_firestore_format(self):
        result = self.identity()
        self.assertRegex(result.identity_id, r"\A[0-9a-f]{64}\Z")
        self.assertEqual(set(asdict(result)), {"identity_id", "normalization_version", "identity_version", "hmac_key_version"})
        for representation in (repr(result), str(result), str(asdict(result))):
            self.assertNotIn(SECRET, representation)
            self.assertNotIn("buyer@example.com", representation)

    def test_exact_canonical_hmac_not_plain_sha(self):
        message = json.dumps({"purpose": EMAIL_IDENTITY_PURPOSE, "identity_version": 1,
                              "normalization_version": 1, "hmac_key_version": 1,
                              "normalized_email": "buyer@example.com"},
                             sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        expected = hmac.new(SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()
        self.assertEqual(self.identity().identity_id, expected)
        self.assertNotEqual(expected, hashlib.sha256(message).hexdigest())

    def test_no_environment_logging_or_firestore(self):
        with patch('app.services.firebase_service.get_firestore_client', side_effect=AssertionError("No Firestore")), \
             patch('os.getenv', side_effect=AssertionError("No env")), \
             patch('logging.Logger._log', side_effect=AssertionError("No logging")), \
             patch('builtins.print', side_effect=AssertionError("No output")):
            self.identity()
