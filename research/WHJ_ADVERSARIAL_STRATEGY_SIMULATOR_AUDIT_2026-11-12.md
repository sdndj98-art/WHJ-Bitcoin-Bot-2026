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

### F15 validation closure — 2026-11-16

The optional intrabar stop-gap sensitivity policy and its fee/slippage accounting now have regression coverage on the research branch:

- Test commit: `594a241d26855027fb35f1f2a53e8cfd1f52fc3f`.
- Fixture: a 25%-allocated long enters at 100; the `bar_low_worst_case` policy references the candle low of 90; 0.20% adverse slippage produces a fill of 89.82; 0.10% fee per side produces final net-liquidation equity of $973.6538 (return -2.6346%).
- Repository audit: [run 43771208255](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43771208255) completed successfully on that commit: **560 unit tests passed in 4.455 seconds**, tracked Python compilation passed, and `git diff --check` passed.
- This validates deterministic accounting for the explicit OHLC stress policy only. It does not validate expected broker fills, tick-level paths, or any strategy's market performance.

The latest BTC and slow-momentum historical artifacts remain tied to code commit `c110b7f330425c894f968eaca066efe88780f8b5`. The three commits after that evaluation changed only `ohlc_execution_lab.py`, its tests, and this audit; the BTC strategy signal/evaluator and slow-momentum strategy/evaluator files were unchanged. The historical results therefore remain reproducible for their recorded source commit, but are not a new evaluation on the current branch head.


### F16 — OHLC simulator accepted booleans as numeric execution parameters (low/medium)

Python treats booleans as integers. The OHLC simulator's range checks therefore accepted fee=False and slippage=False as zero-cost settings, and accepted take_profit_pct=True as a 100% target. Non-numeric values could also raise a raw TypeError instead of the simulator's documented validation error.

**Research-only remediation:**
- Validate fee, slippage, allocation, stop percentage, and target percentage as finite numeric values before applying their existing bounds.
- Reject booleans explicitly, even though bool subclasses int.
- Preserve the existing fee/slippage defaults, 25% allocation cap, stop/target defaults, and execution behavior for valid numeric inputs.
- Add regression coverage for boolean, string, NaN, and infinite parameter values.

This is input-contract hardening only. It does not change configured paper risk limits, account balances, ledgers, schedules, trading pathways, or strategy behavior.


### F16 validation closure — 2026-11-16

The numeric-parameter contract hardening is covered by the repository-wide audit on the subsequent research head:

