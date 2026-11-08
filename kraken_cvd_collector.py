"""Standalone read-only Kraken Spot WebSocket CVD collector CLI.

This process collects public trade data only. It never places exchange orders.
"""
import argparse
import json
import os
import re
import signal
import sys
import threading

from trade_event_journal import JsonlTradeJournal

from kraken_order_flow import (
    KrakenSpotTradeFeedAdapter,
    KrakenSpotWebSocketRunner,
    PersistentCvdLedger,
    load_cvd_state,
    save_cvd_state_atomic,
)


def default_state_path(pair):
    """Return a filesystem-safe, per-symbol state path."""
    if not isinstance(pair, str) or not pair.strip():
        raise ValueError("pair must be a non-empty string")
    safe_pair = re.sub(r"[^A-Za-z0-9_-]+", "_", pair.strip()).strip("_")
    if not safe_pair:
        raise ValueError("pair does not contain filesystem-safe characters")
    return os.path.join("state", f"kraken_cvd_{safe_pair.lower()}.json")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Collect Kraken public Spot WebSocket v2 trades into a persistent CVD ledger."
    )
    parser.add_argument("--pair", default="BTC/USD", help="Kraken spot pair (default: BTC/USD)")
    parser.add_argument("--state-file", default=None, help="Per-symbol JSON state path")
    parser.add_argument("--trade-log", default=None, help="Optional append-only JSONL raw trade journal path")
    parser.add_argument("--max-trade-log-mb", type=int, default=250, help="Maximum raw trade journal size in MiB")
    parser.add_argument("--timeout", type=float, default=20.0, help="WebSocket receive timeout seconds")
    parser.add_argument("--initial-backoff", type=float, default=1.0, help="Initial reconnect delay seconds")
    parser.add_argument("--max-backoff", type=float, default=30.0, help="Maximum reconnect delay seconds")
    parser.add_argument(
        "--max-reconnect-attempts", type=int, default=0,
        help="Maximum reconnect attempts; 0 means unlimited",
    )
    return parser


def run_collector(args, stop_event, websocket_factory=None):
    pair = args.pair.strip()
    state_path = args.state_file or default_state_path(pair)
    ledger = PersistentCvdLedger(
        symbol=pair,
        state=load_cvd_state(state_path),
    )
    trade_log_path = getattr(args, "trade_log", None)
    journal = None
    if trade_log_path:
        max_mb = getattr(args, "max_trade_log_mb", 250)
        if isinstance(max_mb, bool) or not isinstance(max_mb, int) or max_mb < 1:
            raise ValueError("max_trade_log_mb must be a positive integer")
        journal = JsonlTradeJournal(
            trade_log_path, max_bytes=max_mb * 1024 * 1024
        )
    adapter = KrakenSpotTradeFeedAdapter(
        ledger,
        pair=pair,
        timeout=args.timeout,
        on_accepted_trades=journal.append if journal else None,
    )
    runner = KrakenSpotWebSocketRunner(
        adapter,
        timeout=args.timeout,
        initial_backoff=args.initial_backoff,
        max_backoff=args.max_backoff,
        max_reconnect_attempts=args.max_reconnect_attempts,
    )
    result = runner.run(
        stop_event,
        persist_state=lambda state: save_cvd_state_atomic(state_path, state),
        websocket_factory=websocket_factory,
    )
    if journal:
        result["trade_journal"] = {
            "path": trade_log_path,
            "last_trade_id": journal.last_trade_id,
            "size_bytes": os.path.getsize(trade_log_path) if os.path.exists(trade_log_path) else 0,
        }
    return result


def main(argv=None):
    args = build_parser().parse_args(argv)
    stop_event = threading.Event()

    def request_stop(_signum, _frame):
        stop_event.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, request_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_stop)

    try:
        result = run_collector(args, stop_event)
    except Exception as exc:
        print(
            json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
