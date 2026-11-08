"""Independent Bitstamp BTCUSD validation of the fixed EMA/ADX research rules.

Public market data only. This module never reads or writes paper-account state
and never creates orders.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ema_adx_lab import run_ema_adx_filter_lab

INTERVAL_MS = 60 * 60 * 1000
DAYS = 3000
BASE_URL = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"


def normalize_bitstamp_ohlc(payload):
    """Convert Bitstamp OHLC response objects to validated hourly bars."""
    if not isinstance(payload, dict):
        raise ValueError("Bitstamp OHLC payload must be an object")
    data = payload.get("data")
    rows = data.get("ohlc") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Bitstamp response does not contain an OHLC list")
    normalized = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("Malformed Bitstamp OHLC row")
        try:
            timestamp = int(item["timestamp"]) * 1000
            open_price, high, low, close, volume = (
                float(item[key]) for key in ("open", "high", "low", "close", "volume")
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Malformed or non-numeric Bitstamp OHLC field") from exc
        values = (open_price, high, low, close, volume)
        if timestamp < 0 or timestamp % INTERVAL_MS:
            raise ValueError("Bitstamp candle timestamp is not hourly aligned")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite Bitstamp OHLCV value")
        if min(open_price, high, low, close) <= 0 or volume < 0:
            raise ValueError("Invalid Bitstamp OHLCV price or volume")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Impossible Bitstamp OHLC relationship")
        normalized.append({
            "timestamp": timestamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "imputed": False,
        })
    normalized.sort(key=lambda row: row["timestamp"])
    for previous, current in zip(normalized, normalized[1:]):
        if current["timestamp"] == previous["timestamp"]:
            raise ValueError("Duplicate Bitstamp hourly candle")
        if current["timestamp"] - previous["timestamp"] != INTERVAL_MS:
            raise ValueError("Bitstamp hourly data contains a gap")
    return normalized


def _request_bitstamp_page(end_seconds):
    params = urllib.parse.urlencode({
        "step": 3600,
        "limit": 1000,
        "end": end_seconds,
        "exclude_current_candle": "true",
    })
    request = urllib.request.Request(
        BASE_URL + "?" + params,
        headers={
            "User-Agent": "WHJ-Independent-Research/1.0",
            "Accept": "application/json",
        },
    )
    last_error = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                raise ValueError("Bitstamp returned an unexpected OHLC payload")
            return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError("Unable to download Bitstamp BTCUSD candles: " + str(last_error))


def fetch_bitstamp_hourly_candles(days=DAYS, now=None):
    if isinstance(days, bool) or not isinstance(days, int) or days < 365:
        raise ValueError("Research history must be an integer of at least 365 days")
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    cutoff_ms = now_ms - (now_ms % INTERVAL_MS)
    start_ms = ((now_ms - days * 24 * INTERVAL_MS) // INTERVAL_MS) * INTERVAL_MS
    cursor_end_ms = cutoff_ms - 1
    rows = []
    while cursor_end_ms >= start_ms:
        page = normalize_bitstamp_ohlc(_request_bitstamp_page(cursor_end_ms // 1000))
        page_rows = [
            row for row in page
            if start_ms <= row["timestamp"]
            and row["timestamp"] + INTERVAL_MS <= cutoff_ms
            and row["timestamp"] <= cursor_end_ms
        ]
        if not page_rows:
            break
        rows.extend(page_rows)
        oldest_ms = page_rows[0]["timestamp"]
        if oldest_ms <= start_ms:
            break
        next_end_ms = oldest_ms - 1
        if next_end_ms >= cursor_end_ms:
            raise ValueError("Bitstamp backward pagination did not advance")
        cursor_end_ms = next_end_ms
        time.sleep(0.1)

    rows.sort(key=lambda row: row["timestamp"])
    unique = []
    for row in rows:
        if unique and row["timestamp"] == unique[-1]["timestamp"]:
            continue
        unique.append(row)
    if len(unique) < 1000:
        raise ValueError("Insufficient closed Bitstamp hourly candles")
    for previous, current in zip(unique, unique[1:]):
        if current["timestamp"] - previous["timestamp"] != INTERVAL_MS:
            raise ValueError("Combined Bitstamp history contains an hourly gap")
    return unique


def run_cross_exchange_adx_lab(hourly_candles):
    report = run_ema_adx_filter_lab(hourly_candles)
    report["validation_type"] = "INDEPENDENT_CROSS_EXCHANGE_REPLICATION"
    report["data_source"] = "Bitstamp public spot OHLC"
    report["symbol"] = "BTCUSD"
    report["hourly_candles"] = len(hourly_candles)
    report["first_candle_time_utc"] = datetime.fromtimestamp(
        hourly_candles[0]["timestamp"] / 1000, timezone.utc
    ).isoformat()
    report["last_candle_time_utc"] = datetime.fromtimestamp(
        hourly_candles[-1]["timestamp"] / 1000, timezone.utc
    ).isoformat()
    report["paper_state_touched"] = False
    report["live_orders_enabled"] = False
    report["interpretation"] = (
        "Independent exchange replication using the same fixed thresholds, "
        "fees, slippage, 50/50 4h+6h sleeves, and matched benchmark. "
        "This is a robustness check, not a new threshold-selection exercise. "
        "Historical results do not imply forward-paper or live profitability."
    )
    return report


def main():
    candles = fetch_bitstamp_hourly_candles()
    report = run_cross_exchange_adx_lab(candles)
    Path("ema_adx_cross_exchange_research.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
