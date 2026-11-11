# WHJ Adversarial Strategy and Simulator Audit

Date: 2026-11-12
Scope: research branch `research/global-evidence-strategy-lab-20261112`; read-only source review.
Status: findings and implementation contract. No production strategy, paper ledger, risk limit, schedule, or live-order path was changed.

## Executive decision

**No candidate is approved.** The current EMA/ADX and slow-momentum results are research observations only. The slow-momentum implementation is useful as a baseline, but its reported metrics are not yet strong enough to support a promotion decision. The next engineering priority is simulator validity and experimental governance, not adding more indicators.

## Findings from source inspection

### F1 — Daily slow-momentum simulation marks risk only at closes (high)

File: `slow_momentum_lab.py`, `_simulate`.

The simulator marks liquidation value using daily close only. This cannot measure intraday adverse excursion, gap-through-stop losses, or intraday drawdown. It is acceptable for a close-only signal prototype, but its maximum drawdown must be labelled close-to-close and must not be compared as if it were an intraday risk measure.

Required change:
- Keep close-to-close drawdown but name it explicitly.
- Add a separate OHLC execution/risk simulator before claiming realistic stop or intraday-risk behaviour.
- If stop and target are both touched in one bar and intrabar ordering is unknown, assume the adverse ordering or use lower-frequency data.

### F2 — Cost model is a fixed percentage (high)

The current simulator applies a constant fee and slippage per side. The 2x/3x sensitivity is useful but does not model spread, volatility, traded notional, market impact, latency, or liquidity variation.

Required change:
- Preserve fixed-cost scenarios for reproducibility.
- Add a conservative spread-plus-slippage model, with slippage increasing with volatility and order-notional / observed-volume ratio.
- Report every component separately and clearly label unavailable components as assumptions.
- Never infer realistic fills from candle close alone.

### F3 — OOS sub-windows are not rolling walk-forward retraining (high)

The slow-momentum evaluator partitions the final 30% into three chronological slices. It does not retrain or reselect parameters in successive training windows. Calling these windows "walk-forward" overstates what is tested.

Required change:
- Rename these outputs to `oos_subperiods` or equivalent.
- Implement a separate rolling walk-forward protocol: at each fold, use only prior data for model/parameter selection, freeze the choice, and evaluate the next untouched block.
- Record train/validation/test boundaries and all variants considered in each fold.

### F4 — Profit factor omits any open position at window end (medium/high)

The simulator marks an open position to estimated net liquidation value for final equity, but its closed-trade profit factor is calculated only from completed trades. A reader could misinterpret PF as describing the full window economics.

Required change:
- Keep closed-trade PF, explicitly named as such.
- Report open-position count, unrealized net liquidation P&L, realized P&L, and final net liquidation equity separately.
- Do not synthesize an artificial closed trade merely to inflate the trade count.

### F5 — The fixed 25% allocation is not a risk budget (high)

The slow-momentum candidate allocates 25% of current cash on entry. That is a capital-allocation rule, not a stop-distance or volatility-based risk budget.

Required change:
- Preserve 25% allocation as the original benchmark candidate.
- Add a separately named risk-sized ablation using lagged volatility / ATR and a predeclared per-trade risk budget.
- Apply a hard notional cap no greater than the incumbent limit; the new overlay may reduce exposure but may not raise existing risk limits.
- Include gap and fee stress; a stop does not guarantee a maximum loss.

### F6 — Cost-stress benchmark needs exact matched treatment (medium)

The implementation reruns candidate and benchmark with multiplied fee/slippage, which is directionally correct. Reports must additionally verify that benchmark and candidate use identical window boundaries, capital base, initial allocation, fill timing, and cost assumptions.

Required change:
- Add assertions for identical dates and cost parameters.
- Report benchmark-relative excess return in percentage points for each OOS subperiod and cost scenario.
- Do not treat a candidate as robust if it only beats the benchmark in aggregate but loses in most subperiods.

### F7 — Selection bias and multiple testing are not fully quantified (high)

The research plan correctly warns about backtest overfitting, but the report needs a machine-readable trial manifest. The three fixed lookbacks are not the only trials if other modules, thresholds, data sources, and variants have been explored.