- Source fix: [commit 2ad50d0](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/2ad50d0e6c99bbdb8455a2af75b8e7f7ac51508b).
- Regression tests: [commit b3f8afe](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/b3f8afedd9b85c28a007e4d3cc0b7451210c61a7).
- Latest full repository audit including those tests: [run 43967507318](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43967507318), research head `3874d78df39299effd49e626f31cd3f6bc94144d).
- Result: **565 unit tests passed in 6.918 seconds**; tracked Python compilation and `git diff --check` passed.
- The new tests reject booleans, strings, NaN and infinity for fee, slippage, allocation, stop and target parameters. Valid numeric execution behavior and the 25% research cap remain unchanged.

This closes the input-validation finding only. It does not validate market fills, the OHLC path model, or any strategy's profitability.


### F17 independent 17-candidate Bitstamp replication — 2026-11-16

A new research-only workflow evaluates the same 17 predeclared boolean long/flat signal-state proxies on a separate Bitstamp BTCUSD hourly history. It does not alter any candidate rules and does not access paper state.

- Evaluator: `bitstamp_strategy_family_research.py`; workflow: [WHJ Bitstamp 17-Candidate Independent Research](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43967507369).
- Code commit: [3874d78](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/3874d78df39299effd49e626f31cd3f6bc94144d).
- Artifact: [whj-bitstamp-17-strategy-research-3, ID 14276064048](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43967507369/artifacts/14276064048).
- Workflow result: **success**. Four new report/regime tests passed; all shared strategy/evaluator/rolling/PBO/snapshot/Bitstamp-loader test suites passed; isolated modules compiled; all 17-candidate evaluation and artifact upload succeeded.
- Dataset: 72,000 hourly bars, 2018-08-30T22:00Z through 2026-11-16T21:00Z; gap-free, zero imputed bars, zero duplicate timestamps.
- Canonical dataset SHA-256: `b0113cfd54fe0aa29da724c534a2f6deb241a0ee123aa3efe7a0b59426361fb2`. The downloaded gzip snapshot was decompressed and its canonical bytes re-hashed; it matched the report. The downloaded artifact ZIP digest also matched GitHub's `d4ffea7d4885724d78e98a8b7a05e34085d25d88532078b5f327c18f9dbd2562`.
- Chronological 70/30 split: 50,400 training candles; 21,600 OOS candles and 21,599 OOS open-to-open returns (2024-05-30T22:00Z through 2026-11-16T21:00Z).
- Fixed costs: 0.10% fee + 0.05% slippage per side at 1x; both multiplied by 2x/3x. These match the Coinbase research assumptions to isolate price-series sensitivity; they are **not** Bitstamp account-specific fees, quoted spread, measured slippage or market impact.

#### Bitstamp OOS ranking at 1x

| Rank | Candidate | Net return | Max DD | Period PF | Sharpe | Closed trades | 2x | 3x |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | RSI14 | -3.38% | 3.43% | 0.452 | -1.895 | 37 | -6.03% | -8.60% |
| 2 | Bollinger | -16.84% | 16.88% | 0.370 | -4.418 | 209 | -28.91% | -39.23% |
| 3 | SMA200 | -22.31% | 27.89% | 0.941 | -1.329 | 381 | -41.63% | -56.15% |
| 4 | Z-Score20 | -23.23% | 23.30% | 0.492 | -4.891 | 358 | -41.32% | -55.15% |
| 5 | ROC60 | -25.84% | 32.27% | 0.915 | -1.771 | 481 | -48.31% | -63.97% |
| 6 | ROC120 | -27.10% | 31.77% | 0.918 | -1.767 | 437 | -47.48% | -62.17% |
| 7 | Donchian55/20 | -27.86% | 28.09% | 0.422 | -5.239 | 428 | -47.68% | -62.06% |
| 8 | Volatility Squeeze | -28.44% | 28.44% | 0.350 | -6.312 | 426 | -48.02% | -62.24% |
| 9 | Volume Breakout | -30.71% | 30.93% | 0.457 | -5.098 | 524 | -53.24% | -68.45% |
| 10 | RSI2 | -31.53% | 31.55% | 0.406 | -6.449 | 512 | -53.37% | -68.25% |
| 11 | ATR Channel | -39.44% | 39.58% | 0.425 | -6.447 | 684 | -63.75% | -78.31% |
| 12 | SMA20/50 | -40.50% | 41.88% | 0.825 | -3.476 | 744 | -65.95% | -80.52% |
| 13 | ROC20 | -41.93% | 42.82% | 0.828 | -3.520 | 765 | -67.29% | -81.58% |
| 14 | EMA12/26 | -43.20% | 43.21% | 0.857 | -3.224 | 817 | -69.23% | -83.34% |
| 15 | Donchian20/10 | -44.18% | 44.31% | 0.418 | -7.087 | 769 | -68.66% | -82.40% |
| 16 | OBV | -55.40% | 55.40% | 0.788 | -4.751 | 1,105 | -80.54% | -91.51% |
| 17 | Stochastic | -65.40% | 65.40% | 0.280 | -12.168 | 1,446 | -88.31% | -96.05% |

Matched 25% buy-and-hold returned **+3.56%** at 1x. Every one of the 17 candidates lost money at 1x, 2x and 3x; every candidate also underperformed the matched benchmark at 1x. The best candidate's conditional 24-hour block-bootstrap 95% interval was -5.96% to -1.24% (1,000 resamples); all top-five conditional intervals were below zero, but these intervals are not multiple-testing adjusted.

#### Independent expanding-window walk-forward

- Initial training: 39,600 bars; four contiguous test folds of 7,200 bars each; total 28,800 OOS returns; 3,599 newest bars unused.
- SMA200 was selected in all four folds using training-only excess return.
- Aggregate 1x: strategy **-16.79%**, matched buy-and-hold **+39.09%**, max open-to-open DD **26.58%**, periodic PF **0.971**, Sharpe **-0.640**, 501 closed trades, 13.05% exposure.
- 2x: **-42.87%**; 3x: **-60.78%**.
- Fold 1/2/3/4 strategy returns: -1.13%, +5.04%, -7.62%, -13.34%; matched benchmarks: +20.17%, +14.03%, +16.09%, -12.67%.

#### CSCV/PBO and regime diagnostics

- CSCV/PBO = **0.000000**, 8 contiguous partitions, 35 splits, 2,699 observations per partition, 21,592/21,599 observations used; 7 newest observations trimmed. This means the in-sample selected candidate did not fall below the median relative OOS rank in these splits. It does **not** mean the candidates are profitable or free of overfitting; every candidate's net OOS return is negative.
- OOS regime bars: bearish 8,401; bullish 8,500; sideways/transition 4,698. Regime values are log-return attribution by the regime known at the prior close, not separate regime portfolios.
- SMA200 attributed return: +10.28% in bullish bars, -24.64% in sideways/transition bars, -6.53% in bearish bars; total -22.31%. This illustrates substantial regime dependence despite its repeated training selection.

#### Cross-exchange interpretation

The Coinbase 70/30 run ranked RSI14 at -1.36% versus a -11.14% matched benchmark; the Bitstamp run ranked the same proxy at -3.38% versus a +3.56% benchmark. These OOS windows are not the same calendar interval, so this is not a strict same-date venue spread comparison. It nevertheless shows that relative ranking is highly sample/regime dependent; the absolute RSI14 return was negative on both datasets.

**F17 is closed as an evaluation-pipeline milestone, not as a strategy approval. F14 remains open:** Donchian and Stochastic (and other state proxies) still require explicit, frozen entry/exit semantics before the 17 candidates can be described as canonical trading systems. The cross-exchange run is historical research, not forward paper trading. No candidate is promoted.


### F18 exact same-calendar Coinbase–Bitstamp comparison — 2026-11-16

The full-history Bitstamp 70/30 split above begins earlier than the Coinbase OOS window. To remove that date-window confound, the evaluator now also freezes an exact same-calendar comparison against Coinbase multi-strategy run #33.

- Code: [commit f749a0e](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/f749a0e820a343fceb0fee1e7464c9618cadeef4).
- Workflow: [WHJ Bitstamp 17-Candidate Independent Research, run 43968648454](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43968648454).
- Artifact: [whj-bitstamp-17-strategy-research-6, ID 14276514574](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43968648454/artifacts/14276514574).
- Reference: Coinbase run [43649648836](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43649648836), code `c110b7f`, dataset SHA `110e96bd167f93c0bef58fe3385f71acab9d2da96142ff687f4b4a679a10ee9a`.
- Exact OOS open window: **2025-08-21T22:00:00Z through 2026-11-14T21:00:00Z**; 10,799 open-to-open returns, 10,801 Bitstamp rows including the prior completed signal candle and final endpoint.
- Bitstamp matched-slice SHA-256: `2d695ceb526a69a9816b85ed1f2d7dbe5bd13072eaf2062ab8bdf97a1784e9f6`. The slice was recomputed from the downloaded 72,000-row snapshot and matched. Full Bitstamp dataset SHA remains `b0113cfd54fe0aa29da724c534a2f6deb241a0ee123aa3efe7a0b59426361fb2`; the downloaded ZIP digest also matched GitHub's artifact digest.
- The report explicitly truncates Bitstamp data at the reference endpoint; a regression test changes every later OHLCV row and verifies the matched results and slice hash remain identical. This guards against future-row leakage in the matched comparison.
- Cost assumptions are identical to Coinbase (0.10% fee + 0.05% slippage per side at 1x; 2x/3x stress) to isolate the price series. They remain fixed proxies, not Bitstamp's account-specific fee schedule, spread, or market impact.

#### Same-date 1x comparison

| Rank | Candidate | Coinbase | Bitstamp | Bitstamp DD | Period PF | Sharpe | Trades | Bitstamp 2x | Bitstamp 3x |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | RSI14 | -1.3633% | -1.3451% | 1.39% | 0.355 | -1.873 | 11 | -2.16% | -2.96% |
| 2 | Bollinger | -8.5147% | -8.5148% | 8.51% | 0.281 | -4.632 | 84 | -14.10% | -19.35% |
| 3 | Z-Score20 | -10.6427% | -11.1827% | 11.18% | 0.437 | -4.910 | 146 | -20.40% | -28.66% |
| 4 | Donchian55/20 | -12.3917% | -12.3974% | 12.74% | 0.436 | -4.909 | 194 | -24.27% | -34.53% |
| 5 | Volatility Squeeze | -12.6200% | -13.4058% | 13.41% | 0.358 | -6.644 | 203 | -25.64% | -36.15% |
| 6 | Volume Breakout | -12.1569% | -14.2490% | 14.59% | 0.505 | -4.409 | 254 | -29.13% | -41.43% |
| 7 | SMA200 | -14.4767% | -14.7792% | 17.14% | 0.909 | -2.002 | 182 | -25.66% | -35.15% |
| 8 | ROC60 | -15.7099% | -16.0788% | 16.69% | 0.881 | -2.422 | 231 | -29.44% | -40.67% |
| 9 | ROC120 | -16.4685% | -16.2513% | 18.69% | 0.885 | -2.379 | 198 | -27.81% | -37.78% |
| 10 | RSI2 | -16.7561% | -17.1736% | 17.17% | 0.343 | -7.178 | 229 | -30.25% | -41.27% |
| 11 | ATR Channel | -18.1666% | -18.2922% | 18.59% | 0.480 | -5.385 | 322 | -35.83% | -49.61% |
| 12 | Donchian20/10 | -19.7443% | -19.9192% | 20.21% | 0.486 | -5.677 | 354 | -38.60% | -52.93% |
| 13 | ROC20 | -20.1493% | -19.9646% | 20.71% | 0.828 | -3.307 | 335 | -37.76% | -51.60% |
| 14 | SMA20/50 | -25.0615% | -24.9688% | 26.72% | 0.788 | -4.272 | 370 | -43.16% | -56.94% |
| 15 | EMA12/26 | -26.4535% | -26.7095% | 26.88% | 0.824 | -3.994 | 375 | -44.69% | -58.26% |
| 16 | OBV | -35.3842% | -33.0747% | 33.23% | 0.762 | -5.324 | 533 | -55.14% | -69.93% |
| 17 | Stochastic | -39.4443% | -40.5080% | 40.51% | 0.273 | -12.154 | 710 | -65.08% | -79.51% |

The matched 25% buy-and-hold benchmark was **-11.14%** on both feeds. All 17 candidates lost money at 1x, 2x and 3x. RSI14 and Bollinger beat the benchmark only in relative terms; both still lost capital, had negative Sharpe and PF below 1.

Across the 17 candidate net returns on this exact calendar window:
- Spearman rank correlation: **0.992647**.
- Pearson return correlation: **0.996070**.
- Mean absolute cross-feed return difference: **0.5268 percentage points**; maximum absolute difference: **2.3095 pp** (OBV).
- Candidate order differs only among ranks 4–6; the other 14 ranks match.
- CSCV/PBO: **0.085714** on both feeds (8 partitions, 35 splits, 1,349 observations per partition, 10,792/10,799 used; 7 trailing observations trimmed). This is a relative selection diagnostic, not a profitability probability.
- Conditional 24-hour block-bootstrap 95% intervals for the Bitstamp top five were all below zero; RSI14's interval was -3.1265% to -0.0540%. These intervals are not adjusted for selecting the top five on the same OOS sample.

**F18 closes the same-calendar cross-exchange comparison milestone. It does not close F14 or approve a strategy.** The very high rank/return correlations confirm that the poor results are not just a Coinbase-specific price-feed artifact for this window. The candidates remain the same long/flat signal-state proxies; their entry/exit semantics still require frozen canonical definitions. No forward-paper result or live profitability is claimed.


### F19 — slow-momentum cost-input validation

A source review found that the isolated slow-momentum evaluator reused Python's numeric comparisons without rejecting boolean and non-finite inputs first. In particular, `fee=False` and `slippage=False` were accepted as zero-cost assumptions; NaN could pass the range comparisons, and non-numeric strings could raise a raw `TypeError`. The periodic-return helper had the same cost-input weakness, and the public cost-stress helper did not reject non-finite multipliers.

**Research-only remediation:**
- Require fee and slippage to be finite non-boolean numeric fractions in `[0, 1)` in the evaluator, periodic-return helper, and direct cost-stress helper.
- Require periodic allocation to be a finite non-boolean numeric value in `(0, 0.25]`; the incumbent research cap is unchanged.
- Require the cost multiplier to be finite, non-boolean, numeric, and at least 1.
- Add regression cases for booleans, strings, NaN, positive/negative infinity, and sub-unit multipliers.

This is input-contract hardening only. It does not alter signal definitions, execution timing, normal cost assumptions, allocation, strategy results, paper ledgers, schedules, or trading pathways. The existing isolated slow-momentum workflow path filters include both the source and its test file. The push triggered the dedicated public-data workflow on 2026-11-17; its completed run and artifact are recorded in the validation closure below.


### F19 validation closure — 2026-11-17

- Research fix: [commit 63a82b8](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/63a82b8bf9768ba85bca14c2b00eb08e8567daf4).
- Full repository validation: [Termux Repository Audit run 44151979255](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44151979255), exact head `63a82b8bf9768ba85bca14c2b00eb08e8567daf4).
- Result: **571 tests passed in 7.751 seconds**; the three new F19 regression methods are present in the log and pass. Tracked Python compilation and `git diff --check` also passed.
- Dedicated slow-momentum workflow: [run 44151979400](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44151979400), conclusion `success`, exact same code head.
- Artifact: `whj-isolated-slow-momentum-22`, ID `14359971027`; ZIP digest `3d640f573cab6412447b9d8e2885ac9450018bc8fe5d37aac710fe07055deab3`.
- The artifact's decompressed daily dataset hash was independently recomputed and matched the JSON report and trial manifests: `5feba5d5f2f97eaec192ae058b2a689d09556717a7dabc686e1715a470f765db`.
- The artifact explicitly reports research-only execution disabled, no live orders, and no paper ledgers read or written.

