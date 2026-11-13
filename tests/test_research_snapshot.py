import gzip
import unittest

from research_snapshot import canonical_json_bytes, gzip_snapshot_bytes, sha256_bytes


class ResearchSnapshotTests(unittest.TestCase):
    def test_canonical_json_is_key_order_independent(self):
        left = canonical_json_bytes({"z": 1, "a": [2, 3]})
        right = canonical_json_bytes({"a": [2, 3], "z": 1})
        self.assertEqual(left, right)
        self.assertEqual(left, b'{"a":[2,3],"z":1}')

    def test_gzip_snapshot_round_trips_and_is_deterministic(self):
        payload = canonical_json_bytes([{"close": 10.5, "timestamp": 1}])
        first = gzip_snapshot_bytes(payload)
        second = gzip_snapshot_bytes(payload)
        self.assertEqual(first, second)
        self.assertEqual(gzip.decompress(first), payload)

    def test_hash_matches_uncompressed_canonical_payload(self):
        payload = canonical_json_bytes({"rows": 3})
        self.assertEqual(
            sha256_bytes(payload),
            "2bafd4629cc04e701c66d3854982e073924fa77d4fdc31b2803184ff5a42cecc",
        )
        self.assertEqual(sha256_bytes(payload), sha256_bytes(bytearray(payload)))

    def test_non_finite_json_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})

    def test_hash_and_compression_require_bytes(self):
        for fn in (sha256_bytes, gzip_snapshot_bytes):
            with self.subTest(function=fn.__name__):
                with self.assertRaises(TypeError):
                    fn("not bytes")


if __name__ == "__main__":
    unittest.main()
