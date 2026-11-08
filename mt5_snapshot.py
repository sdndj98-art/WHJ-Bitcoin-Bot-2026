"""Create a privacy-safe MT5 market snapshot and optional local paper ledger.

The script reads completed broker candles and quotes. It never submits MT5 orders.
Paper accounts are local virtual ledgers and are updated only with --update-paper-ledger.
"""
import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from market_scanner import scan_btc_market
from mt5_adapter import MetaTrader5ReadOnly

TIMEFRAMES = {
    "1h": ("TIMEFRAME_H1", 3600),
    "4h": ("TIMEFRAME_H4", 14400),
    "6h": ("TIMEFRAME_H6", 21600),
}
MAX_BARS = 10000


def _finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _quality(rows, interval_seconds, now_timestamp):
    timestamps = [int(row["timestamp"]) for row in rows]
    gaps = sum(
        max(0, (current - previous) // interval_seconds - 1)
        for previous, current in zip(timestamps, timestamps[1:])
        if (current - previous) % interval_seconds == 0
    )
    irregular_intervals = any(
        (current - previous) % interval_seconds != 0
        for previous, current in zip(timestamps, timestamps[1:])
    )
    age_minutes = (now_timestamp - (timestamps[-1] + interval_seconds)) / 60.0
    fresh = -1.0 <= age_minutes <= (interval_seconds / 60.0 * 2 + 10)
    aligned = all(ts % interval_seconds == 0 for ts in timestamps)
    reasons = []
    if gaps or irregular_intervals:
        reasons.append("missing_or_irregular_completed_bars")
    if not fresh:
        reasons.append("stale_or_future_bar")
    if not aligned:
        reasons.append("bar_time_not_utc_aligned")
    if len(rows) < 51:
        reasons.append("insufficient_history_for_scanner")
    return {
        "quality_status": "HEALTHY" if not reasons else "BLOCKED",
        "paper_execution_allowed": not reasons,
        "bar_count": len(rows),
        "missing_bars": gaps,
        "latest_bar_age_minutes": round(age_minutes, 2),
        "latest_bar_fresh": fresh,
        "utc_aligned": aligned,
        "block_reasons": reasons,
    }


def _scanner_rows(rows):
    # MT5 tick volume is a broker-side activity proxy, not centralized exchange volume.
    # The scanner's eighth field is a trade-count placeholder and is deliberately zero.
    return [
        [row["timestamp"], row["open"], row["high"], row["low"], row["close"],
         0.0, row["tick_volume"], 0]
        for row in rows
    ]


def build_mt5_snapshot(adapter, symbol, count=300, now_timestamp=None,
                       update_paper_ledger=False, state_dir="mt5_paper_state"):
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("A non-empty broker symbol is required")
    symbol = symbol.strip()
    if isinstance(count, bool) or not isinstance(count, int) or not 51 <= count <= MAX_BARS:
        raise ValueError("count must be an integer between 51 and 10000")
    now = datetime.now(timezone.utc).timestamp() if now_timestamp is None else _finite(
        now_timestamp, "current timestamp"
    )

    # Ignore the returned account summary. It contains private balance/equity details.
    adapter.connect()
    quote = adapter.get_quote(symbol)
    if quote.get("symbol") != symbol:
        raise ValueError("MT5 quote symbol does not match the requested symbol")
    bid = _finite(quote.get("bid"), "bid")
    ask = _finite(quote.get("ask"), "ask")
    if bid <= 0 or ask < bid:
        raise ValueError("MT5 returned an invalid quote")

    frames = {}
    raw_by_frame = {}
    for label, (mt5_timeframe, interval_seconds) in TIMEFRAMES.items():
        rows = adapter.fetch_closed_rates(symbol, mt5_timeframe, count)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"No completed MT5 candles available for {label}")
        quality = _quality(rows, interval_seconds, now)
        scanner = None
        if quality["quality_status"] == "HEALTHY":
            try:
                scanner = scan_btc_market(
                    _scanner_rows(rows), quality, interval_hours=interval_seconds // 3600,
                    market_label=symbol
                )
            except ValueError as exc:
                scanner = {
                    "status": "BLOCKED_INVALID_OR_INSUFFICIENT_DATA",
                    "reason": str(exc),
                    "paper_candidate_only": True,
                    "live_execution_enabled": False,
                }
        else:
            scanner = {
                "status": "BLOCKED_DATA_QUALITY",
                "reason": ", ".join(quality["block_reasons"]),
                "paper_candidate_only": True,
                "live_execution_enabled": False,
            }
        raw_by_frame[label] = rows
        frames[label] = {
            "timeframe": label,
            "interval_seconds": interval_seconds,
            "quality": quality,
            "scanner": scanner,
            "candles": rows[-120:],
        }

    paper = {
        "mode": "NOT_UPDATED",
        "enabled": False,
        "note": "No MT5 paper ledger update was requested. No broker orders are sent.",
    }
    if update_paper_ledger:
        if not (symbol.upper().startswith("BTC") or symbol.upper().startswith("XBT")):
            raise ValueError("The current MT5 paper portfolio supports BTC/XBT symbols only")
        hourly = raw_by_frame["1h"]
        hourly_quality = frames["1h"]["quality"]
        if hourly_quality["quality_status"] != "HEALTHY":
            paper = {
                "mode": "PAUSED_DATA_QUALITY",
                "enabled": True,
                "note": "Paper ledger was not updated because MT5 hourly data quality is blocked.",
            }
        else:
            from paper_account import run_paper_portfolio
            portfolio = run_paper_portfolio(_scanner_rows(hourly), state_dir=state_dir)
            paper = {
                "mode": portfolio["mode"],
                "enabled": True,
                "execution": "LOCAL_VIRTUAL_LEDGER_ONLY",
                "symbol": symbol,
                "accounts": {
                    name: {
                        key: value.get(key)
                        for key in (
                            "initial_cash_usd", "equity_after_estimated_exit_costs_usd",
                            "return_pct", "max_drawdown_pct", "completed_trades",
                            "win_rate_pct", "profit_factor", "fees_paid_usd",
                            "open_position", "paused_for_drawdown", "daily_loss_paused",
                            "paused_for_loss_streak", "paused_for_strategy_health",
                            "last_processed_candle_timestamp",
                        )
                        if key in value
                    }
                    for name, value in portfolio["accounts"].items()
                },
                "note": "Virtual local paper accounts using MT5 completed candles. No MT5 orders are submitted.",
            }

    return {
        "schema_version": 1,
        "source": "MetaTrader 5",
        "mode": "MT5_MARKET_DATA_PAPER_ONLY",
        "generated_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "symbol": symbol,
        "quote": {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "spread": round(ask - bid, 12),
            "timestamp": int(_finite(quote.get("time"), "quote timestamp")),
        },
        "timeframes": frames,
        "paper_trading": paper,
        "privacy": {
            "account_login_included": False,
            "account_balance_included": False,
            "account_equity_included": False,
            "broker_server_included": False,
        },
        "safety": {
            "orders_sent": False,
            "live_trading_enabled": False,
            "mode": "READ_ONLY_DATA_AND_LOCAL_PAPER_LEDGER",
        },
        "limitations": [
            "MT5 tick volume is broker-specific and is not centralized exchange volume.",
            "Broker symbols, trading sessions, spreads and candle history can differ.",
            "Scanner outputs are research labels, not trade instructions or profitability evidence.",
            "Paper ledger fills are simulated and do not reproduce broker execution.",
        ],
    }


