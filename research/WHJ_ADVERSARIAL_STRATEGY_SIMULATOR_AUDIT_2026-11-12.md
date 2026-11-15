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

## 2026-11-13 follow-up re-audit

### F9 — OHLC drawdown omitted realized exits (high)

A focused re-read of `ohlc_execution_lab.py` found that `max_intrabar_ohlc_envelope_drawdown_pct` was updated only while a position remained open at the end of the candle. A stop-loss, stop-gap, or next-open signal exit closes the position before that mark, so the realized loss could be omitted from the intrabar drawdown field even while close-to-close drawdown reflected it.

**Research-branch fix:** `close_position()` now records post-exit cash against the preceding intrabar equity peak immediately after every realized exit. This preserves stop/gap execution assumptions and does not change allocation, stop distance, fees, slippage, signals, or any paper account.

Regression coverage:
- A 5% stop on a 25%-allocated position must report a 1.25% realized intrabar drawdown on a flat-price fixture.
- A loss on a next-open signal exit must also contribute to intrabar drawdown.

Commits: source fix `b8667fc95f5b880a8447775c18a52b157f99269c`; regression tests `f4b4fa3e67bf4fb984ee6f0c2877e7f15d226a86`.

Validation completed in Termux Repository Audit run 43518359895 on research head 004eb3836b4508f5f55e04e250b12bfdeec3a04f: 554 unit tests passed, tracked Python compilation passed, and whitespace checks passed. Both realized-stop and next-open-exit OHLC drawdown regressions passed. The patch remains research-only and does not read or write paper ledgers, change risk limits or schedules, or enable execution.

## Safety invariants

- Do not invoke the historical research entry point if it can mutate existing paper state.
- Do not read, reset, seed, or rewrite existing forward paper ledgers for this audit.
- Do not alter existing risk limits, schedules, or live-order pathways.
- No exchange credentials, live orders, or real funds.
- Any failed data-quality or risk-control check must fail closed and be reported, not silently repaired.


## 2026-11-14 follow-up — exact dataset replay

### F10 — a dataset hash without the normalized payload cannot reproduce a historical run (high)

The BTC 17-strategy, slow-momentum, and GC=F artifacts recorded source labels, row counts, and SHA-256 fingerprints, but did not include the exact normalized market-data rows. Public candle endpoints can revise or backfill history; a hash detects a change but cannot reconstruct the input that produced a report.

**Research-branch remediation:**
- Added `research_snapshot.py` with canonical JSON serialization (`sort_keys`, compact separators, non-finite values rejected), SHA-256 over the canonical uncompressed bytes, and deterministic gzip compression.
- The isolated 17-strategy BTC workflow now uploads `btc_hourly_dataset.json.gz`.
- The isolated slow-momentum workflow now uploads `btc_daily_dataset.json.gz`.
- The GC=F futures-reference workflow now uploads `gc_f_daily_dataset.json.gz`.
- Each report identifies its snapshot filename; the reported dataset hash is the hash of the decompressed canonical JSON bytes.
- Snapshots contain only public normalized market-data rows. They do not contain accounts, paper ledgers, credentials, or order data.

Commits: helper `ba2c38a6c4313d2a5bf357f4fbe59017230f0ef1`; tests `be224fd7b5caa28e452d1866599433b96920cd03`; BTC workflow `78b78d1a79f9d08273ab78d397c14d977de8cb97`; slow-momentum workflow `d8f9753b85c14cf32ac4fefccf4f0e688434a16e`; GC=F workflow `b920858d64778e6aa5d2971bef7e49e27a308086`.

Validation completed on 2026-11-13:
- Termux Repository Audit run 43518359895: 554 tests passed; tracked Python compilation and whitespace checks passed.
- BTC 17-strategy workflow run 43518310574 succeeded and uploaded artifact `whj-multi-strategy-research-32` with `btc_hourly_dataset.json.gz`; decompressed canonical-data SHA-256 matched the report exactly (36,000 rows).
- Slow-momentum workflow run 43518319267 succeeded and uploaded `btc_daily_dataset.json.gz`; SHA-256 matched exactly (1,499 rows).
- GC=F workflow run 43518326396 succeeded; its five gold test groups passed (11 + 4 + 4 + 9 + 3 = 31 tests), and `gc_f_daily_dataset.json.gz` matched the report hash (2,515 rows).
- The five focused snapshot tests passed locally and are included in the 554-test CI run.

