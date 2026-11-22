# WHJ 24-hour development office

This is a scheduled, deterministic coordination office—not autonomous AI employees and not an always-on server.

## Cycle
GitHub Actions runs on a schedule every two hours (12 scheduled cycles/day), plus manual dispatch. Each cycle rotates through a defined role, records the next handoff, and reports reminders in the Actions job summary. GitHub Actions can delay or skip scheduled runs; this is best-effort and not a guaranteed 24/7 SLA.

## Roles (handoff chain)
1. Coordinator → selects the next task and sets its due cycle.
2. Market-data QA → checks the data-quality task.
3. Strategy QA → reviews paper-strategy qualification.
4. Paper-engine QA → verifies simulated order/ledger behavior.
5. Dashboard QA → checks dashboard/report integration.
6. Risk QA → checks safeguards and stale-data blocks.
7. Release QA → summarizes blockers and hands the next item back to Coordinator.

Roles are scripted workflow steps. They do not independently write code, use paid AI APIs, place real orders, or access exchange secrets. The office must remain paper-trading/read-only until a separately reviewed execution adapter exists.

## Reminders
The cycle writes the current owner, next owner, due-cycle number, and pending handoff into `office/office_state.json`; the Actions summary displays the reminder. For phone access, open the repository's Actions tab and select **WHJ 24-hour Office Cycle**.

## Limits
GitHub Actions is not a persistent 24-hour process. Scheduled workflows are best-effort and repository plan limits apply. This workflow does not change the existing dashboard or trading workflows.