def write_snapshot(snapshot, output_path):
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(target.parent),
            prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(snapshot, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Read-only MT5 snapshot and optional local paper ledger")
    parser.add_argument("--symbol", default="BTCUSD", help="Exact symbol name shown by your broker")
    parser.add_argument("--bars", type=int, default=300)
    parser.add_argument("--output", default="mt5_snapshot.json")
    parser.add_argument(
        "--update-paper-ledger", action="store_true",
        help="Update separate local virtual BTC paper accounts; never sends broker orders"
    )
    parser.add_argument("--state-dir", default="mt5_paper_state")
    parser.add_argument("--terminal-path", default=None)
    args = parser.parse_args()
    adapter = MetaTrader5ReadOnly(terminal_path=args.terminal_path)
    try:
        snapshot = build_mt5_snapshot(
            adapter, args.symbol, args.bars,
            update_paper_ledger=args.update_paper_ledger,
            state_dir=args.state_dir,
        )
        write_snapshot(snapshot, args.output)
        print(json.dumps({
            "output": str(Path(args.output).resolve()),
            "symbol": args.symbol,
            "mode": snapshot["mode"],
            "paper_mode": snapshot["paper_trading"]["mode"],
            "orders_sent": False,
            "live_trading_enabled": False,
        }, indent=2))
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