The broker-specific XAUUSD path still requires a non-secret bid/ask export and broker session/cost specifications; the GC=F snapshot is not a substitute.

## 2026-11-14 follow-up re-audit — same-bar peak before stop exit

### F11 — OHLC drawdown could omit the current bar's high when a stop closed the position (high)

A further source-level review found that the simulator resolved an intrabar stop before marking the current candle's high. The realized-exit fix in F9 compared post-exit cash with the prior bar's peak, but a large same-bar high could still be omitted from the conservative OHLC envelope whenever the stop closed the position before the normal high/low mark.

**Research-branch fix:**
- For a position that survives opening-gap checks, mark the current bar's high as a possible equity peak before resolving intrabar stop/target touches.
- On a stop hit, use the actual stop fill (including configured adverse slippage and fee) as the liquidation trough; do not count a lower wick that may have occurred after the position was stopped out.
- On a target-only exit or a bar that remains open, retain the bar-low liquidation mark.
- Opening-gap exits and next-open signal exits remain processed at the open before the subsequent bar range; execution, allocation, stop/target levels, fees, slippage, and account state are unchanged.

Regression coverage:
- A flat-price stop fixture still reports the 1.25% realized loss for a 5% stop on 25% allocation.
- A same-bar high of 120 followed by a 5% stop fill at 95 records the $1,050 envelope peak and $987.50 stop liquidation, or 5.9524% peak-to-fill drawdown.
- The stop/target collision remains stop-first.

Commits: source 8e8829e1f78c1c71d59336d4adb88bb1daceacb3; regression test d0d00ff42435ba31d0e2d0e792688ae97818d72b; audit documentation commit recorded below.

Validation: source review and deterministic test were added on the research branch. CI for these new commits has not yet been observed; no pass is claimed here.

## 2026-11-15 follow-up — validation, CSCV coverage, and rolling-window instability

### F11 validation closure

The same-bar high-before-stop OHLC envelope correction and its regression fixtures are now covered by the latest repository audit:
- Latest audit run: [43629280670](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43629280670), commit `74d9a15c51571765b19c227506e1662b74a08007`.
- A later repository audit on the research follow-up commit [43649648829](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43649648829), commit `c110b7f330425c894f968eaca066efe88780f8b5`, passed **557 unit tests**, tracked Python compilation, and `git diff --check`.
- The F11 tests are included in that 557-test suite. The prior “CI pending” statement above is superseded by these successful runs.

### F12 — PBO was skipped only because the OOS length was not divisible by the partition count (medium)

The BTC 17-candidate OOS stream contained 10,799 aligned hourly returns, so the original strict CSCV helper skipped PBO for 8, 6, and 4 equal partitions. A reproducible helper was added to trim only the newest remainder and disclose the exact omission:
- Helper: `cscv_probability_of_backtest_overfitting_with_tail_trim()`.
- Eight equal contiguous partitions, 1,349 observations each.
- 10,792 of 10,799 OOS returns used; seven newest observations trimmed.
- 35 complementary CSCV splits across the 17 declared candidates.
- Selection metric inside each split: maximum in-sample Sharpe.
- Result: PBO diagnostic **0.085714**, median logit rank 1.757858.
- The diagnostic is limited to this 17-candidate set and this already-used OOS segment. It is not a future-profit probability, not a global experiment census, and not an untouched final holdout.

Implementation and tests: commit [c110b7f](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/c110b7f330425c894f968eaca066efe88780f8b5). The updated isolated BTC workflow completed successfully as run [43649648836](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43649648836), artifact `whj-multi-strategy-research-33`. The 36,000-row gzip snapshot was downloaded, decompressed, and its SHA-256 matched the report exactly: `110e96bd167f93c0bef58fe3385f71acab9d2da96142ff687f4b4a679a10ee9a`.

### F13 — expanding-window candidate selection is unstable to a one-day rolling data-window shift (high)

Two consecutive 36,000-hour Coinbase snapshots were compared. The newer 1,500-day window shifted forward by one day while the evaluator and walk-forward code remained unchanged:
- Run 32, snapshot `4d0c0345…`: fold 3 selected RSI14; its training excess score was -65.97% versus SMA200 -66.33% (gap about 0.36 percentage points). Fold-3 OOS return was -1.11% on four closed trades.
- Run 33, snapshot `110e96bd…`: fold 3 selected SMA200; its training excess score was -64.01% versus RSI14 -64.26% (gap about 0.25 percentage points). Fold-3 OOS return was -13.17% on 80 closed trades.
- The aggregate stitched walk-forward 1x result moved from -12.89% to -23.29%; 2x moved from -21.98% to -35.01%; 3x moved from -30.14% to -44.95%.

