"""Evidence-based comparison of the BTC and XAUUSD forward paper ledgers.

Read-only: this report never changes strategies, ledgers, risk limits, or orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "dual_portfolio.json"
LEDGERS = {
    "BTC": ROOT / "state" / "btc_10usd_rsi14_mean_reversion.json",
    "XAUUSD": ROOT / "state" / "xauusd_10usd_ema_trend.json",
}
OUTPUT = ROOT / "research" / "paper_learning" / "latest_report.json"
MIN_REVIEW_TRADES = 10


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + " must be a finite number")
    return float(value)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read required JSON file: " + str(path)) from exc


def summarize_market(symbol, sleeve, ledger):
    trades = ledger.get("trades")
    if not isinstance(trades, list):
        raise ValueError(symbol + " ledger trades must be a list")

    pnls = []
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict) or "pnl_usd" not in trade:
            raise ValueError(symbol + " trade " + str(index) + " is invalid")
        pnls.append(_finite(trade["pnl_usd"], symbol + " trade PnL"))

    wins = [value for value in pnls if value > 0]
    losses = [-value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    count = len(pnls)
    win_rate = (len(wins) / count * 100.0) if count else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    equity = _finite(sleeve.get("equity_usd"), symbol + " equity")
    initial = _finite(sleeve.get("initial_equity_usd"), symbol + " initial equity")
    if initial <= 0:
        raise ValueError(symbol + " initial equity must be positive")
    drawdown = _finite(sleeve.get("max_drawdown_pct", 0.0), symbol + " drawdown")
    if not 0 <= drawdown <= 100:
        raise ValueError(symbol + " drawdown must be between 0 and 100")

    if count < MIN_REVIEW_TRADES:
        review_status = "COLLECTING_SAMPLE"
        next_action = "CONTINUE_PAPER_TEST"
    elif equity <= initial or (profit_factor is not None and profit_factor < 1.0):
        review_status = "REVIEW_REQUIRED"
        next_action = "FLAG_FOR_HUMAN_STRATEGY_REVIEW"
    else:
        review_status = "SAMPLE_READY_FOR_HUMAN_REVIEW"
        next_action = "HUMAN_REVIEW_ONLY"

    return {
        "market": symbol,
        "strategy": sleeve.get("strategy", ledger.get("strategy", "UNKNOWN")),
        "status": sleeve.get("status", "UNKNOWN"),
        "closed_trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 4) if win_rate is not None else None,
        "gross_profit_usd": round(gross_profit, 6),
        "gross_loss_usd": round(gross_loss, 6),
        "net_closed_trade_pnl_usd": round(sum(pnls), 6),
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
        "equity_usd": round(equity, 4),
        "initial_equity_usd": round(initial, 4),
        "return_pct": round((equity / initial - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(drawdown, 4),
        "review_status": review_status,
        "next_action": next_action,
    }


def build_report(snapshot, btc_ledger, gold_ledger, generated_at=None):
    if not isinstance(snapshot, dict):
        raise ValueError("Portfolio snapshot must be an object")
    if snapshot.get("paper_only") is not True or snapshot.get("live_trading_enabled") is not False:
        raise ValueError("Safety gate failed: report requires paper_only=true and live_trading_enabled=false")
    btc = snapshot.get("btc")
    gold = snapshot.get("gold")
    if not isinstance(btc, dict) or not isinstance(gold, dict):
        raise ValueError("Snapshot must contain BTC and Gold sleeves")

    markets = {
        "BTC": summarize_market("BTC", btc, btc_ledger),
        "XAUUSD": summarize_market("XAUUSD", gold, gold_ledger),
    }
    both_reviewable = all(
        item["closed_trades"] >= MIN_REVIEW_TRADES for item in markets.values()
    )
    return {
        "schema_version": 1,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_PAPER_RESEARCH",
        "paper_only": True,
        "live_trading_enabled": False,
        "minimum_trades_for_human_review": MIN_REVIEW_TRADES,
        "markets": markets,
        "comparison": {
            "status": "DESCRIPTIVE_SAMPLE_AVAILABLE" if both_reviewable else "INSUFFICIENT_FORWARD_SAMPLE",
            "both_markets_have_minimum_sample": both_reviewable,
            "note": "BTC and XAUUSD use different instruments and strategies. Metrics are shown side by side; this report does not declare a winner or infer future performance.",
        },
        "governance": {
            "strategy_auto_changes": False,
            "ledger_mutation": False,
            "risk_limit_changes": False,
            "dashboard_modified": False,
            "orders_submitted": False,
        },
    }


def write_report(snapshot_path=SNAPSHOT, btc_path=LEDGERS["BTC"],
                 gold_path=LEDGERS["XAUUSD"], output_path=OUTPUT):
    snapshot = _read_json(snapshot_path)
    btc_ledger = _read_json(btc_path)
    gold_ledger = _read_json(gold_path)
    report = build_report(snapshot, btc_ledger, gold_ledger)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(target.parent),
            prefix="." + target.name + ".", suffix=".tmp", delete=False
        ) as handle:
            temporary = handle.name
            json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--btc-ledger", type=Path, default=LEDGERS["BTC"])
    parser.add_argument("--gold-ledger", type=Path, default=LEDGERS["XAUUSD"])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = write_report(args.snapshot, args.btc_ledger, args.gold_ledger, args.output)
    print(json.dumps({
        "status": report["comparison"]["status"],
        "btc_closed_trades": report["markets"]["BTC"]["closed_trades"],
        "gold_closed_trades": report["markets"]["XAUUSD"]["closed_trades"],
        "output": str(args.output),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