This closes F19's input-validation and CI-verification task. It does not close the OHLC fill-realism findings, establish realistic spread/depth/market impact, create a rolling or untouched holdout, or validate profitability. The new historical results remain negative in absolute terms and no candidate is promoted.


### F20 — chronological timestamp integrity in the 17-signal input contract

A source review found that strategy_family_lab._rows() trusted the caller's row order and ignored timestamps on mapping-shaped candles. Duplicate or out-of-order rows could therefore be accepted by the standalone 17-candidate signal builder, even though the downstream Bitstamp data loader independently enforces hourly continuity.

**Research-only remediation:**
- When timestamps are supplied, require finite numeric, non-boolean values.
- Require timestamps to be present on every row or omitted on every mapping row; reject mixed timestamp coverage.
- Require strictly increasing timestamps, rejecting duplicates and out-of-order bars before indicators are calculated.
- Do not impose a universal gap-free interval in the signal library: timeframe/session-specific gap policy remains the responsibility of each source loader.

**Regression coverage:** four tests cover duplicate and out-of-order sequences, boolean/string/NaN/infinite timestamps, mixed mapping timestamp presence, valid mapping timestamps, and the documented all-omitted mapping case.

**Commits and validation:**
- Source guard and initial tests: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/53c27dbbf28aef950aa4a4a6e72d45375f5c7b40.
- Test-fixture correction (the first fixture removed a required positional timestamp instead of creating a mixed mapping): https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/4808ab87dd5919f5aa63b47e761a74986341225e.
- First validation on 53c27db correctly exposed that test-fixture mistake: 575 tests ran with one assertion failure; the source guard itself and all other tests passed.
- Corrected full repository audit on 4808ab8: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44189928767, **575 tests passed in 6.104 seconds**; compile-all-tracked-Python and git diff --check steps succeeded.
- Independent Bitstamp research workflow on the corrected head: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44189928739; shared strategy/evaluator tests and module compilation passed before the historical evaluation step. Final run conclusion is tracked separately.

