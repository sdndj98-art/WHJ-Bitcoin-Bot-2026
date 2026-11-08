"""Candle-aligned Kraken trade-flow diagnostics for research only.

Trade events are assigned to completed OHLCV intervals. This module deliberately
fails closed when feed continuity is not independently verified; it does not
infer missing trades, use order-book snapshots, or place orders.
"""
import math
from datetime import datetime
from bisect import bisect_right


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _timestamp(value):
    if isinstance(value, bool):
        raise ValueError("trade timestamp must be numeric or timezone-aware ISO text")
    if isinstance(value, (int, float)):
        result = _number(value, "trade timestamp")
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid ISO-8601 trade timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("ISO-8601 trade timestamp must include timezone")
        result = parsed.timestamp()
    else:
        raise ValueError("trade timestamp must be numeric or timezone-aware ISO text")
    if result < 0:
        raise ValueError("trade timestamp must be non-negative")
    return result


def align_trade_flow_to_candles(candles, trades, interval_seconds=3600,
                                continuity_verified=False, min_trades=1,
                                max_last_trade_lag_seconds=60.0,
                                min_abs_delta_pct=10.0):
    """Align signed trade volume to candle starts; only closed, verified bars qualify.

    candles use Kraken OHLCV rows [time, open, high, low, close, vwap, volume, count].
    trades use dicts with trade_id, timestamp, qty, and side ('buy'/'sell').
    """
    if not isinstance(candles, list) or not candles:
        raise ValueError("candles must be a non-empty list")
    if not isinstance(trades, list):
        raise ValueError("trades must be a list")
    if not isinstance(continuity_verified, bool):
        raise ValueError("continuity_verified must be boolean")
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or interval_seconds <= 0:
        raise ValueError("interval_seconds must be a positive integer")
    if isinstance(min_trades, bool) or not isinstance(min_trades, int) or min_trades < 1:
        raise ValueError("min_trades must be a positive integer")
    lag_limit = _number(max_last_trade_lag_seconds, "max_last_trade_lag_seconds")
    threshold = _number(min_abs_delta_pct, "min_abs_delta_pct")
    if lag_limit < 0 or not 0 <= threshold <= 100:
        raise ValueError("invalid lag or delta threshold")

    starts = []
    normalized = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            raise ValueError("each candle must contain the Kraken OHLCV fields")
        timestamp = _number(row[0], "candle timestamp")
        if not timestamp.is_integer() or timestamp < 0:
            raise ValueError("candle timestamp must be a non-negative integer")
        values = [_number(row[i], name) for i, name in zip(
            (1, 2, 3, 4, 6, 7),
            ("open", "high", "low", "close", "volume", "trade_count")
        )]
        open_price, high, low, close, volume, count = values
        if min(open_price, high, low, close) <= 0 or volume < 0 or count < 0 or not count.is_integer():
            raise ValueError("invalid candle price, volume, or trade count")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("inconsistent candle OHLC bounds")
        start = int(timestamp)
        if start % interval_seconds:
            raise ValueError("candle timestamps must align to interval boundaries")
        if starts and start - starts[-1] != interval_seconds:
            raise ValueError("candles must be strictly increasing and contiguous")
        starts.append(start)
        normalized.append((open_price, close))
    if len(set(starts)) != len(starts):
        raise ValueError("duplicate candle timestamp")

    buckets = {start: [] for start in starts}
    previous_trade_id = None
    previous_timestamp = -1.0
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
        timestamp = _timestamp(trade.get("timestamp"))
        if timestamp < previous_timestamp:
            raise ValueError("trade timestamps must be non-decreasing")
        previous_timestamp = timestamp
        quantity = _number(trade.get("qty"), "trade quantity")
        side = trade.get("side")
        if quantity <= 0 or side not in ("buy", "sell"):
            raise ValueError("trade quantity must be positive and side buy/sell")
        index = bisect_right(starts, timestamp) - 1
        if index < 0 or timestamp >= starts[-1] + interval_seconds:
            raise ValueError("trade timestamp is outside supplied candle coverage")
        buckets[starts[index]].append((timestamp, quantity, side))

    output = []
    for start, (open_price, close) in zip(starts, normalized):
        events = buckets[start]
        buy = sum(qty for _, qty, side in events if side == "buy")
        sell = sum(qty for _, qty, side in events if side == "sell")
        total = buy + sell
        last_ts = events[-1][0] if events else None
        lag = (start + interval_seconds - last_ts) if last_ts is not None else None
        enough = len(events) >= min_trades and total > 0
        fresh = enough and lag <= lag_limit
        available = continuity_verified and fresh
        delta_pct = ((buy - sell) / total * 100.0) if total else 0.0
        aligned = {
            "candle_timestamp": start,
            "trade_count": len(events),
            "buy_volume": round(buy, 12),
            "sell_volume": round(sell, 12),
            "delta_volume": round(buy - sell, 12),
            "delta_pct": round(delta_pct, 4),
            "last_trade_lag_seconds": round(lag, 3) if lag is not None else None,
            "continuity_verified": continuity_verified,
            "available": available,
            "status": "OK" if available else (
                "CONTINUITY_UNVERIFIED" if not continuity_verified else
                "INSUFFICIENT_OR_STALE_TRADES"
            ),
            "bullish_flow_confirmation": bool(
                available and close > open_price and delta_pct >= threshold
            ),
            "bearish_flow_confirmation": bool(
                available and close < open_price and delta_pct <= -threshold
            ),
            "bullish_absorption_divergence": bool(
                available and close < open_price and delta_pct >= threshold
            ),
            "bearish_absorption_divergence": bool(
                available and close > open_price and delta_pct <= -threshold
            ),
            "research_only": True,
            "execution_enabled": False,
        }
        output.append(aligned)

    return {
        "status": "OK" if all(item["available"] for item in output) else "PARTIAL_OR_UNAVAILABLE",
        "interval_seconds": interval_seconds,
        "bars": output,
        "available_bars": sum(item["available"] for item in output),
        "total_bars": len(output),
        "research_only": True,
        "execution_enabled": False,
        "limitations": [
            "Continuity is an explicit caller assertion and must come from the feed adapter's gap-recovery state.",
            "A trade batch cannot prove completeness without a verified cursor and gap-free ingestion.",
            "CVD is aggressor-side volume for one venue and is not order-book depth.",
            "This diagnostic is not a backtest, profitability claim, or order instruction.",
        ],
    }
