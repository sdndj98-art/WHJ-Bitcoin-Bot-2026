# WHJ Termux Bridge

## Purpose

The agent runs locally in Termux and polls GitHub Issue 102 for authenticated task envelopes. ChatGPT can submit tasks and read results through the connected GitHub integration. This is a task relay, not a direct socket from ChatGPT to the phone.

Task queue: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/issues/102

## Install on Termux

1. Ensure the project working tree is clean.
2. Fetch and switch to the bridge branch without deleting your existing feature branch:

   git fetch origin bridge/termux-agent-20261110
   git switch -c bridge/termux-agent-20261110 --track origin/bridge/termux-agent-20261110

3. Create a fine-grained GitHub personal access token for ONLY this repository:
   - Contents: Read and write
   - Issues: Read and write
   - Metadata: Read-only
   - No Actions, Administration, Workflows, or Secrets permissions.

4. Run:

   bash scripts/setup_whj_bridge.sh

The token is entered through a hidden prompt and stored outside the repository at:
~/.config/whj-bridge/github_token
File permissions are restricted to the Termux app user. Never send the token to ChatGPT or post it in an issue.

## Task protocol

Only comments authored by the repository owner account sdndj98-art are accepted. A task comment contains:

<!-- WHJ_TASK {"id":"unique-task-id","op":"status"} -->

Supported operations:
- status
- git_status
- git_diff
- tests
- compile
- read_file (safe source/documentation paths only)
- write_file (safe source/documentation paths only; content max 120 KB)
- commit_push (only on bridge/termux-agent-20261110)

The agent posts a result comment with the matching task ID. Issue comments are public because this repository is public. Never include secrets, private logs, account data, or exchange credentials in tasks.

## Safety boundaries

- No arbitrary shell command execution.
- No access to state/, data/, logs/, .git/, .github/, virtual environments, or secret paths.
- No collector inspection, stop, restart, or signal operations.
- No live exchange orders or real-money trading.
- No changes to workflows, deployments, repository secrets, or GitHub settings.
- No push to main. Commits can be pushed only to the dedicated bridge branch.
- The agent does not merge to main.
- Tests run only the fixed unittest discovery command; compile runs py_compile over project Python files.
- File writes are backed up outside the repository before replacement.
- All operations are recorded in ~/.config/whj-bridge/audit.jsonl.

## Start / inspect

The setup script starts the polling agent. Log:
~/.config/whj-bridge/agent.log

The poll interval is 25 seconds. Termux battery optimization may stop background work; allow Termux background operation if needed. The agent does not open a listening network port.

## Stop

Find the agent PID with:
pgrep -af whj_bridge_agent.py

Stop only the bridge process (not the Kraken collector) with:
kill PID

Unlock wake lock if desired:
termux-wake-unlock

## Important limitation

The ChatGPT GitHub integration can submit and read issue tasks, but it cannot itself open a direct TCP connection to this phone. The agent polls GitHub outbound over HTTPS. A task is not considered complete until its result comment appears on Issue 102.
