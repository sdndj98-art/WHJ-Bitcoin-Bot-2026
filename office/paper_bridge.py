#!/usr/bin/env python3
"""Connect the scheduled WHJ office to the paper engine's latest run outputs.

This is a read-only audit/reporting bridge. It does not run strategies, mutate
the portfolio ledger, or submit exchange/broker orders.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = ROOT / "state" / "whj_agents.json"
SNAPSHOT_PATH = ROOT / "dual_portfolio.json"
LEDGER_PATH = ROOT / "state" / "shared_paper_100usd.json"
REPORT_PATH = ROOT / "office" / "paper_bridge_report.json"


def load_json(path):
    if not path.is_file():
        raise FileNotFoundError(f"Required paper-engine output is missing: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    agents = load_json(AGENTS_PATH)
    snapshot = load_json(SNAPSHOT_PATH)
    ledger = load_json(LEDGER_PATH)

    if agents.get("mode") != "PAPER_ONLY" or agents.get("live_trading_enabled") is not False:
        raise ValueError("Six-agent output is not explicitly paper-only")
    if ledger.get("mode") != "PAPER_ONLY" or ledger.get("live_trading_enabled") is not False:
        raise ValueError("Shared ledger is not explicitly paper-only")
    if abs(float(ledger.get("initial_cash_usd", 0)) - 100.0) > 1e-8:
        raise ValueError("Shared ledger capital is not the configured $100")
    if snapshot.get("multi_asset_paper", {}).get("live_orders_enabled") is not False:
        raise ValueError("Multi-asset paper snapshot does not confirm live orders disabled")
    if snapshot.get("multi_asset_paper", {}).get("orders_submitted") is not False:
        raise ValueError("Multi-asset paper snapshot does not confirm zero orders submitted")

    agent_list = agents.get("agents")
    if not isinstance(agent_list, list) or len(agent_list) != 6:
        raise ValueError("Expected exactly six agent telemetry records")
    agent_names = [str(agent.get("name", "UNKNOWN")) for agent in agent_list]
    equity_agent = next((a for a in agent_list if a.get("name") == "EQUITY"), None)
    equity_metrics = (equity_agent or {}).get("metrics", {})
    multi = snapshot.get("multi_asset_paper", {})
    scanned = multi.get("markets_scanned", [])
    if not isinstance(scanned, list):
        scanned = []
    diagnostics = multi.get("strategy_diagnostics", {})
    entries = sum(int(v.get("entry_signals", 0) or 0) for v in diagnostics.values() if isinstance(v, dict))
    opened = sum(int(v.get("opened", 0) or 0) for v in diagnostics.values() if isinstance(v, dict))
    blocked = sum(int(v.get("blocked", 0) or 0) for v in diagnostics.values() if isinstance(v, dict))
    positions = ledger.get("positions", {})
    closed = ledger.get("closed_trades", [])
    if not isinstance(positions, dict) or not isinstance(closed, list):
        raise ValueError("Shared paper ledger has invalid positions/trade collections")

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "CONNECTED",
        "bridge_mode": "READ_ONLY_PAPER_AUDIT",
        "paper_only": True,
        "live_trading_enabled": False,
        "orders_submitted": False,
        "source_workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "six_agent_office": {
            "status": agents.get("portfolio_status", "UNKNOWN"),
            "portfolio_decision": agents.get("portfolio_decision", "UNKNOWN"),
            "agent_count": len(agent_list),
            "agent_names": agent_names,
            "generated_at_utc": agents.get("generated_at_utc"),
        },
        "shared_wallet": {
            "initial_capital_usd": float(ledger["initial_cash_usd"]),
            "cash_usd": float(ledger.get("cash_usd", 0)),
            "open_positions": len(positions),
            "closed_trades": len(closed),
            "equity_usd": equity_metrics.get("equity_usd"),
            "pnl_usd": equity_metrics.get("pnl_usd"),
            "return_pct": equity_metrics.get("return_pct"),
        },
        "multi_asset_engine": {
            "status": multi.get("status", "UNKNOWN"),
            "markets_scanned": len(scanned),
            "markets_with_errors": len(multi.get("markets_with_errors", {}) or {}),
            "processed_closed_candles": multi.get("processed_closed_candles", 0),
            "events_this_run": len(multi.get("events_this_run", []) or []),
            "strategy_entry_signals": entries,
            "positions_opened_this_run": opened,
            "entries_blocked_by_guards": blocked,
            "block_reasons": {
                name: dict(v.get("block_reasons", {}))
                for name, v in diagnostics.items() if isinstance(v, dict) and v.get("block_reasons")
            },
        },
        "note": "Bridge validates and summarizes outputs from the paper workflow. It does not execute trading logic or live orders.",
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    summary = (
        "# WHJ Office ↔ Paper Engine Bridge\n\n"
        "**Bridge:** CONNECTED (read-only)  \n"
        f"**Paper mode:** {report['six_agent_office']['status']}  \n"
        f"**Six agents:** {len(agent_list)}  \n"
        f"**Markets scanned:** {len(scanned)}  \n"
        f"**Shared wallet:** $100 paper  \n"
        f"**Open positions:** {len(positions)}  \n"
        f"**Closed paper trades:** {len(closed)}  \n"
        f"**Entry signals / opened / blocked:** {entries} / {opened} / {blocked}  \n"
        "**Live orders:** disabled; none submitted\n\n"
        "> This is a read-only audit of outputs produced earlier in this workflow. "
        "A signal or simulated trade is not a live order.\n"
    )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary)
    print(summary)


if __name__ == "__main__":
    main()
