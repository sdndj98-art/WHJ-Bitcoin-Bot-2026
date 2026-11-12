"""CLI for advancing isolated forward-only GC=F gold shadow-paper sleeves.

Run periodically from Termux or a scheduled local task. The first run only seeds
indicator warm-up; it does not book historical trades. No broker/order imports.
"""
import argparse
import json
from pathlib import Path

from gold_forward_shadow import (
    STRATEGIES,
    advance_gold_shadow_state,
    seed_gold_shadow_state,
    write_state_atomically,
)
from gold_market_data import load_gold_daily


def run_gold_shadow(state_dir="data/gold_shadow", bars=None):
    rows = load_gold_daily(period="10y") if bars is None else bars
    root = Path(state_dir)
    summaries = []
    for strategy in STRATEGIES:
        path = root / (strategy + ".json")
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            updated = advance_gold_shadow_state(rows, state)
            action = "advanced" if updated["last_processed_timestamp"] != state["last_processed_timestamp"] else "unchanged"
        else:
            updated = seed_gold_shadow_state(rows, strategy)
            action = "seeded_no_historical_trades"
        write_state_atomically(updated, path)
        summaries.append({
            "strategy": strategy,
            "action": action,
            "state_file": str(path),
            "last_processed_timestamp": updated["last_processed_timestamp"],
            "equity_usd": round(updated["equity_usd"], 4),
            "return_pct": updated.get("return_pct", 0.0),
            "completed_trades": updated["completed_trades"],
            "max_drawdown_pct": round(updated["max_drawdown_pct"], 4),
            "risk_pause_reasons": list(updated["risk_pause_reasons"]),
            "live_trading_eligible": False,
        })
    return {
        "asset": "GC=F_COMEX_gold_futures_reference_not_spot_XAUUSD",
        "mode": "FORWARD_ONLY_SHADOW_PAPER",
        "candle_count": len(rows),
        "summaries": summaries,
        "live_orders": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Advance isolated forward-only GC=F gold shadow paper sleeves")
    parser.add_argument("--state-dir", default="data/gold_shadow", help="Directory for separate gold shadow JSON ledgers")
    args = parser.parse_args()
    report = run_gold_shadow(args.state_dir)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
