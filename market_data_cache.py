"""Incremental validated BTC/USD hourly candle cache; research loader remains unchanged."""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from historical_research import INTERVAL_MS, fetch_page, load_two_year_candles

CACHE_SCHEMA_VERSION = 1
CACHE_MARKET = "BTC-USD"
CACHE_GRANULARITY_SECONDS = 3600
DEFAULT_CACHE_PATH = Path("state/market_data/coinbase_btcusd_1h.json")
DEFAULT_BOOTSTRAP_DAYS = 400
DEFAULT_OVERLAP_HOURS = 8
MAX_REPAIR_GAP_HOURS = 6


def _now_ms(now=None):
    value = now or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    return int(value.timestamp() * 1000)


def _validate_candle(row):
    if not isinstance(row, dict):
        raise ValueError("Market candle must be an object")
    timestamp = row.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError("Market candle timestamp must be an integer")
    if timestamp < 0 or timestamp % INTERVAL_MS:
        raise ValueError("Market candle timestamp is not hour-aligned")
    values = []
    for key in ("open", "high", "low", "close", "volume"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Invalid market candle " + key)
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Non-finite market candle " + key)
        values.append(value)
    op, high, low, close, volume = values
    if min(op, high, low, close) <= 0 or volume < 0:
        raise ValueError("Non-positive price or negative volume")
    if high < max(op, close, low) or low > min(op, close, high):
        raise ValueError("Impossible OHLC relationship")
    imputed = row.get("imputed", False)
    if not isinstance(imputed, bool):
        raise ValueError("Market candle imputed flag must be boolean")
    return {
        "timestamp": timestamp, "open": op, "high": high, "low": low,
        "close": close, "volume": volume, "imputed": imputed,
    }


def _repair_and_validate(rows, cutoff_ms):
    unique = {}
    for raw in rows:
        candle = _validate_candle(raw)
        if candle["timestamp"] + INTERVAL_MS > cutoff_ms:
            continue
        old = unique.get(candle["timestamp"])
        if old is None or (old["imputed"] and not candle["imputed"]):
            unique[candle["timestamp"]] = candle
    ordered = [unique[key] for key in sorted(unique)]
    if not ordered:
        raise ValueError("No closed hourly candles in market-data cache")
    result = []
    for current in ordered:
        if result:
            previous = result[-1]
            delta = current["timestamp"] - previous["timestamp"]
            if delta <= 0 or delta % INTERVAL_MS:
                raise ValueError("Market candle timestamps are not hourly aligned")
            missing = delta // INTERVAL_MS - 1
            if missing > MAX_REPAIR_GAP_HOURS:
                raise ValueError("Market data gap exceeds six-hour repair limit")
            for offset in range(1, missing + 1):
                flat = previous["close"]
                result.append({
                    "timestamp": previous["timestamp"] + offset * INTERVAL_MS,
                    "open": flat, "high": flat, "low": flat, "close": flat,
                    "volume": 0.0, "imputed": True,
                })
        result.append(current)
    if result:
        result[0]["_imputed_hour_count"] = sum(bool(row["imputed"]) for row in result)
    return result


def _read_cache(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Market-data cache unreadable; refusing silent bootstrap") from exc
    if not isinstance(payload, dict):
        raise ValueError("Market-data cache root must be an object")
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise ValueError("Unsupported market-data cache schema")
    if payload.get("market") != CACHE_MARKET:
        raise ValueError("Market-data cache market mismatch")
    if payload.get("granularity_seconds") != CACHE_GRANULARITY_SECONDS:
        raise ValueError("Market-data cache granularity mismatch")
    candles = payload.get("candles")
    if not isinstance(candles, list) or not candles:
        raise ValueError("Market-data cache candles missing or empty")
    return candles


def _write_cache(path, candles, fetched_at):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "market": CACHE_MARKET,
        "granularity_seconds": CACHE_GRANULARITY_SECONDS,
        "fetched_at_utc": fetched_at,
        "candle_count": len(candles),
        "imputed_hour_count": sum(bool(row.get("imputed")) for row in candles),
        "candles": candles,
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(target.parent),
            prefix="." + target.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _fetch_incremental(start_ms, end_ms):
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        page_end = min(cursor + 299 * INTERVAL_MS, end_ms)
        rows.extend(fetch_page(cursor, page_end))
        next_cursor = page_end + INTERVAL_MS
        if next_cursor <= cursor:
            raise ValueError("Incremental pagination did not advance")
        cursor = next_cursor
        if cursor < end_ms:
            time.sleep(0.2)
    return rows


def update_market_data_cache(
    cache_path=DEFAULT_CACHE_PATH, now=None,
    bootstrap_days=DEFAULT_BOOTSTRAP_DAYS, overlap_hours=DEFAULT_OVERLAP_HOURS,
):
    """Bootstrap once; then fetch only the recent overlap and newly closed candles."""
    if isinstance(bootstrap_days, bool) or not isinstance(bootstrap_days, int) or bootstrap_days < 30:
        raise ValueError("bootstrap_days must be an integer of at least 30")
    if isinstance(overlap_hours, bool) or not isinstance(overlap_hours, int) or not 1 <= overlap_hours <= 48:
        raise ValueError("overlap_hours must be an integer from 1 to 48")
    now_ms = _now_ms(now)
    cutoff = now_ms - now_ms % INTERVAL_MS
    target = Path(cache_path)
    if not target.exists():
        candles = load_two_year_candles(
            days=bootstrap_days,
            now=now or datetime.fromtimestamp(now_ms / 1000, timezone.utc),
        )
    else:
        cached = _repair_and_validate(_read_cache(target), cutoff)
        start_ms = max(0, cached[-1]["timestamp"] - overlap_hours * INTERVAL_MS)
        fetched = _fetch_incremental(start_ms, cutoff)
        additions = [{
            "timestamp": int(row[0]), "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
            "imputed": False,
        } for row in fetched]
        candles = cached + additions
    candles = _repair_and_validate(candles, cutoff)
    earliest = cutoff - bootstrap_days * 24 * INTERVAL_MS
    candles = [row for row in candles if row["timestamp"] >= earliest]
    if len(candles) < 1000:
        raise ValueError("Insufficient retained hourly history in market-data cache")
    candles[0]["_imputed_hour_count"] = sum(bool(row.get("imputed")) for row in candles)
    _write_cache(target, candles, datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat())
    return candles
