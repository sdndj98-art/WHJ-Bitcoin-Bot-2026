#!/usr/bin/env python3
"""Deterministic office rotation and handoff ledger; no trading execution."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "office" / "office_state.json"
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
    record = {
        "cycle": cycle,
        "timestamp_utc": now,
        "current_owner": owner,
        "current_task": task,
        "handoff_to": next_owner,
        "handoff_task": next_task,
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
        f"**Next task:** {next_task}\n\n"
        "> Scheduled rotation only. It does not represent autonomous AI staff, "
        "continuous uptime, or live trading. Trading mode remains paper-only.\n"
    )
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary)

if __name__ == "__main__":
    main()
