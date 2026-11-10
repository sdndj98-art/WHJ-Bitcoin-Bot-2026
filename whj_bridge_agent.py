#!/usr/bin/env python3
"""Restricted, auditable GitHub-Issue task agent for WHJ on Termux."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = "sdndj98-art/WHJ-Bitcoin-Bot-2026"
ISSUE = 102
OWNER = "sdndj98-art"
BRANCH = "bridge/termux-agent-20261110"
API = "https://api.github.com"
CONFIG = Path.home() / ".config" / "whj-bridge"
TOKEN_FILE = CONFIG / "github_token"
CURSOR_FILE = CONFIG / "cursor.json"
AUDIT_FILE = CONFIG / "audit.jsonl"
BACKUP_DIR = CONFIG / "backups"
MAX_TASK_BYTES = 120_000
MAX_OUTPUT = 12_000
POLL_SECONDS = 25

FORBIDDEN_PARTS = {
    ".git", ".github", "state", "data", "logs", "secrets",
    ".venv", "venv", "__pycache__", ".whj_bridge",
}
ALLOWED_SUFFIXES = {".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".html", ".css", ".js"}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
]


def audit(event: dict) -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    event = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), **event}
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def redact(value: str) -> str:
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value[:MAX_OUTPUT]


def token() -> str:
    if not TOKEN_FILE.is_file():
        raise RuntimeError("Missing token file: " + str(TOKEN_FILE))
    value = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if len(value) < 20:
        raise RuntimeError("GitHub token file is empty or invalid")
    return value


def api(method: str, path: str, payload: dict | None = None, authenticated: bool = False):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "WHJ-Termux-Bridge/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if authenticated:
        headers["Authorization"] = "Bearer " + token()
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read(2_000_000)
        return json.loads(raw.decode("utf-8")) if raw else {}


def git(args: list[str], timeout: int = 30, env: dict | None = None) -> str:
    p = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        timeout=timeout, env=env,
    )
    output = (p.stdout or "") + (p.stderr or "")
    if p.returncode:
        raise RuntimeError("git failed: " + redact(output))
    return redact(output.strip())


def safe_path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw or len(raw) > 240:
        raise ValueError("invalid path")
    rel = Path(raw)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError("path traversal or absolute path rejected")
    if any(part.lower() in FORBIDDEN_PARTS for part in rel.parts):
        raise ValueError("protected path rejected")
    if rel.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("file extension is not allowed")
    target = ROOT / rel
    parent = target.parent.resolve()
    if parent != ROOT and ROOT not in parent.parents:
        raise ValueError("path escapes project root")
    for part in rel.parts[:-1]:
        probe = ROOT.joinpath(*rel.parts[:rel.parts.index(part) + 1])
        if probe.is_symlink():
            raise ValueError("symlink directories are not allowed")
    if target.exists() and target.is_symlink():
        raise ValueError("symlinks are not allowed")
    return target


def ensure_branch() -> None:
    current = git(["branch", "--show-current"]).strip()
    if current == BRANCH:
        return
    dirty = git(["status", "--porcelain"]).strip()
    if dirty:
        raise RuntimeError("working tree is not clean; refusing to switch branches")
    exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/" + BRANCH],
        cwd=ROOT,
    ).returncode == 0
    if exists:
        git(["switch", BRANCH])
    else:
        if current == "main":
            raise RuntimeError("refusing to create bridge branch directly from main")
        git(["switch", "-c", BRANCH])
    audit({"event": "branch_ready", "branch": BRANCH, "base": current})


def run_fixed_tests() -> str:
    p = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    return redact((p.stdout or "") + (p.stderr or "") + f"\nexit_code={p.returncode}")


def run_compile() -> str:
    files = sorted(str(p.relative_to(ROOT)) for p in ROOT.glob("*.py"))
    test_dir = ROOT / "tests"
    if test_dir.exists():
        files += sorted(str(p.relative_to(ROOT)) for p in test_dir.rglob("*.py") if p.is_file())
    if not files:
        return "No Python files found"
    p = subprocess.run(
        [sys.executable, "-m", "py_compile", *files],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    return redact((p.stdout or "") + (p.stderr or "") + f"\nexit_code={p.returncode}")


def task_status() -> dict:
    return {
        "branch": git(["branch", "--show-current"]),
        "commit": git(["log", "-1", "--oneline"]),
        "status": git(["status", "--short"]),
        "collector_processes": "not inspected; collector control is prohibited",
        "live_trading": "DISABLED_BY_POLICY",
        "protected_state_access": "DENIED_BY_POLICY",
    }


def execute(task: dict) -> dict:
    op = task.get("op")
    if op == "status":
        return task_status()
    if op == "git_status":
        return {"status": git(["status", "--short"]), "branch": git(["branch", "--show-current"])}
    if op == "git_diff":
        return {"diff": git(["diff", "--", "*.py", "*.md", "*.toml", "*.txt"], timeout=60)}
    if op == "tests":
        return {"tests": run_fixed_tests()}
    if op == "compile":
        return {"compile": run_compile()}
    if op == "read_file":
        target = safe_path(task.get("path"))
        if not target.is_file():
            raise ValueError("file not found")
        return {"path": str(target.relative_to(ROOT)), "content": redact(target.read_text(encoding="utf-8"))}
    if op == "write_file":
        target = safe_path(task.get("path"))
        content = task.get("content")
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_TASK_BYTES:
            raise ValueError("content missing or exceeds size limit")
        ensure_branch()
        if target.exists():
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = BACKUP_DIR / (stamp + "-" + target.name + ".bak")
            backup.write_bytes(target.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".whj-tmp")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, target)
        audit({"event": "write_file", "path": str(target.relative_to(ROOT)), "bytes": len(content.encode("utf-8"))})
        return {"written": str(target.relative_to(ROOT)), "bytes": len(content.encode("utf-8")), "branch": BRANCH}
    if op == "commit_push":
        current = git(["branch", "--show-current"]).strip()
        if current != BRANCH:
            raise RuntimeError("commit_push is allowed only on " + BRANCH)
        changed = git(["status", "--porcelain"]).splitlines()
        paths = []
        for line in changed:
            path = line[3:].strip().strip('"')
            if not path:
                continue
            safe_path(path)
            paths.append(path)
        if not paths:
            return {"message": "no changes to commit"}
        git(["add", "--", *paths])
        git(["commit", "-m", str(task.get("message") or "WHJ bridge: verified development change")[:120]], timeout=120)
        helper = CONFIG / "git-askpass"
        helper.write_text(
            "#!/data/data/com.termux/files/usr/bin/python\n"
            "import sys\n"
            "from pathlib import Path\n"
            "p=Path.home()/'.config'/'whj-bridge'/'github_token'\n"
            "prompt=' '.join(sys.argv[1:]).lower()\n"
            "print('x-access-token' if 'username' in prompt else p.read_text().strip())\n",
            encoding="utf-8",
        )
        helper.chmod(0o700)
        env = os.environ.copy()
        env.update({"GIT_ASKPASS": str(helper), "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
        remote = git(["remote", "get-url", "origin"]).strip()
        if not remote.startswith("https://github.com/" + REPO):
            raise RuntimeError("origin must be HTTPS URL for the configured repository")
        pushed = git(["push", "-u", "origin", BRANCH], timeout=180, env=env)
        return {"commit": git(["log", "-1", "--oneline"]), "push": pushed, "branch": BRANCH}
    raise ValueError("operation not allowed")


def parse_task(body: str) -> dict | None:
    marker = "<!-- WHJ_TASK "
    start = body.find(marker)
    if start < 0:
        return None
    end = body.find("-->", start)
    if end < 0:
        return None
    raw = body[start + len(marker):end].strip()
    if len(raw.encode("utf-8")) > MAX_TASK_BYTES:
        raise ValueError("task exceeds size limit")
    task = json.loads(raw)
    if not isinstance(task, dict) or not isinstance(task.get("id"), str):
        raise ValueError("task must be JSON object with string id")
    return task


def post_result(task_id: str, result: dict, error: bool = False) -> None:
    payload = {
        "body": (
            f"<!-- WHJ_RESULT {task_id} -->\n"
            f"WHJ Bridge result: {'ERROR' if error else 'OK'}\n\n"
            + json.dumps(result, ensure_ascii=False, indent=2)[:MAX_OUTPUT]
        )
    }
    api("POST", f"/repos/{REPO}/issues/{ISSUE}/comments", payload, authenticated=True)


def load_cursor() -> int:
    try:
        return int(json.loads(CURSOR_FILE.read_text()).get("last_comment_id", 0))
    except Exception:
        return 0


def save_cursor(comment_id: int) -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    temp = CURSOR_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"last_comment_id": comment_id}), encoding="utf-8")
    os.replace(temp, CURSOR_FILE)


def poll_once() -> int:
    cursor = load_cursor()
    page = 1
    comments = []
    while page <= 5:
        batch = api("GET", f"/repos/{REPO}/issues/{ISSUE}/comments?per_page=100&page={page}")
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    comments.sort(key=lambda x: int(x.get("id", 0)))
    processed = 0
    for comment in comments:
        cid = int(comment.get("id", 0))
        if cid <= cursor:
            continue
        if (comment.get("user") or {}).get("login") != OWNER:
            save_cursor(cid)
            cursor = cid
            continue
        task = None
        try:
            task = parse_task(comment.get("body") or "")
            if task is None:
                save_cursor(cid)
                cursor = cid
                continue
            task_id = task["id"]
            result = execute(task)
            post_result(task_id, result)
            audit({"event": "task_ok", "task_id": task_id, "op": task.get("op"), "comment_id": cid})
            processed += 1
        except Exception as exc:
            task_id = task.get("id", "unknown") if isinstance(task, dict) else "invalid"
            message = redact(f"{type(exc).__name__}: {exc}")
            try:
                post_result(str(task_id), {"error": message}, error=True)
            except Exception as post_exc:
                print("Could not post task result:", redact(str(post_exc)), flush=True)
                break
            audit({"event": "task_error", "task_id": str(task_id), "comment_id": cid, "error": message})
        save_cursor(cid)
        cursor = cid
    return processed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    args = parser.parse_args()
    CONFIG.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        print("Missing GitHub token. See docs/WHJ_TERMUX_BRIDGE.md", file=sys.stderr)
        return 2
    print(f"WHJ Bridge started | repo={REPO} | issue=#{ISSUE} | branch={BRANCH}", flush=True)
    print("Policy: no live trading, no state access, no collector control, no arbitrary shell.", flush=True)
    while True:
        try:
            count = poll_once()
            if count:
                print(f"Processed {count} task(s)", flush=True)
        except urllib.error.HTTPError as exc:
            print("GitHub HTTP error:", exc.code, flush=True)
        except Exception as exc:
            print("Bridge error:", redact(f"{type(exc).__name__}: {exc}"), flush=True)
        if args.once:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
