"""Read-only integrity and performance summary for local forward-paper ledgers.

This utility never imports trading modules, writes files, or places orders.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

CANDIDATES = {
    "1d_sma_trend": "paper_qualified_1d_sma_trend.json",
    "6h_ema50_200_regime": "paper_qualified_6h_ema50_200_regime.json",
    "6h_ema_pullback_trend": "paper_qualified_6h_ema_pullback_trend.json",
    "4h_ema20_50_daily_sma200_atr3": "paper_qualified_4h_ema20_50_daily_sma200_atr3.json",
}


def _finite_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field} must be finite")
    return float(value)


def _read_ledger(root: Path, filename: str):
    path = root / filename
    if path.is_symlink():
        raise ValueError(f"Refusing symlink ledger: {filename}")
    if not path.exists():
        return None, "MISSING"
    if not path.is_file():
        raise ValueError(f"Ledger is not a regular file: {filename}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read ledger {filename}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Ledger root must be an object: {filename}")
    return payload, "OK"


def _trade_stats(trades):
    if not isinstance(trades, list):
        raise ValueError("trades must be a list")
    pnls = []
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            raise ValueError(f"trade {index} must be an object")
        if "pnl_usd" in trade:
            pnls.append(_finite_number(trade["pnl_usd"], f"trades[{index}].pnl_usd"))
    wins = sum(pnl > 0 for pnl in pnls)
    losses = sum(pnl < 0 for pnl in pnls)
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = -sum(pnl for pnl in pnls if pnl < 0)
    return {
        "trades_with_realized_pnl": len(pnls),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / len(pnls) * 100, 2) if pnls else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if not gross_profit else "INF"),
        "realized_pnl_usd": round(sum(pnls), 4),
    }


def audit_ledger(root: Path, name: str, filename: str):
    state, status = _read_ledger(root, filename)
    if state is None:
        return {"name": name, "file": filename, "status": status}
    result = {"name": name, "file": filename, "status": status}
    for key in ("strategy", "last_timestamp", "last_processed_timestamp",
                "processed_new_candles", "completed_trades", "wins", "losses",
                "paused", "pause_reason", "pending_action"):
        if key in state:
            result[key] = state[key]
    if "trades" in state:
        result.update(_trade_stats(state["trades"]))
    for key in ("initial_cash", "cash", "btc", "equity", "peak_equity",
                "max_drawdown_pct", "fees_paid", "quantity"):
        if key in state:
            result[key] = round(_finite_number(state[key], key), 8)
    if "initial_cash" in state and "cash" in state:
        initial = _finite_number(state["initial_cash"], "initial_cash")
        cash = _finite_number(state["cash"], "cash")
        if initial <= 0:
            raise ValueError(f"initial_cash must be positive: {filename}")
        result["cash_vs_initial_pct"] = round((cash / initial - 1) * 100, 4)
    return result


def build_audit(state_dir):
    root = Path(state_dir).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("State path must be a directory")
    ledgers = [audit_ledger(root, name, filename) for name, filename in CANDIDATES.items()]
    present = [item for item in ledgers if item["status"] == "OK"]
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_PAPER_LEDGER_AUDIT",
        "state_directory": str(root),
        "ledger_count": len(ledgers),
        "present_ledgers": len(present),
        "missing_ledgers": [item["name"] for item in ledgers if item["status"] == "MISSING"],
        "ledgers": ledgers,
        "files_modified": False,
        "live_orders_placed": False,
        "warning": "Missing local ledgers are not inferred from GitHub; this report is descriptive, not a strategy qualification.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="research_runs/20261111_atr_forward_validation/paper_state")
    args = parser.parse_args()
    try:
        print(json.dumps(build_audit(args.state_dir), indent=2, allow_nan=False))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"AUDIT ERROR: {exc}\n")


if __name__ == "__main__":
    main()
