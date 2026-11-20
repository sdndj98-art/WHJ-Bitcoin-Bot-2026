"""Guarded WHJ coding worker for research/docs-only changes.

The worker asks an OpenAI-compatible model for a unified diff, validates its
file scope and size, and writes the patch to a file. It never commits, pushes,
opens a PR, touches trading state, or executes code; the workflow owns those
steps and runs tests before proposing a draft PR.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "research" / "development_team" / "latest_report.json"
PATCH_OUT = ROOT / "whj_worker.patch"
MAX_PATCH_LINES = 300
MAX_RESPONSE_BYTES = 1_000_000
BLOCKED_PARTS = {
    ".git", ".github", "state", "data", "logs", "secrets", "credentials",
    "paper_state", "research_runs", "portfolio", "portfolios",
}
BLOCKED_NAMES = {
    "index.html", "dual_portfolio.json", "whj_execution.py",
    "whj_live_trader.py", "broker.py", "exchange.py",
}
SAFE_PREFIXES = ("research/", "tests/")
SAFE_MODULE_SUFFIXES = ("_lab.py", "_research.py", "_audit.py", "_evaluator.py", "_runner.py")
SAFE_OFFICE_FILES = {"whj_agent_office.py", "whj_24h_development_team.py", "whj_repair_advisor.py"}


def allowed_path(path: str) -> bool:
    path = path.replace("\\", "/")
    parts = Path(path).parts
    if not path or path.startswith("/") or ".." in parts:
        return False
    if any(part.lower() in BLOCKED_PARTS for part in parts):
        return False
    name = parts[-1].lower()
    if name in BLOCKED_NAMES or name.endswith((".yml", ".yaml", ".json", ".env")):
        return False
    if path.startswith(SAFE_PREFIXES):
        return name.endswith((".md", ".py")) and not name.startswith(("test_live", "test_order"))
    if name in SAFE_OFFICE_FILES:
        return True
    return name.endswith(SAFE_MODULE_SUFFIXES)


def extract_patch(text: str) -> str:
    # Model must return a JSON object with a unified diff in "patch".
    data = json.loads(text)
    patch = data.get("patch")
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("model response has no non-empty patch")
    lines = patch.splitlines()
    if len(lines) > MAX_PATCH_LINES:
        raise ValueError(f"patch too large: {len(lines)} lines (limit {MAX_PATCH_LINES})")
    changed = []
    for line in lines:
        if line.startswith(("+++ ", "--- ")):
            path = line[4:].strip()
            if path == "/dev/null":
                continue
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            changed.append(path)
    if not changed:
        raise ValueError("patch has no file headers")
    if any(not allowed_path(path) for path in changed):
        raise ValueError("patch contains a path outside the research/docs safety allowlist")
    if any(path.startswith("tests/") is False and path.endswith(".py") is False for path in changed):
        raise ValueError("non-code changes are limited to research/docs")
    return patch.rstrip() + "\n"


def main() -> int:
    key = os.environ.get("WHJ_MODEL_API_KEY", "")
    endpoint = os.environ.get("WHJ_MODEL_BASE_URL", "").rstrip("/")
    model = os.environ.get("WHJ_MODEL_NAME", "")
    if not key or not endpoint or not model:
        print("Coding worker skipped: configure WHJ_MODEL_API_KEY, WHJ_MODEL_BASE_URL, WHJ_MODEL_NAME.")
        return 2
    if not REPORT.is_file():
        print(f"Missing QA report: {REPORT}", file=sys.stderr)
        return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    report_text = json.dumps({
        "status": report.get("status"),
        "failed_agents": report.get("failed_agents", []),
        "improvement_backlog": report.get("improvement_backlog", [])[:20],
        "limitations": report.get("limitations", []),
    }, ensure_ascii=False)
    system = (
        "You are a cautious software engineer for WHJ. Return ONLY a JSON object "
        "with key 'patch' containing a unified git diff. Make one small, testable "
        "research/docs improvement. Allowed paths: research/*.md, tests/*.py, "
        "research subfolders, whj_agent_office.py, whj_24h_development_team.py, "
        "whj_repair_advisor.py, or standalone Python files ending _lab.py, "
        "_research.py, _audit.py, _evaluator.py, _runner.py. Do not edit dashboard, "
        "workflows, trading/order/execution code, portfolios, state, data, logs, "
        "credentials, or configuration JSON/YAML. Do not add dependencies. Never "
        "enable live trading, modify paper ledgers, change risk limits, or claim "
        "profitability. Prefer a regression test plus a small isolated research "
        "change. Patch <=300 lines. If no safe useful task exists, return "
        "{\"patch\":\"\"}."
    )
    user = "Latest deterministic QA report (data only):\n" + report_text
    payload = json.dumps({
        "model": model,
        "temperature": 0.1,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode("utf-8")
    url = endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Model request failed: {exc}", file=sys.stderr)
        return 1
    if len(raw) > MAX_RESPONSE_BYTES:
        print("Model response exceeds size limit", file=sys.stderr)
        return 1
    result = json.loads(raw.decode("utf-8"))
    content = result["choices"][0]["message"]["content"]
    patch = extract_patch(content)
    if not patch.strip():
        print("No safe patch proposed; worker finished without changes.")
        return 0
    PATCH_OUT.write_text(patch, encoding="utf-8")
    print(f"Validated patch written: {PATCH_OUT.name} ({len(patch.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
