# WHJ AI Research Office — MVP Architecture

## Purpose

Create a governed research organization that can later use multiple LLM workers to investigate Bitcoin and gold strategies. The organization is structured around a Chief of Staff, a Project Manager, 20 specialist workers, and two independent auditors.

## Implemented in this MVP

- A 24-role roster with stable role IDs.
- A 14-task research plan covering BTC and gold data, strategy inventory, market quality, execution costs, historical evaluation, walk-forward robustness, statistical validation, risk, red-team review, safety review, leadership synthesis, and project acceptance.
- Explicit task ownership, a separate reviewer, dependency links, acceptance criteria, and evidence fields.
- Dependency-cycle and governance validation.
- A command-line planner that writes JSON and Markdown.
- A scheduled GitHub Actions workflow at 00:00 UTC (03:00 Baghdad time) that validates the planner and uploads the nightly plan artifact.

## Important distinction: planning versus model execution

The office has a deterministic planner and a bounded Grok worker adapter. The adapter uses the xAI Responses API with structured JSON output and read-only repository excerpts. It does not expose shell, repository-write, exchange, broker, or paper-ledger tools.

The scheduled workflow only calls Grok when BOTH of these are explicitly configured:
- GitHub Actions secret: `XAI_API_KEY`
- Repository Actions variable: `WHJ_AGENT_AUTORUN=true`

If either is absent, the workflow creates the nightly plan only and makes zero model API calls. The default per-run budget guard is USD 0.50, with a maximum of 1,000 output tokens per call. The adapter records token usage and estimated cost, retries transient rate-limit/server errors, and stops before a call whose estimated cost would exceed the budget.

This does not mean 24 separate Grok subscriptions or 24 continuously running processes. The 24 roles are specialist responsibilities coordinated by a bounded run. A run calls only the roles needed by the task plan, sequentially, and may stop early at the budget guard.

The current Grok adapter creates research findings and review reports only. It does not autonomously patch or merge code. Model-generated findings are accepted only when every cited quote is an exact substring of a supplied repository file or prior agent report.

## Worker execution contract

Each worker must return a structured result containing:
- task ID and role ID;
- concise findings;
- exact repository files, dataset fingerprints, commit IDs, or workflow artifacts used;
- reproducible commands and test output where applicable;
- known limitations and unresolved questions;
- proposed patch paths (never directly merge);
- self-check results.

The Project Manager must reject results with missing evidence, unmet acceptance criteria, fabricated metrics, or conflicts with the task scope. The red-team reviewer independently attempts to falsify the findings. The safety auditor checks research isolation and verifies that no order path or unapproved paper-ledger mutation was used.

## Hard safety boundaries

- Research and paper-only.
- No live exchange or broker orders.
- No credentials in source files or logs.
- No automatic merge to main.
- No automatic strategy promotion.
- No automatic modification of existing paper ledgers or risk limits.
- Unknown or unavailable data must remain UNKNOWN, not be imputed as zero.
- Every experiment must retain dataset identity, code commit, parameters, time boundaries, costs, and output artifact references.

## xAI API cost and key handling

The Grok API is usage-billed, not included with a ChatGPT subscription. The current xAI documentation lists Grok 4.7 at USD 2 per million input tokens and USD 6 per million output tokens; verify current pricing before enabling scheduled runs. Keep the key in GitHub Actions Secrets or a local environment variable. Never paste it into chat, commit it, or write it to logs.

Official documentation: https://docs.x.ai/overview and https://docs.x.ai/developers/model-capabilities/text/structured-outputs

## Local Termux usage

From the repository root:

```bash
python whj_agent_office.py validate
python whj_agent_office.py plan
python -m unittest tests.test_whj_agent_office -v
```

The default plan files are written under `research/agent_office/`. They are generated artifacts and should not be treated as evidence that any candidate strategy is profitable.
