"""WHJ 24/7 development team: zero-cost repository QA and improvement backlog.

This is an hourly GitHub Actions worker, not a continuously running server.
It performs reproducible local checks and writes an evidence report artifact.
It never edits source files, merges code, touches paper ledgers, or places orders.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "research" / "development_team"
EXCLUDED = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def tracked_python_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDED for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def run_command(command: list[str]) -> dict:
    try:
        proc = subprocess.run(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=900, check=False,
        )
        return {
            "command": command,
            "exit_code": proc.returncode,
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


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = tracked_python_files()
    syntax = []
    backlog = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=rel)
            syntax.append({"file": rel, "status": "passed"})
            for number, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if any(tag in stripped for tag in ("TODO", "FIXME", "NotImplementedError")):
                    backlog.append({"file": rel, "line": number, "item": stripped[:240]})
        except (OSError, UnicodeError, SyntaxError) as exc:
            syntax.append({"file": rel, "status": "failed", "error": str(exc)})

    compile_result = run_command([sys.executable, "-m", "compileall", "-q", "."])
    tests_result = run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    checks = {
        "python_ast": {
            "status": "passed" if all(x["status"] == "passed" for x in syntax) else "failed",
            "files_checked": len(syntax), "files": syntax,
        },
        "compileall": compile_result,
        "unit_tests": tests_result,
    }
    all_ok = all(x["status"] == "passed" for x in checks.values())
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "team": "WHJ 24/7 Development Team",
        "execution_model": "hourly GitHub Actions job; not a continuously running process",
        "mode": "free_local_quality_assurance",
        "status": "HEALTHY" if all_ok else "NEEDS_ATTENTION",
        "checks": checks,
        "improvement_backlog": backlog,
        "governance": {
            "source_code_auto_edits": False,
            "auto_merge": False,
            "live_trading_enabled": False,
            "paper_ledger_mutation": False,
            "paid_apis": False,
            "dashboard_modified": False,
        },
        "limitations": [
            "Static scans and tests do not prove strategy profitability or market safety.",
            "Semantic code changes require a reviewed pull request; this worker does not invent or apply them.",
            "GitHub Actions scheduling can be delayed by platform capacity and usage limits.",
        ],
    }
    (OUTPUT / "latest_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# WHJ 24/7 Development Team",
        "",
        f"- Generated UTC: {report['generated_at_utc']}",
        f"- Status: **{report['status']}**",
        "- Schedule: hourly GitHub Actions run (not an always-on server)",
        "",
        "## Quality checks",
    ]
    for name, check in checks.items():
        lines.append(f"- {name}: **{check['status']}**")
        if name == "python_ast":
            lines.append(f"  - Python files checked: {check['files_checked']}")
        else:
            lines.append(f"  - Exit code: {check['exit_code']}")
    lines += ["", "## Improvement backlog"]
    if backlog:
        lines += [f"- {x['file']}:{x['line']} — {x['item']}" for x in backlog]
    else:
        lines.append("- No TODO/FIXME/NotImplementedError markers found.")
    lines += [
        "", "## Safety",
        "- No source edits, auto-merges, paid APIs, live trades, or paper-ledger writes.",
        "- Dashboard is not modified.",
        "", "## Limits",
        *[f"- {x}" for x in report["limitations"]], "",
    ]
    (OUTPUT / "latest_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"WHJ development team: {report['status']}; python_files={len(files)}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
