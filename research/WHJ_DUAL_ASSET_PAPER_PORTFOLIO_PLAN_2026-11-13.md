# WHJ Dual-Asset Paper Portfolio Activation Plan — 2026-11-13

## User-approved virtual capital

Two independent paper portfolios are requested:
- BTC: USD 10.00 starting equity.
- Gold: USD 10.00 starting equity.
- Combined simulated equity: USD 20.00.

This is simulated capital only. No deposits, exchange credentials, broker credentials, live order routes, leverage, or real-money trading are permitted.

## Intended portfolio structure

Each asset is evaluated independently. The initial comparison design is five strategy sleeves per asset, each seeded with USD 2.00 (20% of that asset's USD 10.00 budget). A sleeve must never borrow cash or positions from another sleeve. Reports must show both sleeve-level and asset-level equity, fees, realized/unrealized P&L, completed trades, win rate, profit factor, drawdown, and feed status.

BTC and gold results must never be combined when ranking strategies. Bull/Bear/Risk reviews are explanatory decision records and cannot override the deterministic strategy/risk engine.

## Activation blockers — do not bypass

1. The existing `paper_account.py` ledger is BTC-specific: state stores units under a `btc` field and the existing multi-strategy helper hardcodes USD 1,000 per strategy. Do not reuse it for gold by silently relabelling BTC units.
2. The existing gold research uses Yahoo `GC=F` continuous COMEX futures, not spot XAUUSD. Its historical results underperformed matched buy-and-hold and did not meet the trade-count screen. This is not a valid substitute for a broker-specific XAUUSD forward feed.
3. A genuine gold paper path needs an identified public or broker demo *market-data-only* source, timezone/session handling, bid/ask or documented spread assumptions, commission, swap/financing treatment, and instrument contract/unit rules.
4. The BTC and gold ledgers need a shared asset-neutral implementation with separate state files and tests for isolation, restart/idempotency, fees, next-bar execution, and risk pauses.
5. A successful CI run and a first live-feed snapshot are required before the status can change to ACTIVE.

## Execution protocol

- Paper-only, long/flat initially; no leverage or short exposure until separately tested.
- Signals use completed candles only; fills occur no earlier than the next bar.
- Use conservative costs and publish the exact assumptions in every report.
- Reject stale, duplicated, out-of-order, incomplete, or mismatched candles; fail closed on unknown feed quality.
- Preserve existing risk guards. A daily loss pause, drawdown pause, or feed-integrity failure blocks new entries.
- Never reset an existing ledger automatically if its capital, asset, strategy, schema, or checksum does not match.
- Do not promote a strategy based on a tiny forward sample. Report insufficient evidence until a predeclared minimum sample and independent evaluation gates are met.

## Current status

`CONFIGURED_NOT_ACTIVE`

The requested USD 10 + USD 10 budgets are recorded as the target configuration, but no new dual-asset paper orders have been simulated yet. BTC can be adapted from the existing forward paper path after capital isolation and test coverage are added. Gold remains blocked until an appropriate XAUUSD feed and asset-neutral ledger are implemented and validated.

No claim of activation, trades, profit, or successful new tests is made by this planning document.
