"""Integrity-bound continuity checkpoints for the read-only Kraken trade journal.

The checkpoint is a collector assertion bound to the exact JSONL bytes. It is
not a cryptographic signature or proof against a malicious local file editor.
"""
import hashlib
import json
import math
import os
import tempfile

from kraken_order_flow import _trade_event_timestamp_ns


SOURCE = "kraken_spot_trade_feed_adapter"


def inspect_trade_journal(path):
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise ValueError("journal path must be non-empty")
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("journal must be non-empty and end with a complete line")
    first_id = last_id = None
    symbol = None
    count = 0
    last_timestamp_ns = None
    for line_number, raw_line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid journal JSON at line {line_number}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"journal line {line_number} must be an object")
        trade_id = event.get("trade_id")
        if isinstance(trade_id, bool) or not str(trade_id).isdigit() or int(trade_id) <= 0:
            raise ValueError(f"invalid journal trade ID at line {line_number}")
        trade_id = int(trade_id)
        if last_id is not None and trade_id != last_id + 1:
            raise ValueError(f"journal trade ID gap at line {line_number}")
        current_symbol = event.get("symbol")
        if not isinstance(current_symbol, str) or not current_symbol.strip():
            raise ValueError(f"invalid journal symbol at line {line_number}")
        current_symbol = current_symbol.strip()
        if symbol is None:
            symbol = current_symbol
            first_id = trade_id
        elif current_symbol != symbol:
            raise ValueError("journal contains mixed symbols")
        timestamp_ns = _trade_event_timestamp_ns(event.get("timestamp"))
        if last_timestamp_ns is not None and timestamp_ns < last_timestamp_ns:
            raise ValueError(f"journal timestamp moved backwards at line {line_number}")
        last_timestamp_ns = timestamp_ns
        if isinstance(event.get("price"), bool) or isinstance(event.get("qty"), bool):
            raise ValueError(f"invalid journal price or quantity at line {line_number}")
        try:
            price = float(event.get("price"))
            qty = float(event.get("qty"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"invalid journal price or quantity at line {line_number}") from exc
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"invalid journal price at line {line_number}")
        if not math.isfinite(qty) or qty <= 0:
            raise ValueError(f"invalid journal quantity at line {line_number}")
        if event.get("side") not in ("buy", "sell"):
            raise ValueError(f"invalid journal side at line {line_number}")
        last_id = trade_id
        count += 1
    return {
        "symbol": symbol,
        "first_trade_id": first_id,
        "last_trade_id": last_id,
        "trade_count": count,
        "journal_size_bytes": len(raw),
        "journal_sha256": hashlib.sha256(raw).hexdigest(),
    }


def build_continuity_checkpoint(path, symbol, expected_last_trade_id):
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("checkpoint symbol must be non-empty")
    if isinstance(expected_last_trade_id, bool) or not isinstance(expected_last_trade_id, int) or expected_last_trade_id <= 0:
        raise ValueError("expected_last_trade_id must be a positive integer")
    metadata = inspect_trade_journal(path)
    if metadata["symbol"] != symbol:
        raise ValueError("journal symbol does not match collector")
    if metadata["last_trade_id"] != expected_last_trade_id:
        raise ValueError("journal last trade ID does not match collector state")
    return {
        "version": 1,
        "source": SOURCE,
        "feed_continuity_verified": True,
        **metadata,
    }


def validate_continuity_checkpoint(checkpoint, path, symbol, expected_last_trade_id=None):
    if not isinstance(checkpoint, dict):
        raise ValueError("continuity checkpoint must be an object")
    if (type(checkpoint.get("version")) is not int or checkpoint.get("version") != 1
            or checkpoint.get("source") != SOURCE):
        raise ValueError("continuity checkpoint source or version is not trusted")
    if checkpoint.get("feed_continuity_verified") is not True:
        raise ValueError("continuity checkpoint is not verified")
    metadata = inspect_trade_journal(path)
    integer_fields = (
        "first_trade_id", "last_trade_id", "trade_count", "journal_size_bytes"
    )
    for field in integer_fields:
        value = checkpoint.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"continuity checkpoint {field} is invalid")
    if not isinstance(checkpoint.get("symbol"), str):
        raise ValueError("continuity checkpoint symbol is invalid")
    if not isinstance(checkpoint.get("journal_sha256"), str):
        raise ValueError("continuity checkpoint journal_sha256 is invalid")
    for field in ("symbol", *integer_fields, "journal_sha256"):
        if checkpoint.get(field) != metadata[field]:
            label = "last trade ID" if field == "last_trade_id" else field
            raise ValueError(f"continuity checkpoint {label} does not match journal")
    if metadata["symbol"] != symbol:
        raise ValueError("continuity checkpoint symbol does not match collector")
    if expected_last_trade_id is not None and metadata["last_trade_id"] != expected_last_trade_id:
        raise ValueError("continuity checkpoint last trade ID does not match collector state")
    return metadata


def load_continuity_checkpoint(path):
    with open(path, "r", encoding="utf-8") as handle:
        checkpoint = json.load(handle)
    if not isinstance(checkpoint, dict):
        raise ValueError("continuity checkpoint must be a JSON object")
    return checkpoint


def save_continuity_checkpoint_atomic(path, checkpoint):
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise ValueError("checkpoint path must be non-empty")
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be an object")
    target = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".whj-cvd-checkpoint-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(checkpoint, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        try:
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
