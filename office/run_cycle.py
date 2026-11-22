#!/usr/bin/env python3
"""Deterministic office rotation and handoff ledger; no trading execution."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "office" / "office_state.json"
BRIDGE = ROOT / "office" / "paper_bridge_report.json"


def read_bridge():
    """Read the latest paper-workflow bridge report without changing it."""
    if not BRIDGE.is_file():
        return {"status": "WAITING_FOR_PAPER_WORKFLOW"}
    try:
        report = json.loads(BRIDGE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "INVALID_BRIDGE_REPORT"}
    wallet = report.get("shared_wallet", {})
    engine = report.get("multi_asset_engine", {})
    agents = report.get("six_agent_office", {})
    return {
        "status": report.get("status", "UNKNOWN"),
        "generated_at_utc": report.get("generated_at_utc"),
        "paper_status": agents.get("status", "UNKNOWN"),
        "agent_count": agents.get("agent_count", 0),
        "markets_scanned": engine.get("markets_scanned", 0),
        "open_positions": wallet.get("open_positions", 0),
        "closed_trades": wallet.get("closed_trades", 0),
        "equity_usd": wallet.get("equity_usd"),
        "live_trading_enabled": report.get("live_trading_enabled", True),
        "orders_submitted": report.get("orders_submitted", True),
    }
ROLES = [
    ("Coordinator", "select/sequence next backlog item"),
    ("Market-data QA", "check source freshness and candle integrity"),
    ("Strategy QA", "review paper strategy gates and signal sanity"),
    ("Paper-engine QA", "verify simulated entry/exit and ledger consistency"),
    ("Dashboard QA", "verify report/dashboard fields and refresh"),
    ("Risk QA", "verify drawdown, stale-data and duplicate-entry guards"),
    ("Release QA", "summarize blockers and hand off to Coordinator"),
]

def main():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding="utf-8"))
    else:
        state = {"cycle": 0, "last_role_index": -1, "history": []}

    cycle = int(state.get("cycle", 0)) + 1
    idx = (int(state.get("last_role_index", -1)) + 1) % len(ROLES)
    owner, task = ROLES[idx]
    next_owner, next_task = ROLES[(idx + 1) % len(ROLES)]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bridge = read_bridge()
    record = {
        "cycle": cycle,
        "timestamp_utc": now,
        "current_owner": owner,
        "current_task": task,
        "handoff_to": next_owner,
        "handoff_task": next_task,
        "paper_engine_bridge": bridge,
        "reminder": f"Cycle {cycle}: {owner} must hand off to {next_owner} before the next scheduled cycle."
    }
    state.update({
        "cycle": cycle,
        "last_role_index": idx,
        "updated_at_utc": now,
        "current_handoff": record,
        "history": (state.get("history", []) + [record])[-50:],
        "mode": "coordination_only_paper_trading",
        "live_orders_enabled": False,
    })
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    summary = (
        "# WHJ 24-hour Office Cycle\n\n"
        f"**Cycle:** {cycle}  \n"
        f"**Current role:** {owner}  \n"
        f"**Task:** {task}  \n"
        f"**Handoff reminder:** {owner} → {next_owner}  \n"
        f"**Next task:** {next_task}\n"
        f"**Paper bridge:** {bridge.get('status')} | agents={bridge.get('agent_count', 0)} | markets={bridge.get('markets_scanned', 0)} | paper trades={bridge.get('closed_trades', 0)}\n"
        f"**Paper equity:** {bridge.get('equity_usd', 'not available')} USD | live orders disabled={bridge.get('live_trading_enabled') is False}\n\n"
        "> Scheduled rotation only. It does not represent autonomous AI staff, "
        "continuous uptime, or live trading. Trading mode remains paper-only.\n"
    )
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary)

if __name__ == "__main__":
    main()
