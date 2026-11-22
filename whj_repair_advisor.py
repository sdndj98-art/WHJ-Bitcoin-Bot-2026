"""WHJ repair advisor: deterministic, read-only repair plans from QA reports."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "research" / "development_team" / "latest_report.json"
OUTPUT = ROOT / "research" / "development_team"


AGENT_SOURCE_MAP = {
    "architecture_agent": ("whj_architecture_audit.py", "test_architecture_audit.py"),
    "syntax_agent": ("whj_syntax_check.py", "test_syntax_check.py"),
    "compile_agent": ("whj_compile_check.py", "test_compile_check.py"),
    "test_agent": ("run_tests.py", "test_suite"),
    "paper_safety_agent": ("whj_risk_guard.py", "test_paper_safety.py"),
    "workflow_agent": (".github/workflows/main.yml", "test_workflow.py"),
    "dashboard_integrity_agent": ("whj_dashboard.py", "test_dashboard.py"),
}

SECRET_PATTERNS = [
    re.compile(r"api[_-]?key[\s:=]+['\"']?[a-zA-Z0-9_\-\.]{8,}['\"']?", re.IGNORECASE),
    re.compile(r"secret[\s:=]+['\"']?[a-zA-Z0-9_\-\.]{8,}['\"']?", re.IGNORECASE),
    re.compile(r"token[\s:=]+['\"']?[a-zA-Z0-9_\-\.]{8,}['\"']?", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{10,}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"sk_(?:live|test)_[0-9a-zA-Z]{10,}"),
]

MAX_ERROR_LENGTH = 300
MAX_LOG_LINES = 20


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
        "P0", "Stop and investigate the paper-only/live-trading configuration mismatch. Human intervention required; never generate a code patch for safety mismatches.",
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


def redact_secrets(text: str) -> str:
    if not isinstance(text, str):
        return str(text)
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def sanitize_error_excerpt(evidence: dict) -> str:
    raw_excerpt = ""
    if isinstance(evidence, dict):
        for key in ["error", "message", "output_tail", "stderr", "details", "traceback"]:
            if key in evidence:
                val = evidence[key]
                if isinstance(val, list):
                    val = "\n".join(str(v) for v in val)
                raw_excerpt += f"{key}: {val}\n"
        if not raw_excerpt:
            raw_excerpt = json.dumps(evidence)
    else:
        raw_excerpt = str(evidence)

    redacted = redact_secrets(raw_excerpt)
    lines = redacted.strip().splitlines()
    if len(lines) > MAX_LOG_LINES:
        lines = lines[-MAX_LOG_LINES:]
    truncated = "\n".join(lines)
    if len(truncated) > MAX_ERROR_LENGTH:
        truncated = truncated[:MAX_ERROR_LENGTH] + "... [TRUNCATED]"
    return truncated


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

        retry_count = result.get("retry_count", result.get("retries", 0))
        source_file, regression_test = AGENT_SOURCE_MAP.get(
            name, ("whj_unknown_module.py", "test_unknown.py")
        )
        sanitized_error = sanitize_error_excerpt(result)

        if name == "paper_safety_agent":
            action = "STOP: Paper-safety or live-trading mismatch detected. Human intervention required. Never generate a code patch."

        proposals.append({
            "agent": name,
            "observed_status": status,
            "priority": priority,
            "failed_check": name,
            "source_file": source_file,
            "regression_test": regression_test,
            "sanitized_error_excerpt": sanitized_error,
            "retry_count": retry_count,
            "evidence": result,
            "recommended_action": action,
            "guardrail": guardrail,
            "state": "PROPOSAL_ONLY",
            "linked_issue": "#165",
        })

    for item in report.get("improvement_backlog", []):
        proposals.append({
            "agent": "backlog_advisor",
            "observed_status": "backlog_item",
            "priority": "P3",
            "failed_check": "backlog_item",
            "source_file": "research/development_team/backlog",
            "regression_test": "test_backlog.py",
            "sanitized_error_excerpt": redact_secrets(str(item)),
            "retry_count": 0,
            "evidence": item,
            "recommended_action": "Review whether this TODO/FIXME is still valid and create a focused test before changing code.",
            "guardrail": "Do not implement automatically.",
            "state": "PROPOSAL_ONLY",
            "linked_issue": "#165",
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
        "next_gate": "A human reviews the evidence, prepares a minimal patch on a separate branch, and runs the full test suite before opening a PR. Linked to issue #165.",
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
            f"- Failed check: `{proposal['failed_check']}`",
            f"- Source file: `{proposal['source_file']}`",
            f"- Regression test: `{proposal['regression_test']}`",
            f"- Retry count: `{proposal['retry_count']}`",
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
