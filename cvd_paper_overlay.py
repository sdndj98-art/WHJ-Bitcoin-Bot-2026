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
    interval = evidence.get("interval_seconds", 3600)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        return _unavailable("cvd_invalid_candle_interval")
    candle_end = candle_timestamp + interval
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

def build_latest_cvd_confirmation(
    candles,
    journal_path,
    checkpoint_path,
    *,
    now_timestamp,
    interval_seconds=3600,
    min_trades=10,
    max_last_trade_lag_seconds=120.0,
    min_abs_delta_pct=10.0,
):
    """Build a closed-candle confirmation from an integrity-bound JSONL journal.

    Candle input uses forward_paper_monitor's dict schema and millisecond
    timestamps. Only the latest supplied candle is evaluated. Any checkpoint,
    journal, alignment, or freshness problem returns UNAVAILABLE.
    """
    import hashlib
    import json
    from pathlib import Path

    from cvd_candle_research import align_trade_flow_to_candles
    from trade_journal_checkpoint import (
        load_continuity_checkpoint,
        validate_continuity_checkpoint,
    )

    try:
        if not isinstance(candles, list) or not candles:
            return _unavailable("cvd_market_candles_missing")
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or interval_seconds <= 0:
            return _unavailable("cvd_invalid_candle_interval")
        candle = candles[-1]
        if not isinstance(candle, dict):
            return _unavailable("cvd_market_candle_invalid")
        timestamp_ms = candle.get("timestamp")
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)):
            return _unavailable("cvd_market_candle_timestamp_invalid")
        if not math.isfinite(timestamp_ms) or not float(timestamp_ms).is_integer():
            return _unavailable("cvd_market_candle_timestamp_invalid")
        timestamp = int(timestamp_ms // 1000)
        import time
        now = float(time.time() if now_timestamp is None else now_timestamp)
        if timestamp + interval_seconds > now:
            return _unavailable("cvd_candle_not_yet_closed")

        checkpoint = load_continuity_checkpoint(checkpoint_path)
        metadata = validate_continuity_checkpoint(
            checkpoint, journal_path, "BTC/USD",
            expected_last_trade_id=checkpoint.get("last_trade_id"),
        )
        # A gap-free journal is not enough if collection began after this
        # candle opened. Require the first recorded trade to predate the
        # evaluated candle so a partial first candle cannot be called complete.
        if metadata["first_trade_timestamp_ns"] > timestamp * 1_000_000_000:
            return _unavailable("cvd_journal_starts_after_candle_open")
        raw = Path(journal_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != checkpoint.get("journal_sha256"):
            return _unavailable("cvd_journal_changed_during_snapshot")
        if len(raw) != metadata["journal_size_bytes"]:
            return _unavailable("cvd_journal_size_mismatch")

        trades = []
        for line in raw.splitlines():
            event = json.loads(line.decode("utf-8"))
            if event["trade_id"] > metadata["last_trade_id"]:
                break
            event_ts = event.get("timestamp")
            if isinstance(event_ts, (int, float)) and timestamp <= float(event_ts) < timestamp + interval_seconds:
                trades.append({
                    "trade_id": event["trade_id"],
                    "timestamp": event_ts,
                    "qty": event["qty"],
                    "side": event["side"],
                })
            elif isinstance(event_ts, str):
                from cvd_candle_research import _timestamp
                event_seconds = _timestamp(event_ts)
                if timestamp <= event_seconds < timestamp + interval_seconds:
                    trades.append({
                        "trade_id": event["trade_id"],
                        "timestamp": event_ts,
                        "qty": event["qty"],
                        "side": event["side"],
                    })

        row = [
            timestamp, candle["open"], candle["high"], candle["low"],
            candle["close"], candle.get("close", candle["open"]),
            candle.get("volume", 0.0), 0,
        ]
        aligned = align_trade_flow_to_candles(
            [row], trades, interval_seconds=interval_seconds,
            continuity_verified=True, min_trades=min_trades,
            max_last_trade_lag_seconds=max_last_trade_lag_seconds,
            min_abs_delta_pct=min_abs_delta_pct,
        )["bars"][0]
        evidence = dict(
            aligned,
            is_closed=True,
            open=float(candle["open"]),
            close=float(candle["close"]),
            interval_seconds=interval_seconds,
            status="OK" if aligned["available"] else aligned["status"],
            available=aligned["available"],
            continuity_verified=True,
            research_only=True,
            execution_enabled=False,
        )
        return validate_cvd_confirmation(
            timestamp, evidence, now_timestamp=now,
            min_trades=min_trades,
            max_last_trade_lag_seconds=max_last_trade_lag_seconds,
            min_abs_delta_pct=min_abs_delta_pct,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _unavailable("cvd_source_validation_failed:" + type(exc).__name__)