This guard prevents silent chronological reordering at the signal-library boundary; it does not validate exchange session calendars, detect missing intervals by itself, change any signal or exit rule, or establish performance. No historical result is re-labelled and no candidate is promoted.


### Verified 17-candidate refresh — 2026-11-17

#### Coinbase run 35

- Workflow: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44189928803
- Artifact: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44189928803/artifacts/14375693324
- Artifact ZIP SHA-256: 775f5e30b1c9f14c2a46f2aacfa23367ca7b15a36f1a45a02d5a5a294d4c8cc2
- Dataset SHA-256 (recomputed from decompressed immutable snapshot): 2c3b21e004f0460b0f2647d995f5204d088811f700c94e95bbec67c31f0cb57e
- Code commit: 4808ab87dd5919f5aa63b47e761a74986341225e; run ID 44189928803.
- 36,000 hourly Coinbase BTC-USD candles; 2022-10-09T22:00Z through 2026-11-17T21:00Z; 25,200 training candles and 10,800 OOS candles (10,799 open-to-open returns); 13 hourly observations explicitly marked imputed.
- All 17 candidates remain negative at 1x, 2x, and 3x. At 1x the descriptive ranking starts RSI14 -1.3633%, Bollinger -8.5147%, Z-Score20 -10.6427%, Volume Breakout -12.1543%, Donchian55/20 -12.3891%; it ends OBV -35.4078%, Stochastic -39.7727%. The matched 25% buy-and-hold return was -11.4733%.
- RSI14: max open-to-open DD 1.4107%, periodic PF 0.3497, annualized hourly Sharpe -1.8879, 11 closed trades, 0.058% exposure. Its 1x/2x/3x returns were -1.3633%/-2.1741%/-2.9786%; low exposure and only 11 trades make relative outperformance weak evidence.
- CSCV/PBO 0.085714 across 17 fixed signal-state candidates, 8 contiguous partitions, 35 splits; 10,792/10,799 observations used and 7 newest observations trimmed. This remains a narrow diagnostic, not a future-profit probability or final holdout.
- The top-five conditional moving-block bootstrap 95% intervals all remained below zero: RSI14 [-3.1427%, -0.0027%], Bollinger [-12.1768%, -5.2190%], Z-Score20 [-14.5668%, -6.9280%], Volume Breakout [-16.9754%, -7.0383%], Donchian55/20 [-16.1004%, -8.6152%].
- Expanding-window walk-forward: four contiguous 3,600-return folds, 14,400 OOS returns, 223 closed trades. Adaptive portfolio -22.8438% at 1x, -34.7329% at 2x, -44.7935% at 3x; matched benchmark -0.7516%/-0.7888%/-0.8260%; 1x max DD 25.3867%, Sharpe -2.4771. Folds selected SMA200 three times and RSI14 once. This is a separate adaptive process, not a fixed-candidate backtest.

