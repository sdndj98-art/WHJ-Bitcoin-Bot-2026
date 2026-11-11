"""Public XAU/USD daily OHLC research data from Yahoo Finance chart API.

This is a spot-price reference series, not a broker execution feed. It does not
provide executable bid/ask, CFD financing, commissions, or futures-roll data.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX"
USER_AGENT = "WHJ-Multi-Asset-Research/1.0"


def parse_yahoo_chart(payload):
    if not isinstance(payload, dict):
        raise ValueError("Yahoo chart payload must be a mapping")
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError("Yahoo chart API error: " + str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise ValueError("Yahoo returned no XAU/USD chart result")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]
    arrays = [quote.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
    if not timestamps or any(len(values) != len(timestamps) for values in arrays):
        raise ValueError("Yahoo XAU/USD OHLC arrays are missing or misaligned")
    rows, seen = [], set()
    for i, stamp in enumerate(timestamps):
        values = [arrays[j][i] for j in range(4)]
        if any(v is None or isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or v <= 0 for v in values):
            continue
        o, h, l, c = map(float, values)
        if h < max(o, l, c) or l > min(o, h, c):
            raise ValueError("Impossible XAU/USD OHLC relationship")
        timestamp_ms = int(stamp) * 1000
        if timestamp_ms in seen:
            raise ValueError("Duplicate XAU/USD daily timestamp")
        seen.add(timestamp_ms)
        volume = arrays[4][i]
        rows.append({
            "timestamp": timestamp_ms, "open": o, "high": h, "low": l,
            "close": c, "volume": float(volume) if isinstance(volume, (int, float)) and math.isfinite(volume) else 0.0,
            "imputed": False,
        })
    rows.sort(key=lambda x: x["timestamp"])
    if len(rows) < 1000:
        raise ValueError("Fewer than 1,000 valid closed XAU/USD daily candles")
    # Yahoo's final daily candle may still be forming. Exclude it conservatively.
    rows = rows[:-1]
    if len(rows) < 999:
        raise ValueError("Insufficient XAU/USD daily history after dropping final candle")
    return rows


def load_xauusd_daily(period="10y", retries=4):
    if period not in ("5y", "10y"):
        raise ValueError("Supported XAU/USD daily history periods are 5y or 10y")
    params = urllib.parse.urlencode({"range": period, "interval": "1d", "events": "history"})
    request = urllib.request.Request(
        BASE_URL + "?" + params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return parse_yahoo_chart(payload)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("Unable to download Yahoo XAU/USD daily candles: " + str(last_error))
