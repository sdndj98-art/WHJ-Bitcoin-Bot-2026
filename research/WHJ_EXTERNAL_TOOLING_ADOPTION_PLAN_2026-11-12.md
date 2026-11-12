# WHJ external quantitative tooling adoption plan — 2026-11-12

## Decision

Adopt the ten referenced projects selectively as optional research/data/reporting components. Do not turn the research branch into an autonomous live-trading stack. WHJ remains paper-only; no exchange order endpoint, trading credential, withdrawal permission, or live execution path is to be added by this plan.

The existing repository already has a causal candle evaluator, an isolated 17-family BTC signal library/runner, forward-only paper ledgers, a scheduled monitor, and a browser dashboard. Avoid duplicating those components or adding heavyweight dependencies to the Termux runtime without a measured need.

## Tool-by-tool disposition

| Project | WHJ disposition | Intended boundary |
|---|---|---|
| Cryptofeed | **Priority candidate for the CVD/data-quality gap** | Isolated public trade/order-book collector; timestamped append-only events, reconnect/backfill checks, sequence-gap detection, explicit UNKNOWN when continuity is broken. No order capability. |
| CCXT | **Optional adapter, later** | Public OHLCV/ticker/market metadata across venues for independent data replication. Do not instantiate private clients or expose create/cancel order methods to the bot. |
| Freqtrade | **External benchmark, not embedded executor** | Run a separate dry-run comparison of selected rules after parity tests. Never connect its live mode or credentials to WHJ. |
| VectorBT | **Optional offline research benchmark** | Compare signal/event-study calculations against WHJ's evaluator on identical data, timestamps, fills, costs and benchmark intervals. Do not use its ranking alone for promotion. |
| TA-Lib | **Not required now** | Existing indicator code avoids native-build friction on Android/Termux. Consider only after numerical parity tests and a reproducible install matrix. |
| skfolio | **Deferred** | Portfolio research only after multiple independent candidates have sufficient forward evidence and realistic covariance/cost inputs. No leverage or risk-budget increase. |
| QuantStats | **Optional reporting validation** | Cross-check return-series metrics against WHJ reports; explicitly label periodic-return and close-only metrics. Do not treat a generated tear sheet as proof of profitability. |
| DuckDB | **Priority for immutable research analytics** | Queryable research snapshots/trade-event exports and reproducible reports. Never use it as a replacement for the existing guarded paper-ledger persistence without migration tests. |
| APScheduler | **Do not add yet** | GitHub Actions already schedules repository jobs. Avoid duplicate schedulers and overlapping monitor cycles. Reconsider only for a supervised local Termux daemon with locking and restart recovery. |
| TradingView Lightweight Charts | **Reuse existing dashboard first** | Add trade markers/equity panels only if current dashboard lacks them; keep visualization read-only and do not send orders from chart interactions. |

## Implementation sequence

### Phase 0 — safety and inventory
- Keep all existing workflows, credentials, paper ledgers, risk limits and order-path boundaries unchanged.
- Record exact upstream versions, Python compatibility, license, transitive dependencies and Android/Termux installability before adding any package.
- Add dependency pins only in an isolated optional research extra; core paper monitoring must continue to run without optional packages.

### Phase 1 — repair the evidence pipeline (highest priority)
- Design a public-only trade collector around Cryptofeed (or a minimal exchange-specific websocket client if compatibility/continuity tests fail).
- Persist timestamped raw trade events and a durable checkpoint; detect reconnects, duplicate/out-of-order events, missing sequence ranges, stale feeds and clock skew.
- Build CVD only from a complete, verified interval. Missing, stale or discontinuous input must remain UNKNOWN and block any CVD-required paper entry.
- Add replay tests from captured fixtures, restart/resume tests, idempotency tests and explicit no-ledger-mutation tests.
- Do not weaken or disable the existing CVD fail-closed guard to create trades.

### Phase 2 — independent evaluator parity
- Use VectorBT and/or Freqtrade strictly as independent dry-run/research comparators.
- Feed the same immutable dataset hash, completed-bar signals, next-bar fill convention, fee/slippage assumptions and matched benchmark intervals to each engine.
- Explain every mismatch; include open-position unrealized P&L, closed-trade P&L, fees, turnover, exposure, gap handling and conservative OHLC drawdown.
- Do not select a winner from a parameter sweep without untouched holdout, trial manifest, uncertainty and multiple-testing diagnostics.

### Phase 3 — reproducible research warehouse and reporting
- Export immutable candle/trade/decision records to DuckDB with dataset hashes, source/venue, UTC timestamps, code commit and run ID.
- Validate QuantStats metrics against WHJ's own calculations on the same periodic net-return series.
- Preserve the separation between realized P&L, unrealized P&L, fees, open positions and failed/rejected paper actions.

### Phase 4 — portfolio and dashboard enhancements
- Evaluate skfolio only when independent sleeves have adequate forward samples and robust covariance estimates; cap risk rather than increase it.
- Extend the current read-only dashboard using Lightweight Charts only where it adds clear value. Keep charts observational.
- Retain GitHub Actions as the primary scheduler until a local daemon has tested locking, recovery and single-instance guarantees.

## Required morning report

Every report should include:
- Starting equity and ending net-liquidation equity.
- Realized closed-trade P&L and unrealized open-position P&L separately.
- Fees and slippage separately where available.
- Open positions with entry, mark, stop/target, size and risk at stop.
- Submitted, filled, rejected, cancelled and unknown-status paper actions; never retry an unknown action blindly.
- Data quality, feed gaps, CVD availability/continuity, last completed candle and imputed observations.
- Strategy/version, dataset hash, run ID, benchmark comparison, sample size and explicit evidence status.

## Promotion gates

No candidate is promoted on a single attractive night, one venue, one timeframe, a single backtest, or a high terminal balance. Require chronological out-of-sample and untouched holdout evidence, independent venue replication, realistic spread/fees/slippage, sufficient closed forward-paper trades, drawdown and loss-streak review, uncertainty/selection-bias diagnostics, and a documented human review. Paper-only remains the operating mode.

## Current known blocker

The previously inspected forward monitor reported CVD as UNAVAILABLE because its expected Kraken trade journal/checkpoint was absent in the scheduled workflow. The existing requirement correctly fails closed. Phase 1 is therefore the first implementation target; no CVD bypass is permitted.
