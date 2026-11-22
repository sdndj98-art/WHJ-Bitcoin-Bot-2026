# WHJ AI code-development office: implementation plan

## Current verified state

- `office/gemini_advisor.py` calls Gemini for a read-only advisory report.
- `whj_24h_development_team.py` performs deterministic audits and tests.
- `whj_24h_development_team.yml` runs hourly with `contents: read`.
- The office rotation coordinates tasks and paper-trading checks; it does not edit code.
- A successful workflow run proves that its configured steps completed, not that a strategy is profitable or live trading is running.

## Goal

Add a controlled code-development loop that turns a concrete, reviewed task into a tested pull request. It must not write directly to `main`, merge its own PR, or enable live orders.

## Proposed stages

1. **Task intake** — accept a specific issue with a dedicated label (for example, `ai-office-task`). Reject vague tasks, tasks asking for secrets, live trading, risk-limit bypasses, or guaranteed returns.
2. **Context gathering** — read only the files relevant to the issue and the existing test instructions. Never pass repository secrets or environment values to the model.
3. **Patch generation** — ask the configured Gemini model for a bounded unified diff or a single-file replacement. Validate the response format and reject unexpected paths, binary changes, workflow permission changes, secret references, and edits to live-execution adapters.
4. **Isolated branch** — create a unique branch from the current default branch. Apply only the validated patch; do not commit to `main`.
5. **Automated checks** — run syntax/compile checks, targeted tests, the existing Python suite, dashboard contracts, and paper-safety checks as appropriate. Fail closed if tests cannot run.
6. **Pull request** — open a draft PR with the issue, files changed, test results, and model-generated rationale clearly identified. Require a human review before merge.
7. **Handoff** — publish the PR and test summary as an artifact and assign the next office role/task.

## Required security settings

- Use a narrowly scoped `GITHUB_TOKEN` with `contents: write` and `pull-requests: write` only in the dedicated code-agent job; keep audit workflows read-only.
- Keep `GEMINI_API_KEY` in GitHub Actions Secrets. Never print it, include it in prompts, commit it, or send it to artifacts.
- Restrict the agent to an allowlist of source/test/documentation paths. Do not let model output modify workflow permissions, deployment settings, secret handling, or live-trading controls.
- Pin third-party actions to reviewed commit SHAs before enabling automated writes.
- Use concurrency controls, a job timeout, patch-size limits, and explicit test failure gates.
- Never auto-merge. Paper-only mode and the virtual $100 account remain unchanged.

## Acceptance criteria

- A labeled task produces either a clearly explained rejection or a draft PR.
- The PR contains a bounded diff and test evidence.
- Failed tests prevent PR creation (or mark the PR blocked).
- The default branch remains unchanged until a human merges.
- No real orders, deposits, or exchange credentials are used.
- Performance claims require fee/slippage-aware out-of-sample and forward paper evidence.

## Important limitation

GitHub Actions is scheduled/best-effort, not a persistent 24/7 computer. This plan describes the missing implementation; creating this document alone does not activate an AI code-writing agent.