#### Independent Bitstamp run 8

- Workflow: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44189928739
- Artifact: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44189928739/artifacts/14375209983
- Artifact ZIP SHA-256: 6855f7c1a5fd2413a5649c2dfcfcb4cb28485d40a361e0fe1c54464f15a5dbff
- Dataset SHA-256 (recomputed from decompressed immutable snapshot): 38f9785f46f041ab4103beef984b0850971c35fa67601581f978088470818626
- Code commit: 4808ab87dd5919f5aa63b47e761a74986341225e; run ID 44189928739.
- 72,000 hourly Bitstamp BTCUSD candles; 2018-08-31T22:00Z through 2026-11-17T21:00Z; 50,400 training candles and 21,600 OOS candles (21,599 open-to-open returns); zero duplicate timestamps, zero hourly gaps, zero imputed candles.
- Full-history 70/30 OOS matched buy-and-hold returned +3.4502%, while all 17 strategy candidates were negative. Ranking starts RSI14 -3.3822% (DD 3.4275%, PF 0.4518, Sharpe -1.8949, 37 trades), Bollinger -16.8386%, SMA200 -22.0246%, Z-Score20 -23.2287%, ROC60 -25.5616%; it ends OBV -55.5558% and Stochastic -65.4366%.
- RSI14 cost stress: -3.3822%/-6.0280%/-8.6022% at 1x/2x/3x. All 17 candidates remain negative under every cost multiplier.
- Important cost caveat: the fixed 0.10% fee and 0.05% slippage per side deliberately match Coinbase to isolate price-series sensitivity. They are not Bitstamp account-specific fees, measured spread, order-book depth, impact, latency, or realized slippage.
- Full-history CSCV/PBO was 0.0 across 17 candidates, 8 partitions and 35 splits (21,592/21,599 returns used; 7 newest observations trimmed). This is only a ranking-selection diagnostic on this fixed universe and sample.
- Expanding-window walk-forward selected SMA200 in all four folds: adaptive portfolio -16.794% at 1x, -42.868% at 2x, -60.777% at 3x, versus matched benchmark +39.677%/+39.625%/+39.572%; 1x max DD 26.584%, Sharpe -0.640, 501 closed trades over 28,800 OOS returns. The four folds are stitched OOS, with a 3,600-bar unused tail.

