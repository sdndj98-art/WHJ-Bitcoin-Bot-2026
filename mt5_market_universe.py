"""Export broker-listed WHJ market universe (FX, metals, commodities, crypto).

Run on Windows with an already configured MT5 terminal:
    python mt5_market_universe.py --output market_universe.json

This only reads the broker's symbol catalog. It does not read balances or place orders.
"""
import argparse
import json
from pathlib import Path

from market_universe import discover_market_universe
from mt5_adapter import MetaTrader5ReadOnly


def main():
    parser = argparse.ArgumentParser(description="Read-only MT5 symbol universe discovery")
    parser.add_argument("--output", default="market_universe.json")
    parser.add_argument("--terminal-path", default=None)
    args = parser.parse_args()

    adapter = MetaTrader5ReadOnly(terminal_path=args.terminal_path)
    try:
        adapter.connect()
        names = adapter.list_symbols()
        universe = discover_market_universe(names)
        universe["symbol_count"] = len(names)
        universe["broker_symbols"] = names
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(universe, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
        print(json.dumps({
            "output": str(target.resolve()),
            "symbol_count": len(names),
            "categories": {key: len(value) for key, value in universe["categories"].items()},
            "orders_sent": False,
            "live_trading_enabled": False,
        }, indent=2))
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
