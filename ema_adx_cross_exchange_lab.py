"""Independent Binance BTCUSDT validation of the fixed EMA/ADX research rules.

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
BINANCE_HOSTS = (
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
)


def normalize_binance_klines(rows):
    """Convert Binance [open time, OHLCV, ...] rows to validated hourly bars."""
    if not isinstance(rows, list):
        raise ValueError("Binance kline page must be a list")
    normalized = []
    for item in rows:
        if not isinstance(item, list) or len(item) < 6:
            raise ValueError("Malformed Binance kline row")
        try:
            timestamp = int(item[0])
            open_price, high, low, close, volume = (float(item[i]) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Non-numeric Binance kline field") from exc
        values = (open_price, high, low, close, volume)
        if timestamp < 0 or timestamp % INTERVAL_MS:
            raise ValueError("Binance kline timestamp is not hourly aligned")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite Binance OHLCV value")
        if min(open_price, high, low, close) <= 0 or volume < 0:
            raise ValueError("Invalid Binance OHLCV price or volume")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Impossible Binance OHLC relationship")
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
            raise ValueError("Duplicate Binance hourly candle")
        if current["timestamp"] - previous["timestamp"] != INTERVAL_MS:
            raise ValueError("Binance hourly data contains a gap")
    return normalized


def _request_binance_page(start_ms, end_ms):
    params = urllib.parse.urlencode({
        "symbol": "BTCUSDT",
        "interval": "1h",
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000,
    })
    last_error = None
    for attempt in range(4):
        for host in BINANCE_HOSTS:
            request = urllib.request.Request(
                host + "/api/v3/klines?" + params,
                headers={
                    "User-Agent": "WHJ-Independent-Research/1.0",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    raise ValueError("Binance returned an unexpected kline payload")
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
        time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("Unable to download Binance BTCUSDT candles: " + str(last_error))


def fetch_binance_hourly_candles(days=DAYS, now=None):
    if isinstance(days, bool) or not isinstance(days, int) or days < 365:
        raise ValueError("Research history must be an integer of at least 365 days")
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    cutoff_ms = now_ms - (now_ms % INTERVAL_MS)
    start_ms = ((now_ms - days * 24 * INTERVAL_MS) // INTERVAL_MS) * INTERVAL_MS
    cursor = start_ms
    rows = []
    while cursor < cutoff_ms:
        page = _request_binance_page(cursor, cutoff_ms - 1)
        if not page:
            break
        page_rows = normalize_binance_klines(page)
        page_rows = [
            row for row in page_rows
            if cursor <= row["timestamp"] and row["timestamp"] + INTERVAL_MS <= cutoff_ms
        ]
        if not page_rows:
            break
        rows.extend(page_rows)
        next_cursor = page_rows[-1]["timestamp"] + INTERVAL_MS
        if next_cursor <= cursor:
            raise ValueError("Binance pagination did not advance")
        cursor = next_cursor
        if cursor < cutoff_ms:
            time.sleep(0.1)

    if len(rows) < 1000:
        raise ValueError("Insufficient closed Binance hourly candles")
    # Validate continuity across page boundaries as well as within each page.
    for previous, current in zip(rows, rows[1:]):
        if current["timestamp"] - previous["timestamp"] != INTERVAL_MS:
            raise ValueError("Combined Binance history contains an hourly gap")
    return rows


def run_cross_exchange_adx_lab(hourly_candles):
    report = run_ema_adx_filter_lab(hourly_candles)
    report["validation_type"] = "INDEPENDENT_CROSS_EXCHANGE_REPLICATION"
    report["data_source"] = "Binance public spot klines"
    report["symbol"] = "BTCUSDT"
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
    candles = fetch_binance_hourly_candles()
    report = run_cross_exchange_adx_lab(candles)
    Path("ema_adx_cross_exchange_research.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
