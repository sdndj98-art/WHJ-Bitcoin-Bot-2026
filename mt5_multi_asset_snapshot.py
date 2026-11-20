"""Build a broker quote snapshot for WHJ's isolated multi-asset paper ledger.

Signals and non-USD profit-currency conversions are explicit input data; this
script never invents them. It reads MT5 only and does not submit orders.
"""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from market_universe import discover_market_universe, classify_symbol
from mt5_adapter import MetaTrader5ReadOnly


def _positive(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite and positive")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite and positive") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return number


def build_snapshot(adapter, config, *, now_timestamp=None, max_quote_age_seconds=120):
    if not isinstance(config, dict):
        raise ValueError("signals configuration must be a JSON object")
    signals = config.get("signals", {})
    conversions = config.get("quote_to_usd", {})
    if not isinstance(signals, dict) or not isinstance(conversions, dict):
        raise ValueError("signals and quote_to_usd must be objects")
    now = (datetime.now(timezone.utc).timestamp() if now_timestamp is None
           else _positive(now_timestamp, "now_timestamp"))
    max_age = _positive(max_quote_age_seconds, "max_quote_age_seconds")
    adapter.connect()
    symbols = adapter.list_symbols()
    universe = discover_market_universe(symbols)
    quotes, accepted_signals, healthy, skipped = {}, {}, [], []

    for category, listed in universe["categories"].items():
        if category not in ("FOREX", "CRYPTO", "PRECIOUS_METAL", "COMMODITY"):
            continue
        for symbol in listed:
            signal = str(signals.get(symbol, "HOLD")).upper()
            if signal not in ("BUY", "SELL", "HOLD"):
                signal = "HOLD"
            try:
                quote = adapter.get_quote(symbol)
                spec = adapter.get_instrument_spec(symbol)
                bid = _positive(quote.get("bid"), f"{symbol} bid")
                ask = _positive(quote.get("ask"), f"{symbol} ask")
                if ask < bid:
                    raise ValueError("ask is below bid")
                timestamp = _positive(quote.get("time"), f"{symbol} quote time")
                age = now - timestamp
                if age < -60 or age > max_age:
                    raise ValueError("quote is stale or from the future")
                contract_size = _positive(spec.get("contract_size"), f"{symbol} contract size")
                profit_currency = str(spec.get("profit_currency", "")).upper()
                conversion = conversions.get(symbol)
                if conversion is None and profit_currency == "USD":
                    conversion = 1.0
                if conversion is None:
                    raise ValueError(f"missing quote_to_usd conversion for profit currency {profit_currency or 'unknown'}")
                conversion = _positive(conversion, f"{symbol} quote_to_usd")
                quotes[symbol] = {
                    "bid": bid, "ask": ask, "timestamp": int(timestamp),
                    "contract_size": contract_size, "quote_to_usd": conversion,
                    "asset_class": category, "profit_currency": profit_currency,
                }
                accepted_signals[symbol] = signal
                if signal in ("BUY", "SELL", "HOLD") and age <= max_age:
                    healthy.append(symbol)
            except (ValueError, RuntimeError, TypeError) as exc:
                skipped.append({"symbol": symbol, "reason": str(exc)})

    return {
        "schema_version": 1,
        "source": "MT5_READ_ONLY_QUOTES",
        "generated_timestamp": int(now),
        "quotes": quotes,
        "signals": accepted_signals,
        "healthy_symbols": sorted(healthy),
        "universe_counts": {key: len(value) for key, value in universe["categories"].items()},
        "skipped_symbols": skipped,
        "paper_only": True,
        "live_trading_enabled": False,
        "orders_submitted": False,
        "notes": [
            "Symbols are limited to instruments returned by the connected broker.",
            "Signals are supplied explicitly; absent symbols default to HOLD.",
            "Only USD profit currency is auto-converted. Other conversions must be supplied and verified by the operator.",
            "Broker contract size is read from MT5 instrument metadata; no broker orders are sent.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Read MT5 quotes for broker-listed WHJ multi-asset paper markets.")
    parser.add_argument("--signals", default="whj_market_signals.json",
                        help="JSON file with signals and quote_to_usd conversion map")
    parser.add_argument("--output", default="multi_asset_snapshot.json")
    parser.add_argument("--max-quote-age-seconds", type=int, default=120)
    parser.add_argument("--terminal-path", default=None)
    args = parser.parse_args()
    with open(args.signals, encoding="utf-8") as handle:
        config = json.load(handle)
    adapter = MetaTrader5ReadOnly(terminal_path=args.terminal_path)
    try:
        snapshot = build_snapshot(adapter, config,
                                  max_quote_age_seconds=args.max_quote_age_seconds)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
        print(json.dumps({
            "output": str(target.resolve()),
            "symbols_quoted": len(snapshot["quotes"]),
            "symbols_skipped": len(snapshot["skipped_symbols"]),
            "orders_submitted": False,
            "live_trading_enabled": False,
        }, indent=2))
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
