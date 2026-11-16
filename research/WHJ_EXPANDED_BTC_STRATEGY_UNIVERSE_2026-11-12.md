# WHJ Expanded BTC Strategy Universe

Date: 2026-11-12
Branch: research/global-evidence-strategy-lab-20261112

## Purpose

Add a broad, explicit strategy-family universe without pretending that every family is currently testable from hourly spot OHLCV. The isolated `strategy_family_lab.py` emits completed-bar candidate states only. It has no simulator, portfolio, account, exchange, or order integration. Earliest valid hypothetical execution is the next bar.

## Implemented signal families

| Family | Candidate rules |
|---|---|
| Trend | SMA 20/50, EMA 12/26, SMA200 regime |
| Momentum | 20/60/120-bar rate-of-change with long-term regime filter |
| Breakout | Donchian 20/10, Donchian 55/20, ATR-buffered channel breakout |
| Mean reversion | RSI(2), RSI(14), Bollinger(20,2), z-score(20, -1.5), stochastic reversal |
| Volume/flow proxies | Volume-confirmed breakout, OBV trend confirmation |
| Volatility | ATR-normalized volatility compression followed by breakout |

The Bollinger candidate enters below -2 standard deviations; the separate z-score candidate enters below -1.5 standard deviations. A deterministic regression test verifies they are not duplicate signal streams. These are candidate signal definitions, not claims of profitability. They are intentionally separate from the existing `strategy_lab.py` and historical/paper workflows until a common evaluator and matched benchmarks are explicitly wired and tested.

## Deferred until suitable data exists

- Derivatives: funding-rate carry, perpetual basis, open-interest changes, liquidation cascades.
- Order book: spread/depth imbalance, book pressure, executable market impact.
- Cross-asset: cointegration/pairs, relative strength, cross-asset momentum and rotation.
- Event/on-chain: macro event filters, exchange netflows, on-chain flows.
- Advanced: hidden-Markov regime classification, supervised ML and reinforcement learning.

Do not substitute OHLCV proxies for unavailable funding, open-interest, liquidation, order-book, or on-chain observations. Missing inputs are not zero and are not a pass.

## Required common evaluation before any candidate can compete

1. Freeze candidate definitions and record all trials, parameters, data hashes and commit IDs.
2. Use identical chronological windows, next-bar execution timing, fees, spread/slippage assumptions and matched buy-and-hold/flat-cash benchmarks.
3. Report net return, exposure, turnover, trade count, profit factor, Sharpe/Sortino with frequency, drawdown measurement type, tail loss, time-under-water and open-position liquidation value.
4. Run 2x/3x cost stress, conservative OHLC execution, volatility/liquidity regime slices, and independent venue replication where data permits.
5. Use true rolling walk-forward selection only within prior training data; reserve a final untouched holdout.
6. Report bootstrap uncertainty, parameter/date sensitivity, trade concentration and multiple-testing risk.
7. Mark low-sample candidates `INSUFFICIENT EVIDENCE`; never force a winner.
8. Only after historical gates, allow separate forward-only paper observation. No live trading approval follows from a backtest.

## Explicit exclusions

Options volatility-surface strategies, funding/basis arbitrage, order-book strategies and on-chain strategies are not implemented because the current spot OHLCV dataset cannot support honest tests for them. They require dedicated, timestamp-aligned datasets and their own execution/cost models.

## Safety

No existing paper ledgers, balances, risk limits, schedules, exchange credentials, Telegram integrations or live order pathways are changed. The new module is standalone research code.

## Common evaluator and chronological holdout runner

- `strategy_family_evaluator.py` evaluates completed-close signals with next-open exposure changes and subsequent open-to-open returns. It charges fixed fee/slippage on turnover and provides matched buy-and-hold returns.
- `strategy_family_runner.py` applies this protocol to all 17 implemented candidates. Its `evaluation_start_index` option calculates signals using full past history while retaining the immediately preceding completed candle as the first OOS signal; the first OOS fill is at the next open.
- `.github/workflows/multi-strategy-isolated-research.yml` runs a public Coinbase BTC-USD hourly-data experiment with a 70/30 chronological split, 1x/2x/3x fixed cost stress, per-candidate dataset-hashed trial manifests, and CSCV/PBO diagnostics across only these declared candidates.
- Workflow output is a research artifact; it never reads/writes paper ledgers or places orders. It labels the ranking descriptive and all candidates unpromoted.

The 70/30 experiment is not rolling walk-forward retraining and does not supply an untouched final holdout. Fixed costs do not model spread, depth, impact, latency or partial fills. No result should be called validated until the workflow artifact is inspected.

## Expanding-window rolling walk-forward evaluator

- Added `rolling_walk_forward.py` with an expanding training window. Each fold selects one of the predeclared candidate signal streams using training-period excess return versus matched buy-and-hold, freezes that candidate, and evaluates the next contiguous block.
- Each fold is selected only after the final training candle closes. Its first selected signal executes at the following open; the test slice includes that prior signal candle and the endpoint candle.
- Allocation is hard-capped at 25%; all folds remain descriptive and report `NO_CANDIDATE_PROMOTED`.
- Added tests for expanding/contiguous fold boundaries, future-price isolation of the first fold's selection, invalid inputs, the full 17-signal universe on synthetic OHLCV, and the allocation cap.