#### Exact-date cross-exchange refresh

The Bitstamp run 8 matched-calendar section still referenced Coinbase run 33 (ending 2026-11-14), not the newer Coinbase run 35. The reference was therefore updated, without changing candidate rules or cost assumptions, to pin Coinbase run 35:
- run 44189928803, commit 4808ab87dd5919f5aa63b47e761a74986341225e;
- dataset SHA-256 2c3b21e004f0460b0f2647d995f5204d088811f700c94e95bbec67c31f0cb57e;
- OOS first open 2025-08-24T22:00:00Z, last candle 2026-11-17T21:00:00Z, 10,799 open-to-open returns.
- Reference update and pinning regression test: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/commit/97ffc720584362cc6c52603862effbbb435e020a.
- The resulting Bitstamp run 9 was still executing at this report revision; do not treat its same-calendar result as completed until its artifact is uploaded and checked.

**Current promotion decision remains NO CANDIDATE PROMOTED.** Historical OOS and walk-forward results are not forward paper trading. No candidate has sufficient evidence for production use.


### F21 — latest exact-calendar Coinbase/Bitstamp replication closed — 2026-11-17

The updated reference to Coinbase run 35 completed successfully on Bitstamp run 9. This is now the exact same OOS calendar window on both exchanges, not the older run-33 reference.

