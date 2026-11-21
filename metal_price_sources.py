"""Validated Gold-API spot quotes and goldprice.dev daily OHLC history.
Spot timestamps have a five-minute safety ceiling. Daily bars are available
only for XAU/XAG/HG on the free tier; never fabricate missing candles.
"""
import json, math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE_URL = "https://api.goldprice.dev/v1"
SYMBOLS = {"XAUUSD": "XAU-USD-SPOT", "XAGUSD": "XAG-USD-SPOT", "XCUUSD": "HG-USD-SPOT"}
CODES = {"XAUUSD": "XAU", "XAGUSD": "XAG", "XCUUSD": "HG"}
SPOT_CODES = {"XAUUSD": "XAU", "XAGUSD": "XAG", "XPTUSD": "XPT", "XPDUSD": "XPD", "XCUUSD": "HG"}
UNITS = {"XAUUSD": "troy_ounce", "XAGUSD": "troy_ounce", "XPTUSD": "troy_ounce", "XPDUSD": "troy_ounce", "XCUUSD": "pound"}
SOURCE = "Gold-API public spot; goldprice.dev free daily OHLC history"

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
    """Fetch timestamp-validated public spot from Gold-API (all five metals)."""
    if symbol not in SPOT_CODES:
        raise ValueError("Unsupported Gold-API spot symbol: " + str(symbol))
    now_seconds = now_seconds if now_seconds is not None else datetime.now(timezone.utc).timestamp()
    url = "https://api.gold-api.com/price/" + SPOT_CODES[symbol]
    item = _get_json(url)
    if item.get("symbol") != SPOT_CODES[symbol] or item.get("currency") != "USD":
        raise ValueError("Gold-API spot symbol/currency mismatch")
    expected_unit = "lb" if symbol == "XCUUSD" else "oz"
    raw_unit = str(item.get("unit", "")).strip().lower().replace(" ", "_")
    accepted_units = {"lb", "pound", "usd/lb", "usd_per_lb"} if symbol == "XCUUSD" else {
        "oz", "ozt", "troy_ounce", "troy_oz", "troyounce", "usd/oz", "usd/ozt",
        "usd_per_oz", "usd_per_troy_ounce",
    }
    if raw_unit and raw_unit not in accepted_units:
        raise ValueError("Gold-API spot unit mismatch: expected " + expected_unit + ", received " + repr(item.get("unit")))
    # The public endpoint omits unit on some responses. The provider's
    # documented symbol contract is troy ounce for XAU/XAG/XPT/XPD and pound
    # for HG; only infer when the unit field is absent, never when conflicting.
    price = _number(item.get("price"), "spot price")
    stamp = _parse_timestamp(item.get("updatedAt"), "spot")
    age = now_seconds - stamp
    if price <= 0:
        raise ValueError("Gold-API spot price must be positive")
    if age < -60:
        raise ValueError("Gold-API spot timestamp is future-dated")
    # Gold-API documents 30-second updates; five minutes is a conservative
    # operational freshness ceiling, not an assumption about the quote itself.
    if age > 5 * 60:
        raise ValueError("Gold-API spot quote exceeds the 5-minute safety age")
    return {
        "symbol": symbol, "provider_symbol": SPOT_CODES[symbol],
        "price_usd": price, "price_unit": UNITS[symbol], "provider_unit": item.get("unit") or "symbol-contract-inferred",
        "computed_at": item["updatedAt"], "quote_age_seconds": round(age, 1),
        "expected_delay_minutes": 0,
        "provider": "Gold-API public spot (approximately 30-second refresh)",
        "quality": "TIMESTAMP_VALIDATED_SPOT",
    }


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
