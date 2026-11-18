"""WHJ repair advisor: deterministic, read-only repair plans from QA reports."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "research" / "development_team" / "latest_report.json"
OUTPUT = ROOT / "research" / "development_team"


RECOMMENDATIONS = {
    "architecture_agent": (
        "P2", "Review repository structure and confirm required modules are present.",
        "Do not rename or delete modules automatically."
    ),
    "syntax_agent": (
        "P1", "Inspect the reported Python syntax error and prepare a minimal isolated patch.",
        "Do not alter trading logic, risk controls, or dashboard files."
    ),
    "compile_agent": (
        "P1", "Reproduce the compilation failure and identify the exact affected module.",
        "Do not mass-edit files or apply unreviewed formatting changes."
    ),
    "test_agent": (
        "P1", "Reproduce the failing test and trace the regression before proposing a patch.",
        "Do not weaken, skip, or delete tests to obtain a green result."
    ),
    "paper_safety_agent": (
        "P0", "Stop and investigate the paper-only/live-trading configuration mismatch.",
        "Never enable live trading, change risk limits, or mutate paper ledgers."
    ),
    "workflow_agent": (
        "P1", "Review the hourly workflow schedule and its least-privilege permissions.",
        "Keep repository permissions read-only unless a separately approved workflow requires more."
    ),
    "dashboard_integrity_agent": (
        "P1", "Check why the dashboard integrity audit could not verify index.html.",
        "Do not modify index.html or dashboard assets."
    ),
}


def build_repair_plan(report: dict) -> dict:
    agents = report.get("agents", {})
    proposals = []
    for name, result in agents.items():
        status = result.get("status", "unknown")
        if status == "passed":
            continue
        priority, action, guardrail = RECOMMENDATIONS.get(
            name, ("P2", "Inspect this audit result and write a reproducible diagnosis.", "No automatic source edits.")
        )
        proposals.append({
            "agent": name,
            "observed_status": status,
            "priority": priority,
            "evidence": result,
            "recommended_action": action,
            "guardrail": guardrail,
            "state": "PROPOSAL_ONLY",
        })

    for item in report.get("improvement_backlog", []):
        proposals.append({
            "agent": "backlog_advisor",
            "observed_status": "backlog_item",
            "priority": "P3",
            "evidence": item,
            "recommended_action": "Review whether this TODO/FIXME is still valid and create a focused test before changing code.",
            "guardrail": "Do not implement automatically.",
            "state": "PROPOSAL_ONLY",
        })

    return {
        "source_report_generated_at_utc": report.get("generated_at_utc"),
        "source_status": report.get("status", "UNKNOWN"),
        "advisor_mode": "deterministic_read_only",
        "proposal_count": len(proposals),
        "proposals": proposals,
        "permissions": {
            "source_edits": False,
            "pull_requests_created": False,
            "auto_merge": False,
            "dashboard_write": False,
            "paper_ledger_write": False,
            "live_trading": False,
            "paid_ai_api": False,
        },
        "next_gate": "A human reviews the evidence, prepares a minimal patch on a separate branch, and runs the full test suite before opening a PR.",
    }


def write_plan(report_path: Path = REPORT, output_dir: Path = OUTPUT) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    plan = build_repair_plan(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "repair_proposals.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# WHJ Repair Advisor",
        "",
        f"- Source status: **{plan['source_status']}**",
        f"- Proposals: **{plan['proposal_count']}**",
        "- Mode: deterministic and read-only",
        "",
        "## Proposals",
        "",
    ]
    if not plan["proposals"]:
        lines.append("No repair proposals: all audited agents passed and no backlog markers were found.")
    for proposal in plan["proposals"]:
        lines += [
            f"### [{proposal['priority']}] {proposal['agent']} — {proposal['observed_status']}",
            f"- Recommended action: {proposal['recommended_action']}",
            f"- Guardrail: {proposal['guardrail']}",
            "- State: proposal only; no source code changed",
            "",
        ]
    lines += [
        "## Approval boundary",
        plan["next_gate"],
        "",
        "No pull request is created by this advisor. No source, dashboard, paper ledger, risk limit, or trading setting is modified.",
        "",
    ]
    (output_dir / "repair_proposals.md").write_text("\n".join(lines), encoding="utf-8")
    return plan


def main() -> int:
    plan = write_plan()
    print(f"WHJ repair advisor: proposals={plan['proposal_count']} mode={plan['advisor_mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
