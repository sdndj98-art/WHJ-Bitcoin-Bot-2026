"""Validated, free-tier goldprice.dev market data for WHJ paper research.
The keyless/free feed is delayed by 15 minutes. It provides XAU/XAG/HG spot
prices; intraday bars require an eligible plan. Never fabricate missing bars.
"""
import json, math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE_URL = "https://api.goldprice.dev/v1"
SYMBOLS = {"XAUUSD": "XAU-USD-SPOT", "XAGUSD": "XAG-USD-SPOT", "XCUUSD": "HG-USD-SPOT"}
CODES = {"XAUUSD": "XAU", "XAGUSD": "XAG", "XCUUSD": "HG"}
UNITS = {"XAUUSD": "troy_ounce", "XAGUSD": "troy_ounce", "XCUUSD": "pound"}
SOURCE = "goldprice.dev (15-minute delayed free/keyless spot feed)"

def _get_json(url, timeout=15):
    request = Request(url, headers={"User-Agent": "WHJ-PaperResearch/1.0", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status, body = response.status, response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ValueError("goldprice.dev HTTP " + str(exc.code) + ": " + body) from exc
    if status != 200:
        raise ValueError("goldprice.dev HTTP " + str(status))
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("goldprice.dev response is not a JSON object")
    return data

def _parse_timestamp(value, label):
    if not isinstance(value, str):
        raise ValueError(label + " timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(label + " timestamp must include timezone")
    return parsed.timestamp()

def _number(value, label):
    if isinstance(value, bool):
        raise ValueError(label + " must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + " must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(label + " must be finite")
    return number

def fetch_spot(symbol, now_seconds=None):
    if symbol not in SYMBOLS:
        raise ValueError("Unsupported goldprice.dev spot symbol: " + str(symbol))
    now_seconds = now_seconds if now_seconds is not None else datetime.now(timezone.utc).timestamp()
    url = BASE_URL + "/prices?" + urlencode({"symbol": SYMBOLS[symbol]})
    payload = _get_json(url)
    rows = payload.get("symbols")
    if not isinstance(rows, list):
        raise ValueError("goldprice.dev symbols array missing")
    item = next((row for row in rows if isinstance(row, dict)
        and row.get("symbol") == CODES[symbol] and row.get("quote_currency") == "USD"
        and row.get("contract_type") == "spot"), None)
    if item is None:
        raise ValueError("goldprice.dev did not return requested USD spot symbol")
    if item.get("is_stale") is not False:
        raise ValueError("goldprice.dev spot is stale or freshness unconfirmed")
    price = _number(item.get("price"), "spot price")
    stamp = _parse_timestamp(item.get("computed_at"), "spot")
    age = now_seconds - stamp
    if price <= 0:
        raise ValueError("goldprice.dev spot price must be positive")
    if age < -60:
        raise ValueError("goldprice.dev spot timestamp is future-dated")
    # The source's own is_stale flag is authoritative; allow a cache margin
    # beyond its advertised 15-minute delay.
    if age > 60 * 60:
        raise ValueError("goldprice.dev spot quote exceeds the 60-minute safety age")
    return {"symbol": symbol, "provider_symbol": SYMBOLS[symbol], "price_usd": price, "price_unit": UNITS[symbol],
        "computed_at": item["computed_at"], "quote_age_seconds": round(age, 1),
        "expected_delay_minutes": 15, "provider": SOURCE, "quality": "DELAYED_SPOT_VALIDATED"}

def fetch_daily_bars(symbol, now_seconds=None, days=30):
    """Fetch closed daily spot bars available on the Free/keyless tier."""
    if symbol not in SYMBOLS:
        raise ValueError("Unsupported goldprice.dev daily symbol: " + str(symbol))
    if not isinstance(days, int) or days < 1 or days > 30:
        raise ValueError("Free-tier daily history request must be 1..30 days")
    now_seconds = now_seconds if now_seconds is not None else datetime.now(timezone.utc).timestamp()
    end = datetime.fromtimestamp(now_seconds, timezone.utc)
    start = end - timedelta(days=days - 1)
    query = urlencode({"symbol": SYMBOLS[symbol], "interval": "1d",
        "from": start.date().isoformat(), "to": end.date().isoformat(), "limit": 1000})
    payload = _get_json(BASE_URL + "/bars?" + query)
    if payload.get("symbol") not in (CODES[symbol], SYMBOLS[symbol], symbol):
        raise ValueError("goldprice.dev daily bars symbol mismatch")
    if payload.get("interval") != "1d":
        raise ValueError("goldprice.dev daily interval mismatch")
    source_bars = payload.get("bars")
    if not isinstance(source_bars, list):
        raise ValueError("goldprice.dev daily bars missing")
    bars = []
    for item in source_bars:
        if not isinstance(item, dict) or item.get("is_closed") is not True:
            continue
        timestamp = int(_parse_timestamp(item.get("bar_start"), "daily bar"))
        if timestamp % 86400:
            raise ValueError("goldprice.dev daily bar is not UTC aligned")
        op, high, low, close = [_number(item.get(key), "daily OHLC") for key in ("open", "high", "low", "close")]
        if min(op, high, low, close) <= 0 or high < max(op, close, low) or low > min(op, close, high):
            raise ValueError("goldprice.dev daily OHLC bounds invalid")
        volume = None if item.get("volume") is None else _number(item.get("volume"), "daily volume")
        if volume is not None and volume < 0:
            raise ValueError("goldprice.dev daily volume cannot be negative")
        bars.append([timestamp, op, high, low, close, 0.0, volume])
    bars.sort(key=lambda row: row[0])
    unique = {row[0]: row for row in bars}
    bars = [unique[key] for key in sorted(unique)]
    if len(bars) < 20:
        raise ValueError("Insufficient closed daily spot bars: need at least 20 for daily strategy warmup")
    recent = bars[-20:]
    if any(b[0] - a[0] > 4 * 86400 for a, b in zip(recent, recent[1:])):
        raise ValueError("goldprice.dev recent daily bars contain a gap over four days")
    age = now_seconds - (bars[-1][0] + 86400)
    if age < -120 or age > 4 * 86400:
        raise ValueError("goldprice.dev latest completed daily bar is stale")
    return bars
