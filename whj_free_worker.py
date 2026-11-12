"""Zero-cost deterministic WHJ research workers.

These workers inspect repository files only. They do not use an LLM, network,
exchange, broker, shell, or paper ledger. Their output is a reproducible
structural inventory, not a semantic strategy review or profitability claim.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from whj_agent_office import TASKS, build_plan, validate_plan
from whj_grok_worker import TASK_CONTEXT

MAX_FILE_BYTES = 250_000
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".json", ".csv", ".html"}


def inspect_file(root: Path, relative: str) -> dict | None:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        raw = candidate.read_bytes()
    except OSError:
        return None
    digest = hashlib.sha256(raw).hexdigest()
    result = {
        "path": relative,
        "bytes": len(raw),
        "sha256": digest,
        "readable_text": False,
        "python_ast_valid": None,
        "first_line": "",
    }
    if len(raw) > MAX_FILE_BYTES:
        result["note"] = "File exceeds deterministic inspection size limit."
        return result
    if Path(relative).suffix.lower() in TEXT_SUFFIXES:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            result["note"] = "Not valid UTF-8; content not interpreted."
            return result
        result["readable_text"] = True
        result["first_line"] = content.splitlines()[0][:200] if content.splitlines() else ""
        if Path(relative).suffix.lower() == ".py":
            try:
                ast.parse(content, filename=relative)
                result["python_ast_valid"] = True
            except SyntaxError as exc:
                result["python_ast_valid"] = False
                result["syntax_error"] = f"line {exc.lineno}: {exc.msg}"
    return result


def build_free_report(root: Path) -> dict:
    plan = build_plan()
    validate_plan(plan)
    reports = []
    for task in plan["tasks"]:
        paths = TASK_CONTEXT.get(task["task_id"], [])
        inspected = [item for path in paths if (item := inspect_file(root, path)) is not None]
        missing = [path for path in paths if inspect_file(root, path) is None]
        findings = []
        for item in inspected:
            detail = f"sha256={item['sha256']} bytes={item['bytes']}"
            if item["python_ast_valid"] is True:
                detail += " python_ast=valid"
            elif item["python_ast_valid"] is False:
                detail += " python_ast=INVALID"
            quote = item["first_line"] or detail
            if len(quote) < 12:
                quote = detail
            findings.append({
                "claim": f"Repository file inventory: {item['path']} exists; {detail}.",
                "source_path": item["path"],
                "evidence_quote": quote,
                "confidence": "high",
            })
        syntax_failures = [item for item in inspected if item["python_ast_valid"] is False]
        deterministic_checks = []
        for item in inspected:
            if item["python_ast_valid"] is not None:
                deterministic_checks.append({
                    "check": "python_ast_syntax",
                    "source_path": item["path"],
                    "status": "passed" if item["python_ast_valid"] else "failed",
                    "detail": "Python source parses successfully." if item["python_ast_valid"] else item.get("syntax_error", "Python syntax error"),
                })
            if item["readable_text"]:
                deterministic_checks.append({
                    "check": "utf8_text_readability",
                    "source_path": item["path"],
                    "status": "passed",
                    "detail": "File decoded as UTF-8 within the inspection size limit.",
                })
        risks = []
        if syntax_failures:
            risks.extend(f"Python syntax error in {item['path']}: {item['syntax_error']}" for item in syntax_failures)
        if missing:
            risks.append("Some configured source paths are absent; inspect missing_data before relying on this task.")
        missing_data = [
            "No strategy performance, win rate, drawdown, or profitability is calculated by this static worker.",
            "No external market feed or synchronized live data is queried.",
        ]
        if missing:
            missing_data.append("Missing repository paths: " + ", ".join(missing))
        reports.append({
            "task_id": task["task_id"],
            "owner_role": task["owner_role"],
            "reviewer_role": task["reviewer_role"],
            "status": "collected" if inspected else "blocked",
            "execution_status": "not_executed_plan_only",
            "recommendation": "needs_human",
            "files_expected": paths,
            "files_inspected": inspected,
            "findings": findings,
            "deterministic_checks": deterministic_checks,
            "deterministic_checks_executed": len(deterministic_checks),
            "deterministic_checks_failed": sum(check["status"] == "failed" for check in deterministic_checks),
            "risks": risks,
            "missing_data": missing_data,
            "semantic_review_required": True,
        })
    stamp = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at_utc": stamp,
        "mode": "free_deterministic_repository_audit",
        "provider": "none",
        "provider_calls": 0,
        "cost_usd": 0.0,
        "task_count": len(reports),
        "collected_tasks": sum(row["status"] == "collected" for row in reports),
        "blocked_tasks": sum(row["status"] == "blocked" for row in reports),
        "executed_research_tasks": 0,
        "plan_only_tasks": len(reports),
        "deterministic_checks_executed": sum(row["deterministic_checks_executed"] for row in reports),
        "deterministic_checks_failed": sum(row["deterministic_checks_failed"] for row in reports),
        "deterministic_checks_passed": sum(
            check["status"] == "passed"
            for row in reports for check in row["deterministic_checks"]
        ),
        "live_trading_enabled": False,
        "repository_writes_enabled": False,
        "paper_ledger_mutation_enabled": False,
        "profitability_claims_made": False,
        "reports": reports,
    }


def write_report(root: Path, output_dir: Path) -> dict:
    result = build_free_report(root)
    run_dir = output_dir / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") / "free"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "free_worker_results.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# WHJ Free Research Workers",
        "",
        f"- Generated UTC: {result['generated_at_utc']}",
        "- Provider: none (deterministic Python checks only)",
        "- API calls: 0",
        "- Cost: $0.00",
        f"- Repository inventories collected: {result['collected_tasks']}/{result['task_count']}",
        f"- Research tasks actually executed: {result['executed_research_tasks']}/{result['task_count']} (PLAN ONLY)",
        f"- Deterministic source checks executed: {result['deterministic_checks_executed']} (passed: {result['deterministic_checks_passed']}, failed: {result['deterministic_checks_failed']})",
        "- These are real UTF-8 readability and Python AST syntax checks, not semantic strategy reviews or profitability tests.",
        "- This run does not mean 24 research reviews were completed; it inventories configured source files and runs only the deterministic checks listed above.",
        "- Profitability claims: none",
        "- Live trading / repository writes / paper-ledger mutation: disabled",
        "",
        "| Task | Role | Status | Files inspected |",
        "|---|---|---|---:|",
    ]
    for row in result["reports"]:
        lines.append(f"| {row['task_id']} | {row['owner_role']} | {row['status']} | {len(row['files_inspected'])} |")
    lines += ["", "## Evidence inventory", ""]
    for row in result["reports"]:
        lines += [f"### {row['task_id']} — {row['status']}", ""]
        for item in row["files_inspected"]:
            lines.append(f"- `{item['path']}`: {item['bytes']} bytes; SHA-256 `{item['sha256']}`")
        for check in row["deterministic_checks"]:
            lines.append(f"- Check {check['check']} on `{check['source_path']}`: **{check['status']}** — {check['detail']}")
            if item.get("python_ast_valid") is not None:
                lines.append(f"  - Python AST valid: {item['python_ast_valid']}")
        for risk in row["risks"]:
            lines.append(f"- Risk: {risk}")
        for missing in row["missing_data"]:
            lines.append(f"- Missing/limitation: {missing}")
        lines.append("- Semantic review required; this is not a strategy performance evaluation.")
        lines.append("")
    (run_dir / "free_worker_results.md").write_text("\n".join(lines), encoding="utf-8")
    latest_json = output_dir / "latest_free_worker_results.json"
    latest_md = output_dir / "latest_free_worker_results.md"
    latest_json.parent.mkdir(parents=True, exist_ok=True)
    latest_json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    latest_md.write_text("\n".join(lines), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run zero-cost deterministic WHJ repository workers")
    parser.add_argument("command", choices=("run",))
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default="research/agent_office")
    args = parser.parse_args(argv)
    result = write_report(Path(args.root), Path(args.output_dir))
    print(
        f"Free WHJ workers complete: tasks={result['task_count']} "
        f"inventories_collected={result['collected_tasks']} blocked={result['blocked_tasks']} "
        f"research_tasks_executed={result['executed_research_tasks']} "
        "mode=PLAN_ONLY api_calls=0 cost_usd=0.00"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