- Bitstamp workflow: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44190499641.
- Artifact: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44190499641/artifacts/14377350619.
- Artifact ZIP SHA-256: 2aeace368b2a1e9fab5149691bf74c71896e328e68a29fc9414759a062773bcd.
- Artifact dataset SHA-256: 38f9785f46f041ab4103beef984b0850971c35fa67601581f978088470818626 (recomputed from decompressed snapshot; matches report).
- Bitstamp dataset: 72,000 hourly candles, 2018-08-31T22:00Z through 2026-11-17T21:00Z; 0 duplicate timestamps, 0 hourly gaps, 0 imputed candles.
- Coinbase reference: run 44189928803, commit 4808ab87dd5919f5aa63b47e761a74986341225e, dataset SHA-256 2c3b21e004f0460b0f2647d995f5204d088811f700c94e95bbec67c31f0cb57e.
- Exact shared OOS window: 2025-08-24T22:00Z through 2026-11-17T21:00Z; 10,799 open-to-open returns. The matched Bitstamp slice contains 10,801 candles including the prior signal bar and endpoint; slice SHA-256 6f2a6aa261a12626a7ac948fdad202cf61d41c50059a8b91fb1a64ff46f0cd5a.
- Matched buy-and-hold: Coinbase -11.4733%; Bitstamp -11.4888%.
- Across the 17 candidates' cumulative net returns on this same calendar, Spearman rank correlation = **0.985294**, Pearson correlation = **0.997105**, mean absolute return difference = **0.4672 percentage points**, maximum absolute difference = **2.0931 percentage points**; 13 of 17 ordinal positions are identical.
- The matched ranking still has every candidate negative at 1x/2x/3x. Best five Bitstamp 1x: RSI14 -1.3451%, Bollinger -8.5148%, Z-Score20 -11.1827%, Donchian55/20 -12.3958%, Volatility Squeeze -13.4058%. Worst: Stochastic -40.8298%.
- Matched-window CSCV/PBO = 0.114286 across 17 fixed candidates, 8 contiguous partitions and 35 splits; 10,792/10,799 returns used, 7 newest observations trimmed. This remains a narrow selection diagnostic only.
- Full Bitstamp-history 70/30 results and walk-forward remain as recorded in the run-8 section above; the run-9 change only refreshes the exact Coinbase reference window and matched-calendar diagnostics.

**Execution/test evidence:** Bitstamp run 9 completed successfully. It ran 57 tests across the isolated report and shared contracts, compiled the research modules, evaluated all 17 candidates, and uploaded the artifact. Full repository audit run 1676 on commit 32e0b9c passed **576 tests in 7.130 seconds**, with tracked Python compilation and git diff --check successful: https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44190910372.

This closes the exact-calendar cross-exchange replication task for the current fixed signal-state definitions. It does not close F14 (entry/exit semantics), actual venue-specific spread/fees/impact, an untouched final holdout, or forward paper validation. It is evidence that the negative candidate ranking is not a Coinbase-only artifact; it is not evidence that any candidate is profitable.


### F22 — machine-readable candidate semantics are now carried by the batch runner — 2026-11-18

F14 correctly identified that several candidate names could be mistaken for canonical trading systems. The signal library and common batch runner previously exposed the limitation in prose/audit documentation, but the runner's machine-readable result did not carry the per-proxy caveats.

**Research-only remediation:**
- `strategy_universe()` now publishes an explicit `signal_semantics` object identifying the common boolean long/flat state interpretation and the known Donchian, stochastic, volume-confirmation, and volatility-squeeze limitations.
- `run_strategy_universe()` carries this object into its returned report metadata.
- Regression tests assert the semantics are present and accurately describe the missing exit rules and one-bar stochastic event.
- No signal calculation, evaluator behavior, historical candidate ID, cost assumption, allocation cap, or paper/live pathway was changed.

This is a reporting-contract correction, not a canonical strategy implementation. Existing historical artifacts remain unchanged and retain their original proxy semantics. A new historical evaluation is not needed solely for this metadata addition; the full repository CI must still validate the code and tests. No candidate is promoted.

### F23 — exact-calendar cross-exchange reference refreshed to Coinbase run 40 — 2026-11-19

The previous Bitstamp run 13/14 artifacts still carried the Coinbase run-35 calendar reference. Coinbase run 40 had a newer immutable 36,000-bar snapshot, so those earlier matched-window summaries must not be described as the latest exact-calendar replication. The pinned reference was refreshed to run 40 and independently re-evaluated on Bitstamp run 17. No candidate rule or cost assumption changed.

**Pinned Coinbase reference**
- Workflow: [Coinbase multi-strategy run 40](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44414511120).
- Code commit: `f71f2427ffbb211d9b44aae2f2bd657bff4c88c8`.
- Dataset SHA-256: `3b1d145f79f21e8e2a84d94e6d1f64b5845fc3c5557cc7d93a806f9cca043804` (recomputed from decompressed canonical JSON and matched the report).
- 36,000 BTC-USD hourly candles; 25,200 train candles; 10,800 OOS candles / 10,799 open-to-open returns; 13 explicitly marked imputed hourly observations.
- OOS first open: 2025-08-25T22:00:00Z; last candle: 2026-11-18T21:00:00Z.
- The 17 fixed signal-state proxies were negative at 1x, 2x, and 3x costs. The best-ranked RSI14 proxy returned -1.3633% at 1x (DD 1.4107%, periodic PF 0.3497, Sharpe -1.8879, 11 closed trades). The matched 25% buy-and-hold benchmark returned -11.3461%.

