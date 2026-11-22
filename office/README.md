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

## Paper-engine connection
The separate **WHJ Shared $100 Seven-Strategy Paper Portfolio** workflow runs the BTC strategies, multi-asset crypto/gold/silver paper engine, and six-agent paper decision module. After those steps finish, it runs `office/paper_bridge.py`. The bridge validates the paper-only outputs and writes `office/paper_bridge_report.json` with agent count, scanned markets, shared-wallet metrics, simulated trade counts, and safety flags. It is a read-only audit; it does not run the engine a second time or change the ledger.

The two-hour office cycle reads the latest bridge report and includes its status in `office/office_state.json` and the Actions summary. The bridge report is also published at `office/paper_bridge_report.json` in the dashboard site and attached to the paper workflow artifact. The bridge only reports the latest completed paper workflow; it is not a live feed.

## Reminders
The cycle writes the current owner, next owner, due-cycle number, pending handoff, and latest paper-engine status into `office/office_state.json`; the Actions summary displays the reminder. For phone access, open the repository's Actions tab and select **WHJ 24-hour Office Cycle**.

## Limits
GitHub Actions is not a persistent 24-hour process. Scheduled workflows are best-effort and repository plan limits apply. This workflow does not change the existing dashboard or trading workflows.
