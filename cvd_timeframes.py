"""Build closed-timeframe trade-flow/CVD bars from the durable Kraken JSONL journal.

This is a read-only research utility. It does not connect to an exchange or place
orders. Empty intervals are intentionally omitted rather than filled with zero.
"""
import argparse
import json
import math
import os
import sys
import time

from kraken_order_flow import _trade_event_timestamp_ns


TIMEFRAMES = {
    "1s": 1,
    "5s": 5,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def read_trade_journal(path):
    """Read normalized JSONL events; fail closed on corruption or truncation."""
    events = []
    with open(path, "rb") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.endswith(b"\\n"):
                raise ValueError(f"incomplete JSONL record at line {line_number}")
            try:
                event = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid JSONL record at line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"record {line_number} must be a JSON object")
            events.append(event)
    return events


def aggregate_trade_events(events, timeframe_seconds, as_of=None):
    """Aggregate ordered normalized trade events into one timeframe.

    CVD is cumulative from the first event in the supplied journal. Bar
    timestamps are UTC Unix seconds; end timestamps are exclusive.
    """
    if isinstance(timeframe_seconds, bool) or not isinstance(timeframe_seconds, int) or timeframe_seconds < 1:
        raise ValueError("timeframe_seconds must be a positive integer")
    if as_of is None:
        as_of_ns = time.time_ns()
    else:
        as_of_ns = _trade_event_timestamp_ns(as_of)

    bars = []
    current = None
    cumulative = 0.0
    previous_id = None
    previous_timestamp_ns = None
    symbol = None
    event_count = 0

    for event in events:
        if not isinstance(event, dict):
            raise ValueError("each trade event must be an object")
        trade_id = event.get("trade_id")
        if isinstance(trade_id, bool) or not str(trade_id).isdigit() or int(trade_id) <= 0:
            raise ValueError("trade_id must be a positive integer")
        trade_id = int(trade_id)
        timestamp_ns = _trade_event_timestamp_ns(event.get("timestamp"))
        price = _number(event.get("price"), "price")
        qty = _number(event.get("qty"), "qty")
        side = event.get("side")
        event_symbol = event.get("symbol")
        if price <= 0 or qty <= 0 or side not in ("buy", "sell"):
            raise ValueError("trade price/qty must be positive and side must be buy or sell")
        if not isinstance(event_symbol, str) or not event_symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if previous_id is not None and trade_id <= previous_id:
            raise ValueError("trade IDs must be strictly increasing; duplicates are not replayed")
        if previous_timestamp_ns is not None and timestamp_ns < previous_timestamp_ns:
            raise ValueError("trade timestamps must be non-decreasing")
        if symbol is not None and event_symbol != symbol:
            raise ValueError("one journal aggregation cannot mix symbols")

        bucket_start_ns = (timestamp_ns // (timeframe_seconds * 1_000_000_000)) * timeframe_seconds * 1_000_000_000
        delta = qty if side == "buy" else -qty
        if current is None or current["bucket_start_ns"] != bucket_start_ns:
            if current is not None:
                bars.append(current)
            start_s = bucket_start_ns // 1_000_000_000
            current = {
                "bucket_start": start_s,
                "bucket_end": start_s + timeframe_seconds,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "buy_volume": 0.0,
                "sell_volume": 0.0,
                "volume": 0.0,
                "trade_count": 0,
                "delta": 0.0,
                "cvd_open": cumulative,
                "cvd_close": cumulative,
                "first_trade_timestamp_ns": timestamp_ns,
                "last_trade_timestamp_ns": timestamp_ns,
                "bucket_start_ns": bucket_start_ns,
            }
        current["high"] = max(current["high"], price)
        current["low"] = min(current["low"], price)
        current["close"] = price
        current["volume"] += qty
        current["trade_count"] += 1
        if side == "buy":
            current["buy_volume"] += qty
        else:
            current["sell_volume"] += qty
        current["delta"] += delta
        cumulative += delta
        current["cvd_close"] = cumulative
        current["last_trade_timestamp_ns"] = timestamp_ns
        previous_id = trade_id
        previous_timestamp_ns = timestamp_ns
        symbol = event_symbol
        event_count += 1

    if current is not None:
        bars.append(current)

    previous_start = None
    output = []
    for bar in bars:
        start = bar["bucket_start"]
        interval_gap = previous_start is not None and start - previous_start > timeframe_seconds
        delta_pct = (bar["delta"] / bar["volume"] * 100.0) if bar["volume"] else 0.0
        output.append({
            "bucket_start": start,
            "bucket_end": bar["bucket_end"],
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "buy_volume": round(bar["buy_volume"], 12),
            "sell_volume": round(bar["sell_volume"], 12),
            "volume": round(bar["volume"], 12),
            "trade_count": bar["trade_count"],
            "delta": round(bar["delta"], 12),
            "delta_pct": round(delta_pct, 6),
            "cvd_open": round(bar["cvd_open"], 12),
            "cvd_close": round(bar["cvd_close"], 12),
            "first_trade_timestamp": bar["first_trade_timestamp_ns"] / 1_000_000_000,
            "last_trade_timestamp": bar["last_trade_timestamp_ns"] / 1_000_000_000,
            "is_closed": bar["bucket_end"] * 1_000_000_000 <= as_of_ns,
            "gap_before": interval_gap,
        })
        previous_start = start

    return {
        "status": "OK" if output else "EMPTY",
        "symbol": symbol,
        "timeframe_seconds": timeframe_seconds,
        "event_count": event_count,
        "bar_count": len(output),
        "first_bucket": output[0]["bucket_start"] if output else None,
        "last_bucket": output[-1]["bucket_start"] if output else None,
        "last_cvd": output[-1]["cvd_close"] if output else 0.0,
        "bars": output,
        "data_policy": {
            "empty_intervals": "omitted_not_filled",
            "current_interval": "marked_is_closed_false_until_bucket_end",
            "cvd_scope": "cumulative_from_first_event_in_supplied_journal",
            "source": "single_exchange_trade_journal",
            "research_only": True,
            "execution_enabled": False,
        },
    }


def aggregate_all_timeframes(events, as_of=None, timeframes=None):
    """Return independent native-timeframe bars from one event journal."""
    selected = timeframes or TIMEFRAMES
    if not isinstance(selected, dict) or not selected:
        raise ValueError("timeframes must be a non-empty name-to-seconds mapping")
    materialized = list(events)
    result = {}
    for name, seconds in selected.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("timeframe names must be non-empty strings")
        result[name] = aggregate_trade_events(materialized, seconds, as_of=as_of)
    return {
        "schema_version": 1,
        "timeframes": result,
        "limitations": [
            "This is Kraken venue-specific trade flow, not consolidated market-wide volume.",
            "A trade journal started mid-session has no CVD history before its first event.",
            "No-trade intervals are omitted; absence of a bar is not zero volume.",
            "CVD is not order-book depth and does not prove hidden liquidity or spoofing.",
            "These bars are research inputs, not standalone trade signals.",
        ],
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Replay Kraken raw trades into multi-timeframe CVD bars.")
    parser.add_argument("--trade-log", default="state/kraken_btc_usd_trades.jsonl")
    parser.add_argument("--output", default="state/kraken_cvd_timeframes.json")
    parser.add_argument("--as-of", default=None, help="Optional ISO-8601 timestamp with timezone")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        events = read_trade_journal(args.trade_log)
        report = aggregate_all_timeframes(events, as_of=args.as_of)
        directory = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(directory, exist_ok=True)
        temporary = args.output + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.output)
        print(json.dumps({
            "status": "OK",
            "trade_log": args.trade_log,
            "output": args.output,
            "events": len(events),
            "timeframes": {name: data["bar_count"] for name, data in report["timeframes"].items()},
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
