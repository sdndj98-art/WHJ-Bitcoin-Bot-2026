"""Build completed OHLCV candles directly from normalized executed trades."""
from datetime import datetime
import math


def _finite(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _timestamp(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric or timezone-aware ISO text")
    if isinstance(value, (int, float)):
        result = _finite(value, field)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} is not valid ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must include a timezone")
        result = parsed.timestamp()
    else:
        raise ValueError(f"{field} must be numeric or timezone-aware ISO text")
    if result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result


def build_trade_candles(trades, interval_seconds, now_timestamp, start_timestamp=None):
    """Return closed Kraken-shaped OHLCV candles and their exact trade subset.

    Normalized trade fields: trade_id, timestamp, price, qty, side ('buy'/'sell').
    The currently forming candle is always excluded. Empty interior buckets are
    carried forward at the previous close with zero volume and zero trade count.
    No price or volume is fabricated for a bucket before the first real trade.
    """
    if not isinstance(trades, list) or not trades:
        raise ValueError("trades must be a non-empty list")
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or interval_seconds <= 0:
        raise ValueError("interval_seconds must be a positive integer")
    now = _timestamp(now_timestamp, "now_timestamp")
    end_exclusive = int(now // interval_seconds) * interval_seconds
    if end_exclusive <= 0:
        raise ValueError("no completed candle exists at the supplied time")

    normalized = []
    previous_trade_id = None
    previous_ts = -1.0
    for trade in trades:
        if not isinstance(trade, dict):
            raise ValueError("each trade must be an object")
        trade_id = trade.get("trade_id")
        if isinstance(trade_id, bool) or not str(trade_id).isdigit() or int(trade_id) <= 0:
            raise ValueError("trade_id must be a positive integer")
        trade_id = int(trade_id)
        if previous_trade_id is not None and trade_id <= previous_trade_id:
            raise ValueError("trade IDs must be strictly increasing")
        previous_trade_id = trade_id
        ts = _timestamp(trade.get("timestamp"), "trade timestamp")
        if ts < previous_ts:
            raise ValueError("trades must be sorted by non-decreasing timestamp")
        previous_ts = ts
        price = _finite(trade.get("price"), "trade price")
        qty = _finite(trade.get("qty"), "trade quantity")
        side = trade.get("side")
        if price <= 0 or qty <= 0 or side not in ("buy", "sell"):
            raise ValueError("trade price/quantity must be positive and side buy/sell")
        normalized.append({
            "trade_id": trade_id, "timestamp": ts,
            "price": price, "qty": qty, "side": side,
        })

    first_ts = normalized[0]["timestamp"]
    start = (int(first_ts // interval_seconds) * interval_seconds
             if start_timestamp is None else _timestamp(start_timestamp, "start_timestamp"))
    if not float(start).is_integer() or int(start) % interval_seconds:
        raise ValueError("start_timestamp must be an integer interval boundary")
    start = int(start)
    if start > first_ts:
        raise ValueError("start_timestamp cannot be after the first supplied trade")
    if start >= end_exclusive:
        raise ValueError("trade data contains no completed candle")

    included = [item for item in normalized if start <= item["timestamp"] < end_exclusive]
    if not included:
        raise ValueError("no trades fall inside completed candle coverage")
    if included[0]["timestamp"] // interval_seconds * interval_seconds != start:
        raise ValueError("first candle bucket has no trade; provide a later start_timestamp")

    buckets = {}
    for trade in included:
        bucket_start = int(trade["timestamp"] // interval_seconds) * interval_seconds
        buckets.setdefault(bucket_start, []).append(trade)

    candles = []
    previous_close = None
    for bucket_start in range(start, end_exclusive, interval_seconds):
        events = buckets.get(bucket_start, [])
        if events:
            prices = [item["price"] for item in events]
            volume = sum(item["qty"] for item in events)
            notional = sum(item["price"] * item["qty"] for item in events)
            open_price, close = prices[0], prices[-1]
            high, low = max(prices), min(prices)
            vwap = notional / volume
            count = len(events)
            previous_close = close
        else:
            if previous_close is None:
                raise ValueError("cannot fill an empty first candle without a prior close")
            open_price = high = low = close = previous_close
            vwap, volume, count = previous_close, 0.0, 0
        candles.append([
            bucket_start, open_price, high, low, close,
            vwap, volume, count,
        ])

    return {
        "status": "OK",
        "interval_seconds": interval_seconds,
        "candles": candles,
        "trades": included,
        "closed_until_timestamp": end_exclusive,
        "excluded_forming_candle_trades": sum(
            1 for item in normalized
            if end_exclusive <= item["timestamp"] < end_exclusive + interval_seconds
        ),
        "trade_count": len(included),
        "candle_count": len(candles),
        "empty_candle_count": sum(1 for row in candles if row[7] == 0),
        "research_only": True,
        "execution_enabled": False,
        "limitations": [
            "The caller must establish complete, gap-free trade ingestion independently.",
            "The current forming candle is excluded; only completed intervals are returned.",
            "Empty interior intervals are carried forward at the previous close with zero volume.",
            "This builder does not recover missing exchange trades or prove feed continuity.",
        ],
    }
