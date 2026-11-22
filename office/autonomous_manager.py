"""Scheduled issue-driven task manager for the WHJ autonomous development loop.

The manager only selects from a reviewed, finite backlog and opens a labeled issue.
A separate workflow invokes the bounded Gemini code agent, runs the full test suite,
and creates a draft PR. No direct pushes to main and no auto-merge.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "office" / "autonomous_backlog.json"
LABEL = "ai-office-task"
BRANCH_PREFIX = "ai-office/auto-"


def select_next_task(
    tasks: list[dict[str, Any]],
    pull_requests: list[dict[str, Any]],
    remote_branches: set[str],
) -> dict[str, Any] | None:
    """Return the first not-yet-attempted task; never overlap an active AI PR."""
    if any(
        str(pr.get("state", "")).upper() == "OPEN"
        and str(pr.get("headRefName", "")).startswith(BRANCH_PREFIX)
        for pr in pull_requests
    ):
        return None

    merged = {
        str(pr.get("headRefName"))
        for pr in pull_requests
        if pr.get("mergedAt") and pr.get("headRefName")
    }
    attempted = {str(pr.get("headRefName")) for pr in pull_requests if pr.get("headRefName")}

    for task in tasks:
        branch = BRANCH_PREFIX + str(task["id"])
        if branch in merged:
            continue
        if branch in remote_branches or branch in attempted:
            # A prior branch exists but is not merged: do not overwrite or retry it.
            continue
        return {**task, "branch": branch}
    return None


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=check,
    )


def gh_json(args: list[str]) -> Any:
    result = run(["gh", *args])
    return json.loads(result.stdout or "[]")


def remote_branch_names() -> set[str]:
    result = run(["git", "ls-remote", "--heads", "origin"])
    names = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1].startswith("refs/heads/"):
            names.add(fields[1][len("refs/heads/"):])
    return names


def append_summary(message: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")


def main() -> int:
    tasks = json.loads(BACKLOG.read_text(encoding="utf-8"))
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit("Autonomous development backlog is empty or invalid.")

    prs = gh_json([
        "pr", "list", "--state", "all", "--limit", "100",
        "--json", "headRefName,mergedAt,state",
    ])
    branches = remote_branch_names()
    task = select_next_task(tasks, prs, branches)
    if task is None:
        message = (
            "## WHJ autonomous development manager\n\n"
            "- No task launched this cycle. An AI draft PR may still be under review, "
            "or all queued tasks have already been attempted.\n"
        )
        append_summary(message)
        print("No eligible backlog task.")
        return 0

    # Create the label if it does not exist. An existing label is harmless.
    run([
        "gh", "label", "create", LABEL, "--color", "0E8A16",
        "--description", "Reviewed task for the bounded WHJ AI code agent",
    ], check=False)

    open_issues = gh_json([
        "issue", "list", "--state", "open", "--label", LABEL,
        "--limit", "100", "--json", "number,title",
    ])
    issue = next((item for item in open_issues if item.get("title") == task["title"]), None)
    if issue:
        issue_number = int(issue["number"])
    else:
        created = run([
            "gh", "issue", "create", "--title", task["title"],
            "--body", task["body"], "--label", LABEL,
        ])
        match = re.search(r"/issues/(\d+)\s*$", created.stdout.strip())
        if not match:
            raise SystemExit("Could not determine the created issue number.")
        issue_number = int(match.group(1))

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"has_task=true\n")
            handle.write(f"issue_number={issue_number}\n")
            handle.write(f"task_id={task['id']}\n")
            handle.write(f"branch={task['branch']}\n")
            handle.write(f"task_title={task['title']}\n")

    append_summary(
        "## WHJ autonomous development manager\n\n"
        f"- Selected task: **{task['title']}**\n"
        f"- Issue: #{issue_number}\n"
        f"- Isolated branch: `{task['branch']}`\n"
        "- Next gates: bounded Gemini patch → compile → full tests → paper-safety → draft PR\n"
        "- Auto-merge: disabled\n"
    )
    print(f"Selected {task['id']} as issue #{issue_number}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