This is a sensitivity finding, not proof that one fold is correct. The near-tie in training selection led to a materially different OOS result after a one-day window shift. Do not tune the selection rule post hoc; preregister a stability/abstention rule and test it on a later untouched period.

### Latest isolated slow-momentum refresh

Run [43649648867](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43649648867), artifact `whj-isolated-slow-momentum-21`, succeeded on the same code commit. Its 1,499-row daily snapshot hash matched the report: `9b3f47270eef545e813e0e73837dad322ac88291b7f5cc4720e31b44fb2793ea`.
- 56-day: -2.95% OOS, 15 closed trades, PF 0.6253, close-to-close DD 8.40%, 95% block-bootstrap CI [-16.46%, +13.74%].
- Matched 25% buy-and-hold: -9.88%.
- 56-day stress: -4.03% at 2x and -5.09% at 3x.
- Three-variant CSCV/PBO: 0.50 over 10 splits and six partitions. This is only a small-universe diagnostic.
- No slow-momentum candidate is promoted; the 15-trade sample remains below the 30-trade screening gate.

### PR scope safety review — do not merge as currently composed

PR #122 also contains `.github/workflows/btc-10usd-paper.yml`, which schedules an hourly paper runner, restores/saves a persistent paper ledger, commits a portfolio snapshot, and deploys GitHub Pages. It also contains `.github/workflows/deploy-dashboard-pages.yml`, which deploys the research-branch dashboard on matching pushes or manual dispatch. Neither workflow was run or modified during this research session. Keep the PR unmerged until these paper-ledger, schedule, and deployment changes are explicitly separated and reviewed against the project's safety constraints.



### F14 — several BTC candidate names imply entry/exit systems that the signal library does not fully implement (high)

A source-level semantics review of `strategy_family_lab.py` found that the current 17-candidate report evaluates boolean long/flat signal states, not necessarily canonical textbook trading systems:
- `donchian_20_10_breakout` only checks whether the current close is above the prior 20-bar high; there is no separate 10-bar-low exit rule.
- `donchian_55_20_breakout` only checks the prior 55-bar high; there is no separate 20-bar-low exit rule.
- `stochastic_reversal` is a one-bar event (`previous_k < 20 <= k`), while the common evaluator interprets booleans as persistent position state. The resulting 683 closed trades and 1.58% exposure therefore describe a one-interval pulse rule, not a conventional stochastic system with an explicit exit.
- `volatility_squeeze_breakout` and `volume_confirmed_breakout` also place compression/volume confirmation inside the position-state condition, so a trade can exit when the entry filter ceases to hold even if a separate exit rule would not have fired.

No code was changed for this finding. The current ranking remains valid only for the exact implemented signal-state definitions and must not be presented as a definitive test of the canonical Donchian 20/10, Turtle 55/20, or full stochastic/volume/squeeze systems. Before the next final candidate evaluation, define explicit entry and exit streams (or rename these candidates as signal proxies), add state-transition tests, freeze the definitions, and rerun all 17 on a new untouched protocol. Do not retrofit exits to the existing OOS report and call the changed rules the same experiment.



### F15 — OHLC cannot distinguish an intrabar stop gap from a continuous stop touch (medium/high)

The default OHLC simulator fills a stop touched after the bar opens at the configured stop price. If the candle opens above the stop and later records a low below it, OHLC alone cannot establish whether price crossed the stop continuously or gapped through it. The existing default is therefore a stop-level fill assumption, not a verified conservative fill for every fast-market path.

**Research-only remediation:**
- Preserve the existing `stop_price` default so earlier baseline results remain comparable.
- Add an explicit `bar_low_worst_case` sensitivity policy that fills an intrabar stop at that candle's low, then applies the same adverse slippage and fee.
- Label the low fill as a pessimistic OHLC bound, not as an expected or guaranteed executable price.
- Keep opening-gap fills at the opening price and retain stop-first ordering when both stop and target are touched.

Regression coverage compares a 5% stop on a 25%-allocated position: the default stop-level fill produces $987.50 final equity, while the candle-low stress at $90 produces $975.00. A separate test rejects unknown policy names.

This changes only the isolated research simulator's optional fill assumption. The default execution model, 25% allocation cap, configured paper risk limits, paper ledgers, schedules, and all order pathways remain unchanged. No strategy is evaluated or promoted by this patch.
