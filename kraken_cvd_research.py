"""Read-only integration of a Kraken trade journal and multi-timeframe CVD.

A contiguous journal is not, by itself, proof that the feed is complete. CVD
votes therefore remain disabled unless the caller supplies a matching,
explicitly verified Kraken feed checkpoint from its recovery/collector state.
"""
import json
import math
import os
import time
from datetime import datetime

from trade_candle_builder import build_trade_candles
from multi_timeframe_cvd import TIMEFRAME_SECONDS, analyze_multi_timeframe_cvd


def _epoch(value):
    if isinstance(value, bool):
        raise ValueError("invalid journal timestamp")
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid journal timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("journal timestamp must include timezone")
        result = parsed.timestamp()
    else:
        raise ValueError("invalid journal timestamp")
    if not math.isfinite(result) or result < 0:
        raise ValueError("journal timestamp must be finite and non-negative")
    return result


def _positive_trade_id(value, line_number):
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError(f"invalid trade ID at line {line_number}")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"invalid trade ID at line {line_number}")
    return parsed


def load_normalized_trade_journal(path):
    """Load and validate the complete append-only journal without modifying it."""
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise ValueError("journal path must be non-empty")

    trades = []
    previous_id = None
    previous_timestamp = -1.0
    symbol = None

    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n"):
                raise ValueError(f"incomplete journal line: {line_number}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"journal line {line_number} is not an object")

            trade_id = _positive_trade_id(event.get("trade_id"), line_number)
            if previous_id is not None and trade_id != previous_id + 1:
                raise ValueError(f"trade ID gap at line {line_number}")

            timestamp = _epoch(event.get("timestamp"))
            if timestamp < previous_timestamp:
                raise ValueError(f"timestamp moved backwards at line {line_number}")

            current_symbol = event.get("symbol")
            if not isinstance(current_symbol, str) or not current_symbol.strip():
                raise ValueError(f"invalid symbol at line {line_number}")
            current_symbol = current_symbol.strip()

            values = {}
            for field in ("price", "qty"):
                value = event.get(field)
                try:
                    if isinstance(value, bool):
                        raise ValueError
                    numeric_value = float(value)
                except (TypeError, ValueError, OverflowError):
                    raise ValueError(f"invalid {field} at line {line_number}")
                if not math.isfinite(numeric_value) or numeric_value <= 0:
                    raise ValueError(f"invalid {field} at line {line_number}")
                values[field] = numeric_value

            side = event.get("side")
            if side not in ("buy", "sell"):
                raise ValueError(f"invalid side at line {line_number}")

            if symbol is None:
                symbol = current_symbol
            elif current_symbol != symbol:
                raise ValueError("journal contains mixed symbols")

            trades.append({
                "trade_id": trade_id,
                "timestamp": event["timestamp"],
                "price": values["price"],
                "qty": values["qty"],
                "side": side,
            })
            previous_id = trade_id
            previous_timestamp = timestamp

    if not trades:
        raise ValueError("trade journal is empty")

    return {
        "trades": trades,
        "symbol": symbol,
        "first_trade_id": trades[0]["trade_id"],
        "last_trade_id": trades[-1]["trade_id"],
        "trade_count": len(trades),
        "continuity_from_first_recorded_trade": True,
        "feed_continuity_verified": False,
    }


def _validate_continuity_checkpoint(checkpoint, journal):
    """Require an explicit collector/recovery assertion matching this journal."""
    if checkpoint is None:
        return False
    if not isinstance(checkpoint, dict):
        raise ValueError("continuity_checkpoint must be a mapping")
    if checkpoint.get("source") != "kraken_spot_trade_feed_adapter":
        raise ValueError("continuity checkpoint source is not trusted")
    if checkpoint.get("feed_continuity_verified") is not True:
        raise ValueError("continuity checkpoint is not verified")
    checkpoint_id = checkpoint.get("last_trade_id")
    if isinstance(checkpoint_id, bool) or not isinstance(checkpoint_id, int) or checkpoint_id <= 0:
        raise ValueError("continuity checkpoint has an invalid last_trade_id")
    if checkpoint_id != journal["last_trade_id"]:
        raise ValueError("continuity checkpoint does not match journal last trade ID")
    if checkpoint.get("symbol") != journal["symbol"]:
        raise ValueError("continuity checkpoint symbol does not match journal")
    return True


def analyze_trade_journal(
    path,
    now_timestamp=None,
    timeframes=None,
    min_trades_by_timeframe=None,
    max_last_trade_lag_seconds_by_timeframe=None,
    min_abs_delta_pct=10.0,
    consensus_ratio=0.60,
    continuity_checkpoint=None,
):
    """Build closed trade candles and analyze CVD; first partial bucket never votes.

    CVD votes require a matching explicit checkpoint from the Kraken collector.
    Without it, the report is diagnostic only and all timeframe continuity flags
    remain false, even if IDs in the local journal are sequential.
    """
    now = time.time() if now_timestamp is None else _epoch(now_timestamp)
    if not math.isfinite(float(now)) or float(now) < 0:
        raise ValueError("now_timestamp must be finite and non-negative")

    journal = load_normalized_trade_journal(path)
    trades = journal["trades"]
    continuity_verified = _validate_continuity_checkpoint(
        continuity_checkpoint, journal
    )

    if timeframes is None:
        requested = list(TIMEFRAME_SECONDS)
    elif isinstance(timeframes, (list, tuple)):
        requested = list(timeframes)
    else:
        raise ValueError("timeframes must be a non-empty list or tuple")

    if not requested or any(not isinstance(item, str) for item in requested):
        raise ValueError("timeframes must contain non-empty timeframe strings")
    if any(not item for item in requested) or len(set(requested)) != len(requested):
        raise ValueError("timeframes must be a non-empty unique list")
    unknown = sorted(set(requested) - set(TIMEFRAME_SECONDS))
    if unknown:
        raise ValueError("unsupported timeframes: " + ", ".join(unknown))

    candles_by_timeframe = {}
    trades_by_timeframe = {}
    continuity = {}
    diagnostics = {}

    for timeframe in requested:
        interval = TIMEFRAME_SECONDS[timeframe]
        try:
            built = build_trade_candles(trades, interval, now)
        except ValueError as exc:
            diagnostics[timeframe] = {
                "status": "INSUFFICIENT_DATA",
                "reason": str(exc),
                "available": False,
            }
            continue

        # The first bucket may predate journal collection; never let it vote.
        if len(built["candles"]) < 2:
            diagnostics[timeframe] = {
                "status": "INSUFFICIENT_FULL_CANDLES",
                "available": False,
                "built_candles": len(built["candles"]),
            }
            continue

        candles = built["candles"][1:]
        coverage_start = candles[0][0]
        coverage_end = candles[-1][0] + interval
        frame_trades = [
            trade for trade in built["trades"]
            if coverage_start <= _epoch(trade["timestamp"]) < coverage_end
        ]

        candles_by_timeframe[timeframe] = candles
        trades_by_timeframe[timeframe] = frame_trades
        continuity[timeframe] = continuity_verified
        diagnostics[timeframe] = {
            "status": (
                "READY_FOR_CVD_ANALYSIS" if continuity_verified
                else "CONTINUITY_UNVERIFIED"
            ),
            "available": continuity_verified,
            "interval_seconds": interval,
            "closed_candles": len(candles),
            "trade_count": len(frame_trades),
            "first_candle_timestamp": coverage_start,
            "last_candle_timestamp": candles[-1][0],
            "excluded_initial_partial_candle": True,
            "feed_continuity_verified": continuity_verified,
        }

    if not candles_by_timeframe:
        return {
            "status": "INSUFFICIENT_DATA",
            "symbol": journal["symbol"],
            "journal": journal,
            "timeframe_diagnostics": diagnostics,
            "feed_continuity_verified": False,
            "research_only": True,
            "execution_enabled": False,
            "live_orders_placed": False,
        }

    report = analyze_multi_timeframe_cvd(
        candles_by_timeframe,
        trades_by_timeframe,
        continuity,
        min_trades_by_timeframe=min_trades_by_timeframe,
        max_last_trade_lag_seconds_by_timeframe=max_last_trade_lag_seconds_by_timeframe,
        min_abs_delta_pct=min_abs_delta_pct,
        consensus_ratio=consensus_ratio,
    )

    return {
        "status": report["status"],
        "symbol": journal["symbol"],
        "journal": journal,
        "timeframe_diagnostics": diagnostics,
        "multi_timeframe_cvd": report,
        "feed_continuity_verified": continuity_verified,
        "research_only": True,
        "execution_enabled": False,
        "live_orders_placed": False,
        "limitations": [
            "Sequential IDs prove continuity only from the first recorded journal event.",
            "CVD votes require an explicit matching checkpoint from the Kraken feed adapter.",
            "The checkpoint is an external collector assertion, not cryptographic proof.",
            "The first potentially partial candle is excluded from every timeframe.",
            "An empty or stale candle cannot provide a valid CVD vote.",
            "This report is research data, not a validated trading strategy.",
        ],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Read-only Kraken multi-timeframe CVD research"
    )
    parser.add_argument("--trade-log", required=True)
    parser.add_argument("--timeframes", default="1m,5m,15m,1h,4h,1d")
    args = parser.parse_args()
    result = analyze_trade_journal(
        args.trade_log,
        timeframes=[item.strip() for item in args.timeframes.split(",") if item.strip()],
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
