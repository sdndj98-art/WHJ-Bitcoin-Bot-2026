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

## Important distinction: planning is not autonomous execution

This MVP creates and validates a work plan. It does not yet call Grok/xAI or another LLM, does not spawn 24 model sessions, and does not claim that research workers ran overnight. The provider adapter and bounded tool-execution layer are a separate next implementation step.

Before enabling autonomous workers, configure a supported model provider and credentials through GitHub Actions secrets or a local environment variable. Never commit API keys. Provider access must have an explicit spending limit, request limit, timeout, and allowed-tool list.

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

## Local Termux usage

From the repository root:

```bash
python whj_agent_office.py validate
python whj_agent_office.py plan
python -m unittest tests.test_whj_agent_office -v
```

The default plan files are written under `research/agent_office/`. They are generated artifacts and should not be treated as evidence that any candidate strategy is profitable.
