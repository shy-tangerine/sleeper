import base64
import struct
import unittest
import zlib
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "daemon"))
from redaction import sanitize

class RedactionContract(unittest.TestCase):
    def test_nested_secrets_and_shapes(self):
        raw = "ghp_abcdefghijklmnopqrstuvwxyz123456"  # pragma: allowlist secret -- synthetic fixture
        out = sanitize({"Authorization": "Bearer abc", "nested": [{"api-key": raw}], "url": "https://x/?token=abc"})
        self.assertNotIn(raw, repr(out)); self.assertNotIn("abc", repr(out)); self.assertEqual(out["nested"][0]["api-key"], "[REDACTED]")
    def test_safe_prose_survives(self):
        self.assertEqual(sanitize({"message": "please read the token guide"})["message"], "please read the token guide")
    def test_cycles_and_depth(self):
        x = {}; x["self"] = x
        self.assertEqual(sanitize(x)["self"], "[REDACTED]")
    def test_headers_urls_and_key_aliases(self):
        raw = "sk-abcdefghijklmnopqrstuvwxyz123456"  # pragma: allowlist secret -- synthetic fixture
        out = sanitize({"Set-Cookie": "sid=secret", "api key": raw,
                        "url": "https://u:p@example.test/?access_token=abc#token=def",
                        "Authorization": "Bearer abc"})
        self.assertNotIn("secret", repr(out)); self.assertNotIn(raw, repr(out)); self.assertNotIn("u:p@", repr(out))
    def test_bytes_and_benign_identifiers(self):
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", repr(sanitize(b"sk-abcdefghijklmnopqrstuvwxyz123456")))  # pragma: allowlist secret -- synthetic fixture
        self.assertEqual(sanitize({"description": "tokenize ordinary identifiers"})["description"], "tokenize ordinary identifiers")
    def test_standalone_basic_pem_and_bytes(self):
        self.assertNotIn("dXNlcjpwYXNz", repr(sanitize("Basic dXNlcjpwYXNz")))
        pem = "-----BEGIN PRIVATE KEY-----\nSECRET-BODY\n-----END PRIVATE KEY-----"  # pragma: allowlist secret -- synthetic fixture
        self.assertNotIn("SECRET-BODY", repr(sanitize(pem)))
        self.assertEqual(sanitize(b"arbitrary secret bytes"), "[REDACTED]")
    def test_header_aliases_and_benign_scheme_prose(self):
        values = {"X-API-Key": "alpha-secret-value", "x-access-token": "access-secret-value",
            "Client-Secret": "client-secret-value", "ApiKey": "another-secret-value",  # pragma: allowlist secret -- synthetic fixtures
            "accessToken": "token-secret-value", "privateKey": "key-secret-value",  # pragma: allowlist secret -- synthetic fixtures
                  "Set-Cookie": "sid=private-secret"}
        out = repr(sanitize(values))
        for value in values.values(): self.assertNotIn(value, out)
        self.assertEqual(sanitize("Basic tutorial"), "Basic tutorial")
        self.assertEqual(sanitize("bearer token guide"), "bearer token guide")
    def test_detect_secrets_entropy_candidates(self):
        hex_value = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret -- synthetic fixture
        base64_value = "YWJjREVGMDEyMzQ1Njc4OWFiY2RFRkdISUpLTE1OT1BRUlNUVVZXWFla"  # pragma: allowlist secret -- synthetic fixture
        self.assertNotIn(hex_value, sanitize('checksum = "' + hex_value + '"'))
        self.assertNotIn(base64_value, sanitize('opaque = "' + base64_value + '"'))
        self.assertEqual(sanitize("this is ordinary prose about checksums"), "this is ordinary prose about checksums")

    def test_oversized_strings_are_redacted_before_truncation(self):
        prefix_secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
        suffix_secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
        prefix_value = prefix_secret + ("x" * 70000)
        suffix_value = ("x" * 70000) + suffix_secret

        self.assertNotIn(prefix_secret, sanitize(prefix_value))
        self.assertNotIn(suffix_secret, sanitize(suffix_value))

    def test_large_png_artifact_is_preserved_but_other_data_urls_are_redacted(self):
        # A valid, compressible RGB PNG well beyond ordinary text truncation.
        width, height = 256, 256
        raw = b"".join(b"\0" + bytes((i % 256 for i in range(width * 3))) for _ in range(height))
        chunk = lambda kind, value: struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 0)) + chunk(b"IEND", b"")
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        self.assertGreater(len(data_url), 65536)
        self.assertEqual(sanitize(data_url), "[REDACTED]")
        self.assertEqual(sanitize(data_url, allow_image_artifacts=True), data_url)
        self.assertEqual(sanitize("data:text/plain;base64," + "A" * 70000), "[REDACTED]")
        fake_image = "data:image/png;base64," + base64.b64encode(b"secret-material-not-a-png").decode()
        self.assertEqual(sanitize(fake_image), "[REDACTED]")

if __name__ == "__main__": unittest.main()