**Independent Bitstamp refresh**
- Workflow: [Bitstamp 17-candidate run 17](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44415730207).
- Artifact: [whj-bitstamp-17-strategy-research-17](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44415730207/artifacts/14479033160).
- Artifact ZIP SHA-256: `2365639fdafadee4f9de00dcffa358bc89d8a3e4df85203e7a0b85864152babb`.
- Code commit: `631e35ea22ef1a9f15086cc8dd4dd9115dd0383a`.
- 72,000 BTCUSD hourly candles; 50,400 train candles; 21,600 OOS candles / 21,599 open-to-open returns; 0 duplicate timestamps, 0 gaps, 0 imputed candles.
- Dataset SHA-256: `5e9d2343b3ba8484aa1430b5d3055965259ac4298d4a49e0ab2cf380004c054a` (recomputed from decompressed canonical JSON and matched the report).
- Full-history 70/30 OOS benchmark: +2.83%; all 17 candidates negative at 1x/2x/3x. Best RSI14: -3.3822% (DD 3.4275%, PF 0.4518, Sharpe -1.8949, 37 trades).
- Full-history CSCV/PBO: 0.0 across 17 fixed candidates, 35 splits, 8 partitions; 21,592/21,599 returns used and 7 newest observations trimmed. This remains a narrow ranking diagnostic, not a future-profit probability.

**Exact shared calendar — 10,799 returns on both venues**
- Coinbase reference: run 44414511120; Bitstamp run 44415730207.
- Shared window: 2025-08-25T22:00:00Z through 2026-11-18T21:00:00Z.
- Bitstamp matched slice: 10,801 candles including prior signal bar and endpoint; SHA-256 `1130c7411933db15e716e84cca132fc15e5303e3ac6cbff4d641028cc681d675`.
- Matched 25% buy-and-hold: Coinbase -11.3461%; Bitstamp -11.3554%.
- Across all 17 cumulative net returns: Spearman rank correlation **0.985294**; Pearson correlation **0.997082**; mean absolute return difference **0.4702 percentage points**; maximum absolute difference **2.0931 percentage points**; 13/17 ordinal positions identical.
- Matched Bitstamp top five at 1x: RSI14 -1.3451% (11 trades), Bollinger -8.5148% (84), Z-Score20 -11.1827% (146), Donchian55/20 -12.3958% (193), Volatility Squeeze -13.4058% (203). All five, and all remaining candidates, are negative at 1x/2x/3x.
- Matched CSCV/PBO: 0.085714 across 17 candidates, 35 splits, 8 partitions; 10,792/10,799 returns used and 7 newest observations trimmed. This is a fixed-universe selection diagnostic only.
- Walk-forward on full Bitstamp history selected SMA200 in all four folds. Stitched 28,800-bar adaptive OOS: -16.7937% at 1x versus +42.4975% matched buy-and-hold; DD 26.5845%, Sharpe -0.6396, 501 closed trades. At 2x/3x the strategy returned -42.8682%/-60.7772%. This is an adaptive selection process, not one fixed candidate.

**CI and interpretation**
- Repository audit [run 1751](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44415730199): **581 tests passed in 8.874 seconds**; tracked Python compilation and `git diff --check` succeeded.
- Bitstamp run 17: **62 tests passed across 8 test groups**, research-module compilation succeeded, all 17 candidates evaluated, and the artifact uploaded successfully.
- Two earlier attempts on the reference-refresh change failed before research evaluation: one malformed Markdown f-string and one stale run-35 fixture assertion. Both were corrected; the final run 17 and audit run 1751 above are successful.
- The report's regime attribution is bar-level attribution by the regime known at the prior close, not separate regime portfolios. RSI14 has only 25 active signal bars in this matched sample (all in the bullish bucket), so its small trade count is not regime-robust evidence.
- The 17 candidates remain boolean long/flat signal-state proxies, not fully specified canonical entry/exit systems (F14 remains open). Costs are still fixed 0.10% fee + 0.05% slippage per side for controlled cross-venue comparison, not measured Bitstamp fees/spread/impact. There is still no untouched final holdout or sufficient forward-paper evidence.

**NO CANDIDATE PROMOTED.** This refresh corrects the exact-calendar reference and strengthens replication evidence; it does not establish profitability or justify paper/live promotion.
