"""Deterministic six-agent consensus signal engine for WHJ paper trading.

Five independent rule-based analysts vote BUY/SELL/HOLD; a sixth risk agent
vetoes signals during extreme volatility. This is not a predictive guarantee
and does not submit broker orders.
"""
from __future__ import annotations

import math

MIN_BARS = 25
MAX_AVG_RANGE_PCT = 0.08
MIN_CONSENSUS_VOTES = 3
MIN_CONSENSUS_RATIO = 0.60


def _finite(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _validate_bars(bars):
    if not isinstance(bars, list) or len(bars) < MIN_BARS:
        raise ValueError(f"at least {MIN_BARS} OHLCV bars required")
    result = []
    for i, bar in enumerate(bars[-100:]):
        if not isinstance(bar, dict):
            raise ValueError(f"bar {i} must be an object")
        close = _finite(bar.get("close"), f"bar {i} close")
        high = _finite(bar.get("high"), f"bar {i} high")
        low = _finite(bar.get("low"), f"bar {i} low")
        volume = _finite(bar.get("volume", 0), f"bar {i} volume")
        if close <= 0 or low <= 0 or high < low or not low <= close <= high or volume < 0:
            raise ValueError(f"bar {i} has invalid OHLCV values")
        result.append({"close": close, "high": high, "low": low, "volume": volume})
    if len(result) < MIN_BARS:
        raise ValueError(f"at least {MIN_BARS} OHLCV bars required")
    return result


def _vote_trend(bars):
    closes = [b["close"] for b in bars]
    short = sum(closes[-5:]) / 5
    long = sum(closes[-20:]) / 20
    prior_long = sum(closes[-25:-5]) / 20
    if short > long and long > prior_long:
        return "BUY"
    if short < long and long < prior_long:
        return "SELL"
    return "HOLD"


def _vote_momentum(bars):
    closes = [b["close"] for b in bars]
    change = closes[-1] / closes[-6] - 1
    if change >= 0.003:
        return "BUY"
    if change <= -0.003:
        return "SELL"
    return "HOLD"


def _vote_mean_reversion(bars):
    closes = [b["close"] for b in bars[-20:]]
    mean = sum(closes) / len(closes)
    variance = sum((x - mean) ** 2 for x in closes) / len(closes)
    std = math.sqrt(variance)
    if std == 0:
        return "HOLD"
    z = (closes[-1] - mean) / std
    if z <= -1.5:
        return "BUY"
    if z >= 1.5:
        return "SELL"
    return "HOLD"


def _vote_breakout(bars):
    previous = bars[-21:-1]
    close = bars[-1]["close"]
    if close > max(b["high"] for b in previous):
        return "BUY"
    if close < min(b["low"] for b in previous):
        return "SELL"
    return "HOLD"


def _vote_volume(bars):
    recent = bars[-5:]
    avg_volume = sum(b["volume"] for b in bars[-21:-1]) / 20
    last = recent[-1]
    previous_close = bars[-2]["close"]
    if avg_volume <= 0 or last["volume"] < avg_volume * 1.3:
        return "HOLD"
    if last["close"] > previous_close:
        return "BUY"
    if last["close"] < previous_close:
        return "SELL"
    return "HOLD"


def _risk_agent(bars, max_avg_range_pct):
    ranges = [(b["high"] - b["low"]) / b["close"] for b in bars[-20:]]
    average_range = sum(ranges) / len(ranges)
    if average_range > max_avg_range_pct:
        return "VETO"
    return "ALLOW"


def analyze_market(bars, *, max_avg_range_pct=MAX_AVG_RANGE_PCT):
    """Return six agent outputs and a conservative consensus signal."""
    validated = _validate_bars(bars)
    max_range = _finite(max_avg_range_pct, "max_avg_range_pct")
    if not 0 < max_range <= 1:
        raise ValueError("max_avg_range_pct must be in (0, 1]")
    votes = {
        "SCANNER": _vote_trend(validated),
        "MOMENTUM": _vote_momentum(validated),
        "MEAN_REVERSION": _vote_mean_reversion(validated),
        "BREAKOUT": _vote_breakout(validated),
        "VOLUME": _vote_volume(validated),
    }
    risk = _risk_agent(validated, max_range)
    buy = sum(v == "BUY" for v in votes.values())
    sell = sum(v == "SELL" for v in votes.values())
    total = len(votes)
    if risk == "VETO":
        signal, reason = "HOLD", "RISK_AGENT_VETO"
    elif buy >= MIN_CONSENSUS_VOTES and buy / total >= MIN_CONSENSUS_RATIO and buy > sell:
        signal, reason = "BUY", "BUY_CONSENSUS"
    elif sell >= MIN_CONSENSUS_VOTES and sell / total >= MIN_CONSENSUS_RATIO and sell > buy:
        signal, reason = "SELL", "SELL_CONSENSUS"
    else:
        signal, reason = "HOLD", "NO_CLEAR_CONSENSUS"
    return {
        "signal": signal,
        "reason": reason,
        "agents": {**votes, "RISK": risk},
        "buy_votes": buy,
        "sell_votes": sell,
        "confidence": round(max(buy, sell) / total, 4),
        "risk_veto": risk == "VETO",
        "paper_only": True,
        "live_trading_enabled": False,
        "orders_submitted": False,
    }


def analyze_universe(bars_by_symbol):
    """Analyze provided OHLCV histories; missing/invalid markets are HOLD."""
    if not isinstance(bars_by_symbol, dict):
        raise ValueError("bars_by_symbol must be an object")
    result = {}
    for symbol, bars in bars_by_symbol.items():
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        try:
            result[symbol] = analyze_market(bars)
        except (ValueError, TypeError) as exc:
            result[symbol] = {
                "signal": "HOLD", "reason": "INVALID_OR_INSUFFICIENT_DATA",
                "error": str(exc), "paper_only": True,
                "live_trading_enabled": False, "orders_submitted": False,
            }
    return result