This is a new evaluator implementation, not a completed historical BTC result. It relies on the caller to provide causal, predeclared signal streams; it does not prove their causality, reserve a final untouched holdout, or model spread/depth/impact/latency. Full repository tests and a real historical workflow artifact must pass/be inspected before any empirical conclusion.

### Walk-forward fold integrity and cost stress (2026-11-12)

- Each fold chooses a candidate using only the expanding history through the prior boundary, then evaluates the frozen signal stream over the next block.
- The fold slice retains one prior signal candle and one endpoint candle. OOS returns start at the next open after selection, and adjacent folds meet at the same open boundary without overlapping or skipping an OOS return.
- Each selected fold is evaluated at 1x, 2x, and 3x the same fee/slippage assumptions. Candidate selection remains based on the predeclared 1x training score; stressed costs do not influence selection.
- The aggregate OOS stream is stitched and evaluated once, preserving exposure across candidate switches and charging the buy-and-hold entry cost once. Aggregate net return, matched benchmark, excess return, and open-to-open drawdown are reported for each cost scenario.
- Drawdown is open-to-open equity drawdown, not intrabar OHLC drawdown.

The evaluator still requires a full repository test run and a historical dataset run before its metrics can be treated as empirical evidence. It does not model variable spread, order-book depth, impact, latency, or tick-level execution; no candidate is promoted.


## Independent Bitstamp replication of all 17 declared signal-state candidates (2026-11-16)

- Evaluator: `bitstamp_strategy_family_research.py`.
- Workflow: [WHJ Bitstamp 17-Candidate Independent Research, run 43967507369](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43967507369).
- Artifact: [whj-bitstamp-17-strategy-research-3](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43967507369/artifacts/14276064048).
- Source: Bitstamp public BTCUSD hourly OHLC; 72,000 gap-free bars, 2018-08-30 through 2026-11-16; no imputation.
- Dataset SHA-256: `b0113cfd54fe0aa29da724c534a2f6deb241a0ee123aa3efe7a0b59426361fb2`.
- 70/30 chronological split: 21,600 OOS candles / 21,599 open-to-open returns; 17 candidates.
- Same fixed fee/slippage rates as the Coinbase experiment were retained to isolate the venue price series. They are not Bitstamp account-specific costs.
- Every candidate was negative at 1x/2x/3x and every candidate underperformed the matched 25% buy-and-hold benchmark (+3.56% at 1x).
- Best net-return candidate: RSI14 at -3.38% (max DD 3.43%, periodic PF 0.452, Sharpe -1.895, 37 closed trades); worst: Stochastic at -65.40%.
- CSCV/PBO 0.0 over 35 splits is a relative ranking diagnostic only, not evidence of profitability.
- Expanding walk-forward selected SMA200 in all four folds but returned -16.79% at 1x versus +39.09% matched buy-and-hold; 2x -42.87%, 3x -60.78%.
- This independent venue run does not share the Coinbase OOS calendar window and does not close F14: these remain boolean signal-state proxies, not canonical entry/exit systems. No candidate was promoted; no paper state or live execution was accessed.


## Exact same-calendar Coinbase–Bitstamp comparison

The first Bitstamp 70/30 full-history OOS split was longer than the Coinbase run-33 window. A second, exact overlap was therefore added and frozen to Coinbase run 43649648836:

- Workflow [43968648454](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43968648454), artifact [14276514574](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43968648454/artifacts/14276514574).
- Same calendar: 2025-08-21T22:00Z through 2026-11-14T21:00Z; 10,799 open-to-open returns.
- Matched Bitstamp slice SHA-256: `2d695ceb526a69a9816b85ed1f2d7dbe5bd13072eaf2062ab8bdf97a1784e9f6`.
- The 17-candidate rank correlation across feeds is Spearman **0.992647** and Pearson **0.996070**; mean absolute return difference is 0.5268 percentage points.
- The top five remain RSI14 (-1.3451%), Bollinger (-8.5148%), Z-Score20 (-11.1827%), Donchian55/20 (-12.3974%), and Volatility Squeeze (-13.4058%) on Bitstamp. All 17 remain negative at 1x, 2x and 3x; matched buy-and-hold is -11.14%.
- PBO is 0.085714 on both same-date feeds (35 splits, 8 partitions); this is a relative ranking diagnostic, not a profitability probability.
- A no-lookahead regression test changes all Bitstamp rows after the frozen endpoint and verifies the matched ranking and slice hash do not change.

This is a strict same-calendar price-feed comparison, unlike the separate full-history Bitstamp 70/30 OOS result. The cost assumptions are still fixed proxies, not measured Bitstamp fees/spread. Candidate definitions remain signal-state proxies (F14 open); no candidate is promoted.
