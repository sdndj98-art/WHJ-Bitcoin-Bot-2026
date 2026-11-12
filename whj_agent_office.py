"""WHJ multi-agent research office: deterministic planning and governance MVP.

This module creates an auditable 24-role research roster and dependency-aware
nightly work plan. It does NOT call an LLM, exchange, broker, or order endpoint.
A provider adapter must be configured separately before workers can autonomously
draft research outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

OFFICE_VERSION = 1
ROLES = {
    "chief_of_staff": ("Chief of Staff", "leadership"),
    "project_manager": ("Research Project Manager", "management"),
    "btc_data": ("Bitcoin Data Engineer", "bitcoin"),
    "gold_data": ("Gold Data Engineer", "gold"),
    "market_quality": ("Market Quality Researcher", "shared"),
    "trend": ("Trend Strategy Researcher", "shared"),
    "momentum": ("Momentum Strategy Researcher", "shared"),
    "breakout": ("Breakout Strategy Researcher", "shared"),
    "mean_reversion": ("Mean Reversion Researcher", "shared"),
    "volatility": ("Volatility Researcher", "shared"),
    "execution": ("Execution Cost Researcher", "shared"),
    "backtest": ("Backtest Engineer", "shared"),
    "walk_forward": ("Walk-Forward Researcher", "shared"),
    "benchmark": ("Benchmark Researcher", "shared"),
    "risk": ("Risk Manager", "shared"),
    "statistics": ("Statistical Validation Researcher", "shared"),
    "ml_research": ("Machine Learning Researcher", "shared"),
    "cross_asset": ("Cross-Asset Researcher", "shared"),
    "paper_monitor": ("Paper Trading Monitor", "shared"),
    "dashboard": ("Dashboard and Reporting Engineer", "shared"),
    "qa": ("Quality Assurance Engineer", "shared"),
    "reproducibility": ("Reproducibility and Data Lineage Engineer", "shared"),
    "red_team": ("Independent Red-Team Reviewer", "audit"),
    "safety_auditor": ("Independent Trading-Safety Auditor", "audit"),
}

TASKS = [
    ("btc_data_audit", "Audit Bitcoin data freshness, gaps, duplicates and timestamp integrity", "btc_data", [], ["Dataset fingerprint", "Gap and duplicate report", "No future data leakage"]),
    ("gold_data_audit", "Audit gold data identity, sessions, rolls and source limitations", "gold_data", [], ["Explicit GC=F versus XAUUSD identity", "Session and roll caveats", "Dataset fingerprint"]),
    ("market_quality_review", "Review spread, liquidity and market-quality evidence availability", "market_quality", ["btc_data_audit", "gold_data_audit"], ["Unavailable fields marked UNKNOWN", "No fabricated order-flow or wallet data"]),
    ("strategy_inventory", "Inventory implemented BTC and gold strategy families and evidence status", "trend", ["btc_data_audit", "gold_data_audit"], ["Every candidate has source and status", "Signals separated from performance evidence"]),
    ("cost_model_review", "Review fees, slippage, spread, financing and execution assumptions", "execution", ["market_quality_review"], ["Base and stressed costs explicit", "Unmodelled costs disclosed"]),
    ("historical_evaluation", "Review historical evaluation code and available OOS artifacts without inventing results", "backtest", ["strategy_inventory", "cost_model_review"], ["Chronological OOS only", "Matched benchmark", "No paper ledger or order path"]),
    ("walk_forward_review", "Assess rolling and regime-specific robustness without reusing final holdout", "walk_forward", ["historical_evaluation"], ["Time boundaries documented", "No tuning on final holdout"]),
    ("statistical_review", "Assess uncertainty, trial count, selection bias and winner concentration", "statistics", ["historical_evaluation"], ["Trial manifest", "Uncertainty and limitations", "No PBO overclaim"]),
    ("momentum_strategy_review", "Audit momentum strategy definitions and evidence quality", "momentum", ["strategy_inventory"], ["Causal signals", "No profitability claim without OOS evidence"]),
    ("breakout_strategy_review", "Audit breakout and channel strategy definitions and evidence quality", "breakout", ["strategy_inventory"], ["Completed-bar signals", "Next-bar execution assumptions disclosed"]),
    ("mean_reversion_strategy_review", "Audit mean-reversion strategy definitions and regime risks", "mean_reversion", ["strategy_inventory"], ["Regime assumptions stated", "Trend-trap risks identified"]),
    ("volatility_strategy_review", "Audit volatility filters, stops and volatility-regime handling", "volatility", ["market_quality_review", "strategy_inventory"], ["Volatility inputs are causal", "Gap and jump risks disclosed"]),
    ("benchmark_review", "Audit matched benchmark construction and excess-return comparisons", "benchmark", ["historical_evaluation"], ["Identical intervals and exposure assumptions", "Cash baseline included"]),
    ("ml_research_review", "Review ML research readiness, labels, leakage controls and sample sufficiency", "ml_research", ["statistical_review", "strategy_inventory"], ["No training on future labels", "ML remains research-only"]),
    ("cross_asset_review", "Review BTC and gold cross-asset research feasibility and timestamp alignment", "cross_asset", ["btc_data_audit", "gold_data_audit"], ["No look-ahead across markets", "Unavailable synchronized data marked UNKNOWN"]),
    ("risk_review", "Stress drawdown, loss streaks, gaps and position sizing", "risk", ["historical_evaluation", "cost_model_review"], ["Intrabar risk caveats", "Risk limits tested", "No leverage"]),
    ("paper_monitor_review", "Audit forward-only paper monitors, checkpoint integrity and idempotency", "paper_monitor", ["risk_review", "historical_evaluation"], ["No historical trades booked into forward ledger", "Duplicate candles cannot double count"]),
    ("dashboard_reporting_review", "Audit dashboard reporting for clear evidence, status and risk visibility", "dashboard", ["historical_evaluation", "strategy_inventory"], ["No unsupported performance claims", "Research and paper status clearly separated"]),
    ("qa_review", "Review regression coverage, failure cases and test quality for research modules", "qa", ["historical_evaluation", "strategy_inventory"], ["Negative tests present", "Tests do not encode unsupported performance expectations"]),
    ("reproducibility_review", "Review dataset hashes, commit IDs, parameters and artifact lineage", "reproducibility", ["btc_data_audit", "gold_data_audit", "historical_evaluation"], ["Every report traceable to data and code", "Missing lineage blocks acceptance"]),
    ("red_team_review", "Attempt to falsify the research claims and find leakage or simulator bias", "red_team", ["btc_data_audit", "gold_data_audit", "market_quality_review", "strategy_inventory", "cost_model_review", "historical_evaluation", "walk_forward_review", "statistical_review", "momentum_strategy_review", "breakout_strategy_review", "mean_reversion_strategy_review", "volatility_strategy_review", "benchmark_review", "ml_research_review", "cross_asset_review", "risk_review", "paper_monitor_review", "dashboard_reporting_review", "qa_review", "reproducibility_review"], ["Adversarial findings", "Evidence-linked objections"]),
    ("safety_review", "Verify research isolation and absence of live-order capability", "safety_auditor", ["risk_review", "paper_monitor_review"], ["Live orders disabled", "Secrets not exposed", "No unapproved ledger writes"]),
    ("chief_decision", "Chief of Staff synthesizes evidence and recommends next research priorities", "chief_of_staff", ["red_team_review", "safety_review"], ["Evidence-based decision", "Explicit blockers", "No automatic promotion"]),
    ("pm_acceptance", "Project Manager verifies every deliverable and publishes the nightly report", "project_manager", ["chief_decision"], ["All evidence linked", "Incomplete tasks remain blocked", "No unverified claim"]),
]

def _task_id(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]

def build_plan(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tasks = []
    for key, title, owner, deps, criteria in TASKS:
        tasks.append({
            "task_id": key,
            "title": title,
            "owner_role": owner,
            "reviewer_role": "project_manager" if owner != "project_manager" else "chief_of_staff",
            "dependencies": list(deps),
            "acceptance_criteria": list(criteria),
            "status": "planned",
            "evidence": [],
            "execution_mode": "plan_only",
        })
    plan = {
        "schema_version": OFFICE_VERSION,
        "office": "WHJ AI Research Office",
        "generated_at_utc": now.astimezone(timezone.utc).isoformat(),
        "provider": {"name": None, "configured": False, "status": "NOT_CONFIGURED"},
        "leadership": ["chief_of_staff", "project_manager"],
        "worker_role_count": 20,
        "independent_auditor_roles": ["red_team", "safety_auditor"],
        "roles": [
            {"role_id": key, "name": value[0], "department": value[1]}
            for key, value in ROLES.items()
        ],
        "task_count": len(tasks),
        "tasks": tasks,
        "governance": {
            "research_only": True,
            "live_trading_enabled": False,
            "exchange_order_calls_allowed": False,
            "paper_ledger_mutation_allowed": False,
            "auto_merge_allowed": False,
            "candidate_promotion_allowed": False,
            "require_independent_review": True,
            "require_evidence_for_completion": True,
            "unknown_data_policy": "UNKNOWN_NOT_ZERO_NOT_GUESSED",
        },
        "limitations": [
            "This MVP creates a role roster and auditable plan; it does not yet invoke autonomous LLM workers.",
            "A supported model provider, credentials, budget limits, and tool permissions are required before autonomous worker execution.",
            "No strategy is selected or promoted by the planner.",
        ],
    }
    validate_plan(plan)
    return plan

def validate_plan(plan: dict) -> None:
    if not isinstance(plan, dict) or plan.get("schema_version") != OFFICE_VERSION:
        raise ValueError("Unsupported WHJ agent-office plan")
    roles = plan.get("roles")
    if not isinstance(roles, list) or len(roles) != 24:
        raise ValueError("Office must contain exactly 24 roles")
    ids = [role.get("role_id") for role in roles]
    if len(set(ids)) != 24 or set(ids) != set(ROLES):
        raise ValueError("Role roster is incomplete or contains duplicate IDs")
    if plan.get("worker_role_count") != 20:
        raise ValueError("Office must define 20 worker roles")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != plan.get("task_count"):
        raise ValueError("Task count mismatch")
    task_ids = {task.get("task_id") for task in tasks}
    if len(task_ids) != len(tasks):
        raise ValueError("Duplicate task IDs")
    graph = {}
    for task in tasks:
        owner, reviewer = task.get("owner_role"), task.get("reviewer_role")
        if owner not in ROLES or reviewer not in ROLES or owner == reviewer:
            raise ValueError("Task owner and independent reviewer must be distinct valid roles")
        if task.get("status") not in {"planned", "in_progress", "submitted", "accepted", "rejected", "blocked"}:
            raise ValueError("Invalid task status")
        if task.get("status") == "accepted" and not task.get("evidence"):
            raise ValueError("A task cannot be accepted without evidence")
        deps = task.get("dependencies")
        if not isinstance(deps, list) or any(dep not in task_ids for dep in deps):
            raise ValueError("Unknown task dependency")
        graph[task["task_id"]] = deps
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            raise ValueError("Task dependency cycle detected")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)
    governance = plan.get("governance", {})
    if governance.get("live_trading_enabled") is not False or governance.get("exchange_order_calls_allowed") is not False:
        raise ValueError("Unsafe live-trading governance configuration")
    if governance.get("auto_merge_allowed") is not False or governance.get("candidate_promotion_allowed") is not False:
        raise ValueError("Unsafe automatic promotion or merge configuration")

def render_markdown(plan: dict) -> str:
    validate_plan(plan)
    lines = [
        "# WHJ AI Research Office — Work Plan", "",
        f"- Generated (UTC): {plan['generated_at_utc']}",
        f"- Roster: {len(plan['roles'])} roles (2 leadership, 20 workers, 2 independent auditors)",
        f"- Tasks: {plan['task_count']}",
        f"- LLM provider: {plan['provider']['status']}",
        "- Mode: PLAN ONLY — no autonomous LLM calls, no orders, no ledger writes", "",
        "## Leadership", "- Chief of Staff: plans the research cycle and synthesizes evidence.",
        "- Project Manager: coordinates dependencies and checks deliverables.", "",
        "## Work queue", "",
        "| Task | Owner | Reviewer | Dependencies | Status |",
        "|---|---|---|---|---|",
    ]
    for task in plan["tasks"]:
        lines.append(
            f"| {task['title']} | {task['owner_role']} | {task['reviewer_role']} | "
            f"{', '.join(task['dependencies']) or '—'} | {task['status']} |"
        )
    lines += ["", "## Governance", "- Research-only; live orders disabled.",
              "- No automatic merge or strategy promotion.",
              "- Every accepted task must include evidence and independent review.",
              "- Missing market data is UNKNOWN, never silently treated as zero.", "",
              "## Important limitation", *[f"- {item}" for item in plan["limitations"]], ""]
    return "\n".join(lines)

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build and validate the WHJ multi-agent research-office plan")
    parser.add_argument("command", choices=("plan", "validate"))
    parser.add_argument("--output-dir", default="research/agent_office")
    args = parser.parse_args(argv)
    if args.command == "plan":
        plan = build_plan()
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "latest_plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "latest_plan.md").write_text(render_markdown(plan), encoding="utf-8")
        print(f"WHJ office plan written: {output.resolve()}")
        print(f"roles={len(plan['roles'])} tasks={plan['task_count']} provider={plan['provider']['status']}")
        return 0
    plan = build_plan()
    validate_plan(plan)
    print("WHJ agent-office plan validation: OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
