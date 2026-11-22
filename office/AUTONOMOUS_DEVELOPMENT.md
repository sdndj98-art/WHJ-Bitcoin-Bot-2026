# WHJ autonomous development loop

## What runs

The **WHJ Autonomous Development Loop** is scheduled every two hours (12 times per day), matching the existing office rotation. It also supports manual dispatch.

Each eligible cycle:
1. Selects the next task from `autonomous_backlog.json`.
2. Creates or reuses a GitHub issue labeled `ai-office-task`.
3. Calls the bounded Gemini code agent for only the issue's explicitly listed files.
4. Runs patch-scope checks, Python compilation, and the full unit-test suite.
5. Creates an isolated branch and a **draft pull request** only if every check passes.

The manager allows only one open AI-generated draft PR at a time. After a task PR is merged, the next scheduled cycle advances to the next backlog item. Failed generation/test runs are counted; after three failures the task is labeled `ai-office-blocked` and skipped so it cannot consume quota forever. A closed, unmerged attempt is not silently overwritten; it is skipped for manual diagnosis.

## Required repository secret

Add `GEMINI_API_KEY` under **Settings → Secrets and variables → Actions → Repository secrets**. The key is read only by the code-generation job, never printed, committed, included in artifacts, or passed into the prompt.

The agent lists models available to the configured API key and selects one that advertises `generateContent` support (preferring Flash-Lite, then Flash, then Pro). You can override this by setting the `GEMINI_MODEL` environment variable to an explicit model ID. If discovery fails or quota is exhausted, the workflow stops without opening a PR. Model availability and free quota are not guaranteed.

## Safety boundaries

- The workflow does not write to `main` directly.
- The workflow never auto-merges a PR.
- The agent can edit only explicitly listed, allowlisted source/test files.
- Workflow files, dashboard assets, secrets, execution adapters, and deployment settings are outside the agent allowlist.
- Compilation and the full unit-test suite must pass before a draft PR is opened.
- Paper trading only; no exchange API keys, live orders, deposits, or Binance connection are used.
- A passing test suite is not proof of profitability.

## Limits

GitHub Actions is scheduled/best-effort, not a permanently running server. The backlog is finite and curated in `autonomous_backlog.json`; once all tasks have been attempted, new reviewed tasks must be added. Gemini/API quotas and GitHub Actions limits may delay or stop cycles. Human review is still required to merge every PR.
