"""Build a reproducible CVD/price research report from verified local Kraken files.

Input candles must be completed Kraken OHLCV rows. The trade journal must be
the exact gap-free journal produced by kraken_cvd_collector.py, with its
matching checkpoint. This tool is offline/read-only and never places orders.
"""
import argparse
import json
import math
import os
import tempfile
from datetime import datetime

from cvd_candle_research import align_trade_flow_to_candles
from cvd_entry_filter_lab import run_cvd_entry_filter_lab
from trade_journal_checkpoint import validate_continuity_checkpoint


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_trade_journal(path):
    events = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n"):
                raise ValueError(f"trade journal has incomplete line {line_number}")
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid trade journal JSON at line {line_number}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"trade journal line {line_number} is not an object")
            events.append(item)
    if not events:
        raise ValueError("trade journal is empty")
    return events


def build_research_report(candles, trades, checkpoint, trade_log_path, pair,
                          as_of_timestamp, interval_seconds=3600,
                          fee=0.001, slippage=0.0005):
    """Validate continuity and completed candle coverage before evaluating."""
    if not isinstance(pair, str) or not pair.strip():
        raise ValueError("pair must be non-empty")
    if isinstance(as_of_timestamp, bool) or not isinstance(as_of_timestamp, (int, float)):
        raise ValueError("as_of_timestamp must be a Unix timestamp")
    if (not isinstance(as_of_timestamp, (int, float))
            or not math.isfinite(as_of_timestamp) or as_of_timestamp < 0):
        raise ValueError("as_of_timestamp must be a finite non-negative Unix timestamp")
    metadata = validate_continuity_checkpoint(
        checkpoint, trade_log_path, pair.strip(), checkpoint.get("last_trade_id")
        if isinstance(checkpoint, dict) else None
    )
    journal_events = _read_trade_journal(trade_log_path)
    if trades != journal_events:
        raise ValueError("trade events must be read from the exact checkpointed journal")
    if not isinstance(candles, list) or not candles:
        raise ValueError("candles must be a non-empty Kraken OHLCV list")
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or interval_seconds <= 0:
        raise ValueError("interval_seconds must be a positive integer")
    if any(not isinstance(row, (list, tuple)) or len(row) < 8 for row in candles):
        raise ValueError("each candle must contain all eight Kraken OHLCV fields")
    last_start = candles[-1][0]
    if (isinstance(last_start, bool) or not isinstance(last_start, (int, float))
            or not float(last_start).is_integer()):
        raise ValueError("last candle timestamp must be an integer Unix timestamp")
    if float(last_start) + interval_seconds > float(as_of_timestamp):
        raise ValueError("last candle is not completed at the supplied as-of timestamp")

    aligned = align_trade_flow_to_candles(
        candles, trades, interval_seconds=interval_seconds,
        continuity_verified=True,
    )
    # The initial WebSocket snapshot establishes a continuity baseline, but
    # cannot prove that the first candle was captured from its opening second.
    # Conservatively invalidate that entire first trade-containing candle.
    first_trade_timestamp = trades[0].get("timestamp")
    if isinstance(first_trade_timestamp, bool):
        raise ValueError("first journal trade timestamp is invalid")
    if isinstance(first_trade_timestamp, (int, float)):
        first_trade_epoch = float(first_trade_timestamp)
    elif isinstance(first_trade_timestamp, str):
        try:
            parsed = datetime.fromisoformat(first_trade_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("first journal trade timestamp is invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("first journal trade timestamp must include timezone")
        first_trade_epoch = parsed.timestamp()
    else:
        raise ValueError("first journal trade timestamp is invalid")
    if not math.isfinite(first_trade_epoch) or first_trade_epoch < 0:
        raise ValueError("first journal trade timestamp is invalid")
    partial_bucket_start = int(first_trade_epoch // interval_seconds) * interval_seconds
    for bar in aligned["bars"]:
        if bar["candle_timestamp"] <= partial_bucket_start:
            bar["available"] = False
            bar["status"] = "PARTIAL_INITIAL_CANDLE"
            bar["bullish_flow_confirmation"] = False
            bar["bearish_flow_confirmation"] = False
            bar["bullish_absorption_divergence"] = False
            bar["bearish_absorption_divergence"] = False
    aligned["available_bars"] = sum(bar["available"] for bar in aligned["bars"])
    aligned["status"] = (
        "OK" if aligned["available_bars"] == aligned["total_bars"]
        else "PARTIAL_OR_UNAVAILABLE"
    )
    prices = [float(row[4]) for row in candles]
    timestamps = [int(row[0]) for row in candles]
    report = run_cvd_entry_filter_lab(
        prices, timestamps, aligned["bars"], fee=fee, slippage=slippage
    )
    report["dataset"] = {
        "pair": pair.strip(),
        "interval_seconds": interval_seconds,
        "candle_count": len(candles),
        "trade_event_count": len(trades),
        "first_trade_id": metadata["first_trade_id"],
        "last_trade_id": metadata["last_trade_id"],
        "journal_sha256": metadata["journal_sha256"],
        "journal_continuity_checkpoint_validated": True,
        "as_of_timestamp": int(as_of_timestamp),
        "last_candle_completed": True,
        "available_cvd_bars": aligned["available_bars"],
        "total_cvd_bars": aligned["total_bars"],
        "availability_pct": round(
            aligned["available_bars"] / aligned["total_bars"] * 100.0, 2
        ),
        "limitations": [
            "Checkpoint integrity binds the report to the local journal bytes; it is not a cryptographic signature.",
            "Continuity covers only the captured Kraken feed interval, not earlier exchange history.",
            "The first trade-containing candle is excluded because the initial snapshot cannot prove full-candle coverage.",
            "CVD is venue-specific and cannot represent consolidated market-wide order flow.",
            "Unavailable or stale candle flow is excluded from new entries by the research filter.",
        ],
    }
    return report


def write_json_atomic(path, payload):
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".whj-cvd-report-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build a read-only EMA/CVD research report from verified Kraken files."
    )
    parser.add_argument("--candles-json", required=True, help="JSON array of completed Kraken OHLCV rows")
    parser.add_argument("--trade-log", required=True, help="Gap-free JSONL journal from kraken_cvd_collector.py")
    parser.add_argument("--checkpoint", required=True, help="Matching collector continuity checkpoint JSON")
    parser.add_argument("--pair", default="BTC/USD")
    parser.add_argument("--as-of", required=True, type=int, help="Unix timestamp proving the final candle has closed")
    parser.add_argument("--interval-seconds", type=int, default=3600)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--output", default="reports/cvd_entry_filter_report.json")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    candles = _read_json(args.candles_json)
    trades = _read_trade_journal(args.trade_log)
    checkpoint = _read_json(args.checkpoint)
    report = build_research_report(
        candles, trades, checkpoint, args.trade_log, args.pair, args.as_of,
        interval_seconds=args.interval_seconds, fee=args.fee, slippage=args.slippage,
    )
    write_json_atomic(args.output, report)
    print(json.dumps({
        "status": "REPORT_WRITTEN",
        "output": args.output,
        "sample_count": report["sample_count"],
        "available_cvd_bars": report["dataset"]["available_cvd_bars"],
        "total_cvd_bars": report["dataset"]["total_cvd_bars"],
        "promotion_status": report["promotion_status"],
        "research_only": True,
        "execution_enabled": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
