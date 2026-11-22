"""Generate a bounded, issue-scoped WHJ code patch with Gemini.

This script only edits explicitly named existing source/test/documentation files.
The workflow must run tests and open a draft PR; it must never merge or trade live.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 3
MAX_FILE_CHARS = 18000
MAX_TOTAL_CONTEXT = 42000
ALLOWED = re.compile(r"^(?:whj_[a-z0-9_]+\.py|strategy_[a-z0-9_]+\.py|tests/test_[a-z0-9_]+\.py|office/[a-z0-9_]+\.md)$")
FILES_LINE = re.compile(r"^Files:\s*(.+)$", re.MULTILINE)


def parse_requested_files(body: str) -> list[str]:
    match = FILES_LINE.search(body)
    if not match:
        raise ValueError("Issue must include one line: Files: path1, path2")
    paths = [p.strip().strip("`") for p in match.group(1).split(",") if p.strip()]
    if not paths or len(paths) > MAX_FILES or len(set(paths)) != len(paths):
        raise ValueError(f"Choose 1-{MAX_FILES} unique existing files.")
    for path in paths:
        if not ALLOWED.fullmatch(path):
            raise ValueError(f"File is outside the agent allowlist: {path}")
        if not (ROOT / path).is_file():
            raise ValueError(f"Requested file does not exist: {path}")
    return paths


def github_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def gemini_generate(prompt: str, key: str, model: str) -> str:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 7000,
                             "responseMimeType": "application/json"},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # Do not echo request headers or the API key.
        raise RuntimeError(f"Gemini HTTP {exc.code}: {exc.read().decode(errors='replace')[:700}") from None
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
    if not text.strip():
        raise RuntimeError("Gemini returned no patch content.")
    return text


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    key = os.environ.get("GEMINI_API_KEY", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    issue_number = os.environ.get("ISSUE_NUMBER", "")
    if not all((token, key, repo, issue_number)):
        raise SystemExit("Missing required workflow environment (token/secret values are not printed).")
    issue = github_get(f"https://api.github.com/repos/{repo}/issues/{issue_number}", token)
    labels = {label.get("name") for label in issue.get("labels", [])}
    if "ai-office-task" not in labels:
        raise SystemExit("Issue must have the ai-office-task label.")
    body = issue.get("body") or ""
    forbidden = re.compile(r"(?i)\b(live trading|real money|bypass risk|remove risk limits|guaranteed profit|secret|api key)\b")
    if forbidden.search(body):
        raise SystemExit("Issue contains a restricted request; no code was generated.")
    paths = parse_requested_files(body)
    files = {}
    total = 0
    for path in paths:
        content = (ROOT / path).read_text(encoding="utf-8")
        if len(content) > MAX_FILE_CHARS:
            raise SystemExit(f"File too large for bounded context: {path}")
        total += len(content)
        files[path] = content
    if total > MAX_TOTAL_CONTEXT:
        raise SystemExit("Requested context exceeds the configured limit.")

    prompt = (
        "You are a cautious WHJ software engineer. Return ONLY valid JSON of shape "
        '{"files":[{"path":"exact path","content":"complete replacement text"}]} . '
        "Modify only the exact paths provided; preserve existing behavior except the issue task. "
        "Add or update tests when appropriate. Do not add dependencies, workflows, credentials, "
        "exchange execution, live orders, or weaken paper/risk safeguards. Do not claim profitability. "
        "Every file content must be complete UTF-8 text. Do not include markdown fences.\n\n"
        f"ISSUE #{issue_number}: {issue.get('title','')}\n{body}\n\n"
        "CURRENT FILES:\n" + json.dumps(files, ensure_ascii=False)
    )
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    raw = gemini_generate(prompt, key, model)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Gemini response was not valid JSON at character {exc.pos}.") from None
    proposed = result.get("files")
    if not isinstance(proposed, list) or len(proposed) != len(paths):
        raise SystemExit("Patch must return exactly one replacement for each requested file.")
    seen = set()
    for item in proposed:
        if not isinstance(item, dict) or set(item) != {"path", "content"}:
            raise SystemExit("Invalid file object in generated patch.")
        path, content = item["path"], item["content"]
        if path not in paths or path in seen or not isinstance(content, str):
            raise SystemExit("Generated patch attempted an unrequested path or duplicate.")
        if len(content) > MAX_FILE_CHARS:
            raise SystemExit(f"Generated file exceeds size limit: {path}")
        if "\x00" in content:
            raise SystemExit("Binary/NUL content rejected.")
        seen.add(path)
    if seen != set(paths):
        raise SystemExit("Generated patch omitted a requested file.")
    for item in proposed:
        (ROOT / item["path"]).write_text(item["content"], encoding="utf-8")
    print(f"Generated bounded patch for issue #{issue_number}: {', '.join(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
