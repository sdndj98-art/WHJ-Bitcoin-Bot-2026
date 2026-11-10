"""Fail-closed validation of candle-aligned Kraken CVD evidence.

This module only classifies supplied, already-aggregated trade-flow evidence.
It does not read exchange credentials, connect to Kraken, mutate paper accounts,
or place orders. Callers must derive continuity_verified from the collector's
verified checkpoint and pass only a completed candle's evidence.
"""
import math


def validate_cvd_confirmation(
    candle_timestamp,
    evidence,
    *,
    now_timestamp,
    min_trades=10,
    max_last_trade_lag_seconds=120.0,
    min_abs_delta_pct=10.0,
):
    """Validate one closed candle's CVD evidence and return a research direction.

    A result is unavailable unless the caller explicitly asserts verified feed
    continuity, the candle identity matches, the candle is closed, sample size
    and freshness pass, and all numeric fields are finite.
    """
    def finite_number(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(name + " must be a finite number")
        if not math.isfinite(value):
            raise ValueError(name + " must be a finite number")
        return float(value)

    if isinstance(candle_timestamp, bool) or not isinstance(candle_timestamp, int) or candle_timestamp < 0:
        raise ValueError("candle_timestamp must be a non-negative integer")
    now = finite_number(now_timestamp, "now_timestamp")
    if isinstance(min_trades, bool) or not isinstance(min_trades, int) or min_trades < 1:
        raise ValueError("min_trades must be a positive integer")
    lag_limit = finite_number(max_last_trade_lag_seconds, "max_last_trade_lag_seconds")
    threshold = finite_number(min_abs_delta_pct, "min_abs_delta_pct")
    if lag_limit <= 0 or not 0 < threshold <= 100:
        raise ValueError("CVD freshness and delta thresholds are invalid")
    if not isinstance(evidence, dict):
        return _unavailable("cvd_evidence_missing")

    required_flags = (
        evidence.get("available") is True,
        evidence.get("continuity_verified") is True,
        evidence.get("is_closed") is True,
        evidence.get("research_only") is True,
        evidence.get("execution_enabled") is False,
    )
    if not all(required_flags):
        return _unavailable("cvd_evidence_not_verified_closed_research_data")
    if evidence.get("status") != "OK":
        return _unavailable("cvd_evidence_status_not_ok")
    timestamp = evidence.get("candle_timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp != candle_timestamp:
        return _unavailable("cvd_candle_timestamp_mismatch")

    count = evidence.get("trade_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < min_trades:
        return _unavailable("cvd_trade_sample_insufficient")
    try:
        lag = finite_number(evidence.get("last_trade_lag_seconds"), "last_trade_lag_seconds")
        delta = finite_number(evidence.get("delta_pct"), "delta_pct")
        open_price = finite_number(evidence.get("open"), "open")
        close_price = finite_number(evidence.get("close"), "close")
    except ValueError as exc:
        return _unavailable("cvd_invalid_numeric_evidence:" + str(exc))
    if lag < 0 or lag > lag_limit:
        return _unavailable("cvd_evidence_stale")
    if not -100 <= delta <= 100 or open_price <= 0 or close_price <= 0:
        return _unavailable("cvd_evidence_out_of_range")
    candle_end = candle_timestamp + int(evidence.get("interval_seconds", 3600))
    if candle_end > now:
        return _unavailable("cvd_candle_not_yet_closed")

    direction = "NEUTRAL"
    if close_price > open_price and delta >= threshold:
        direction = "BULLISH"
    elif close_price < open_price and delta <= -threshold:
        direction = "BEARISH"
    return {
        "status": "OK",
        "available": True,
        "direction": direction,
        "candle_timestamp": candle_timestamp,
        "trade_count": count,
        "delta_pct": round(delta, 4),
        "last_trade_lag_seconds": round(lag, 3),
        "continuity_verified": True,
        "research_only": True,
        "execution_enabled": False,
    }


def _unavailable(reason):
    return {
        "status": "UNAVAILABLE",
        "available": False,
        "direction": "UNKNOWN",
        "reason": reason,
        "research_only": True,
        "execution_enabled": False,
    }
