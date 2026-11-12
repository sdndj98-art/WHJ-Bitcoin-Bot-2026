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
- The test block retains the immediately preceding completed signal bar so the common evaluator's next-open execution timing remains aligned.
- Allocation is hard-capped at 25%; all folds remain descriptive and report `NO_CANDIDATE_PROMOTED`.
- Added tests for expanding/contiguous fold boundaries, future-price isolation of the first fold's selection, invalid inputs, the full 17-signal universe on synthetic OHLCV, and the allocation cap.

This is a new evaluator implementation, not a completed historical BTC result. It relies on the caller to provide causal, predeclared signal streams; it does not prove their causality, reserve a final untouched holdout, or model spread/depth/impact/latency. Full repository tests and a real historical workflow artifact must pass/be inspected before any empirical conclusion.

### Walk-forward fold integrity and cost stress (2026-11-12)

- Each fold chooses a candidate using only the expanding history through the prior boundary, then evaluates the frozen signal stream over the next block.
- The test slice retains two pre-test candles so the first OOS open-to-open return begins at the prior boundary open; successive fold return intervals are contiguous without a skipped boundary bar.
- Each selected fold is evaluated at 1x, 2x, and 3x the same fee/slippage assumptions. Candidate selection remains based on the predeclared 1x training score; stressed costs do not influence selection.
- Aggregate OOS net return, matched buy-and-hold return, excess return, and close-to-close drawdown are reported separately for each cost scenario.
- Drawdown is explicitly close-to-close/open-to-open equity drawdown, not intrabar OHLC drawdown.

The evaluator still requires a full repository test run and a historical dataset run before its metrics can be treated as empirical evidence. It does not model variable spread, order-book depth, impact, latency, or tick-level execution; no candidate is promoted.