Required change:
- Record every candidate, parameter set, data version/hash, source, commit SHA, and run ID.
- Report total trial count and discarded variants.
- Reserve a final chronological holdout once; do not inspect it repeatedly during iteration.
- Where sample size permits, estimate PBO/CSCV or use a predeclared multiple-testing adjustment. If infeasible, state why.

### F8 — Minimum sample gate is not enough by itself (medium)

Thirty closed trades can still provide very weak evidence, especially for low-frequency daily momentum. A candidate with fewer trades should not fail as a strategy; it should be marked insufficient evidence.

Required change:
- Keep the repository's existing 30-trade gate as a minimum screening rule.
- Require confidence intervals / bootstrap uncertainty and minimum calendar coverage.
- Do not promote a candidate merely because it barely crosses the minimum.
- For sparse strategies, extend the observation period rather than lowering the gate.

## Required report contract

Every candidate report must include:

1. Dataset identity, source, spot/derivatives classification, time range, timezone, row count, gap count, duplicate count, imputed count, and immutable data hash.
2. Code commit SHA, parameter manifest, trial count, and run identifier.
3. Signal timestamp and earliest executable timestamp; explicit handling of incomplete candles.
4. Net return, annualized return, closed-trade PF, Sharpe/Sortino with frequency, max close-to-close drawdown, OHLC drawdown where available, exposure, turnover, time-under-water, tail loss, and open-position liquidation value.
5. Results by chronological OOS subperiod, market regime, normal/2x/3x costs, and independent exchange source.
6. Matched buy-and-hold and flat-cash comparisons using the same windows, capital, allocation, and cost model.
7. Concentration tests: contribution of top 1 / 5 trades and results after removing them (diagnostic only, not a replacement performance estimate).
8. Bootstrap uncertainty and sensitivity to start/end dates and nearby predeclared parameters.
9. Explicit status: `INSUFFICIENT EVIDENCE`, `REJECTED`, or `ELIGIBLE FOR ISOLATED PAPER REVIEW`.

## Revised promotion gates

A candidate is eligible only if all conditions hold:
- At least 30 closed OOS trades, plus adequate calendar coverage and uncertainty reporting.
- Positive net OOS return under baseline and 2x cost stress; 3x stress must be reported and investigated, not hidden.
- Closed-trade profit factor >= 1.20.
- Maximum drawdown <= 10%, with the drawdown measurement type stated.
- All three predeclared OOS subperiods non-negative.
- Beats matched buy-and-hold after costs in aggregate and does not materially underperform it in most subperiods.
- No material dependence on the top few trades.
- No data-integrity, causality, or risk-control violations.
- Independent forward-only paper validation before any promotion discussion.

Passing these gates permits only an isolated paper review. It does not authorize live trading.

## Ordered implementation backlog

### P0 — Correctness and transparency
1. Rename close-only drawdown and OOS subperiod fields to avoid overclaiming.
2. Add explicit realized/unrealized/final-liquidation metrics.
3. Add benchmark alignment assertions and per-window excess return.
4. Add deterministic tests for open positions, costs, window boundaries, and future-data invariance.

### P1 — Realistic execution
5. Add OHLC-aware adverse-excursion / drawdown reporting.
6. Add spread, volatility, and participation-aware conservative slippage scenarios.
7. Add explicit next-bar fill rules and gap-through-stop tests.

### P2 — Research governance
8. Add immutable trial manifest and data hashes.
9. Add true rolling walk-forward selection/evaluation.
10. Add bootstrap uncertainty, trade concentration, and parameter/date sensitivity.

### P3 — Only after P0-P2
11. Compare EMA/ADX, slow momentum, breakout, pullback, and mean-reversion candidates using the same simulator.
12. Test regime gating as a separately named ablation against the ungated strategy.
13. Keep every candidate in isolated research until independently reviewed.

## Safety invariants

- Do not invoke the historical research entry point if it can mutate existing paper state.
- Do not read, reset, seed, or rewrite existing forward paper ledgers for this audit.
- Do not alter existing risk limits, schedules, or live-order pathways.
- No exchange credentials, live orders, or real funds.
- Any failed data-quality or risk-control check must fail closed and be reported, not silently repaired.
