"""WHJ 24/7 development council: free, read-only, evidence-based QA."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import subprocess
import sys
import tokenize
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "research" / "development_team"
EXCLUDED = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def tracked_python_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py")
        if not any(part in EXCLUDED for part in path.parts)
    )


def run_command(command: list[str], root: Path = ROOT) -> dict:
    try:
        proc = subprocess.run(
            command, cwd=root, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=900, check=False,
        )
        return {
            "command": command, "exit_code": proc.returncode,
            "status": "passed" if proc.returncode == 0 else "failed",
            "output_tail": proc.stdout[-12000:],
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {
            "command": command, "exit_code": None, "status": "timeout",
            "output_tail": str(output)[-12000:],
        }


def audit_portfolio(path: Path) -> dict:
    if not path.is_file():
        return {"status": "blocked", "reason": "dual_portfolio.json missing"}
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"status": "failed", "reason": f"portfolio JSON invalid: {exc}"}
    issues = []
    if snapshot.get("paper_only") is not True:
        issues.append("portfolio paper_only must be true")
    if snapshot.get("live_trading_enabled") is not False:
        issues.append("portfolio live_trading_enabled must be false")
    for market in ("btc", "gold"):
        sleeve = snapshot.get(market)
        if not isinstance(sleeve, dict):
            issues.append(f"{market} sleeve missing or invalid")
            continue
        if sleeve.get("live_trading_enabled", False) is not False:
            issues.append(f"{market} live trading flag must remain false")
        if sleeve.get("paper_only", True) is not True:
            issues.append(f"{market} paper_only flag must remain true")
        consensus = sleeve.get("entry_consensus")
        if consensus is not None and not isinstance(consensus, dict):
            issues.append(f"{market} entry_consensus must be an object")
    return {
        "status": "passed" if not issues else "failed",
        "markets_checked": ["btc", "gold"],
        "issues": issues,
        "paper_only": snapshot.get("paper_only"),
        "live_trading_enabled": snapshot.get("live_trading_enabled"),
    }


def audit_hourly_schedule(path: Path) -> dict:
    if not path.is_file():
        return {"status": "failed", "reason": "development-team workflow missing"}
    content = path.read_text(encoding="utf-8")
    expected = 'cron: "0 * * * *"'
    ok = expected in content and "permissions:" in content and "contents: read" in content
    return {
        "status": "passed" if ok else "failed",
        "hourly_schedule_present": expected in content,
        "read_only_repository_permission": "contents: read" in content,
    }


def file_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_backlog_markers(source: str, filename: str) -> list[dict]:
    """Find actionable TODO/FIXME comments and executable NotImplementedError uses.

    String literals are intentionally ignored so the scanner does not report
    its own marker vocabulary or documentation examples as backlog items.
    """
    found = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT and any(
                tag in token.string for tag in ("TODO", "FIXME")
            ):
                found.append({
                    "file": filename, "line": token.start[0],
                    "item": token.string.strip()[:240],
                })
    except (tokenize.TokenError, IndentationError):
        pass

    try:
        tree = ast.parse(source, filename=filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "NotImplementedError":
                found.append({
                    "file": filename, "line": node.lineno,
                    "item": "NotImplementedError usage",
                })
    except SyntaxError:
        pass
    return sorted(found, key=lambda item: item["line"])


def run_council(root: Path = ROOT) -> dict:
    files = tracked_python_files(root)
    syntax = []
    backlog = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=rel)
            syntax.append({"file": rel, "status": "passed"})
            backlog.extend(find_backlog_markers(source, rel))
        except (OSError, UnicodeError, SyntaxError) as exc:
            syntax.append({"file": rel, "status": "failed", "error": str(exc)})

    # Seven specialist roles run as deterministic local audits; no model/API is called.
    agents = {
        "architecture_agent": {
            "status": "passed" if files else "failed",
            "python_modules_discovered": len(files),
        },
        "syntax_agent": {
            "status": "passed" if syntax and all(x["status"] == "passed" for x in syntax) else "failed",
            "files_checked": len(syntax), "files": syntax,
        },
        "compile_agent": run_command([sys.executable, "-m", "compileall", "-q", "."], root),
        "test_agent": run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], root),
        "paper_safety_agent": audit_portfolio(root / "dual_portfolio.json"),
        "workflow_agent": audit_hourly_schedule(root / ".github/workflows/whj-24h-development-team.yml"),
        "dashboard_integrity_agent": {
            "status": "passed" if file_fingerprint(root / "index.html") else "blocked",
            "dashboard_sha256": file_fingerprint(root / "index.html"),
            "write_access": False,
        },
    }
    failed = [name for name, result in agents.items() if result["status"] != "passed"]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "team": "WHJ 24/7 Development Council",
        "execution_model": "hourly GitHub Actions job; not a continuously running process",
        "mode": "free_read_only_quality_assurance",
        "status": "HEALTHY" if not failed else "NEEDS_ATTENTION",
        "agents": agents,
        "agent_count": len(agents),
        "failed_agents": failed,
        "improvement_backlog": backlog,
        "governance": {
            "source_code_auto_edits": False, "auto_merge": False,
            "live_trading_enabled": False, "paper_ledger_mutation": False,
            "paid_apis": False, "dashboard_modified": False,
            "repository_permission": "contents: read",
        },
        "limitations": [
            "The council performs deterministic checks, not autonomous semantic code generation.",
            "A report does not prove strategy profitability or market safety.",
            "GitHub Actions scheduling can be delayed by platform capacity and usage limits.",
        ],
    }


def write_report(root: Path = ROOT, output: Path = OUTPUT) -> dict:
    report = run_council(root)
    output.mkdir(parents=True, exist_ok=True)
    (output / "latest_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# WHJ 24/7 Development Council", "",
        f"- Generated UTC: {report['generated_at_utc']}",
        f"- Status: **{report['status']}**",
        f"- Specialist agents: {report['agent_count']}",
        "- Schedule: hourly GitHub Actions (not an always-on server)", "",
        "## Agent results", "",
        "| Agent | Status |", "|---|---|",
    ]
    for name, result in report["agents"].items():
        lines.append(f"| {name} | **{result['status']}** |")
    lines += ["", "## Improvement backlog"]
    if report["improvement_backlog"]:
        lines += [f"- {x['file']}:{x['line']} — {x['item']}" for x in report["improvement_backlog"]]
    else:
        lines.append("- No TODO/FIXME/NotImplementedError markers found.")
    lines += [
        "", "## Safety and permissions",
        "- Read-only repository permission; no source edits or auto-merges.",
        "- Live trading disabled; no paper-ledger writes; no paid APIs.",
        "- Dashboard is read-only and its SHA-256 fingerprint is recorded.",
        "", "## Limitations", *[f"- {x}" for x in report["limitations"]], "",
    ]
    (output / "latest_report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    report = write_report()
    print(
        f"WHJ development council: {report['status']}; "
        f"agents={report['agent_count']} failed={len(report['failed_agents'])}"
    )
    return 0 if report["status"] == "HEALTHY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
