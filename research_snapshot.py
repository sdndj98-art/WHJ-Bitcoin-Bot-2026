"""Deterministic public-market research dataset snapshots.

Snapshots preserve the exact canonical JSON bytes used for dataset hashing.
They contain market-data rows only; no account, ledger, credential, or order data.
"""
import gzip
import hashlib
import json


def canonical_json_bytes(value):
    """Serialize JSON deterministically and reject non-finite numeric values."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_bytes(payload):
    """Return the SHA-256 hex digest of an immutable byte payload."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")
    return hashlib.sha256(bytes(payload)).hexdigest()


def gzip_snapshot_bytes(payload):
    """Return a deterministic gzip archive of canonical JSON bytes."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")
    return gzip.compress(bytes(payload), compresslevel=9, mtime=0)
