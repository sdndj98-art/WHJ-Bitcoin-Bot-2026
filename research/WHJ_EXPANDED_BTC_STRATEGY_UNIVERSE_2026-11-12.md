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


## Signal-state semantics and named proxy limitations (2026-11-18)

The common evaluator consumes boolean long/flat states: `True` means remain long and `False` means flat, with state changes applied at the next open. The machine-readable `strategy_universe()["signal_semantics"]` metadata is included in the batch runner output so downstream research reports can preserve this interpretation.

The following names are descriptive proxies, not complete canonical entry/exit systems:

- `donchian_20_10_breakout`: entry is close above the prior 20-bar high; there is no separate prior-10-bar-low exit.
- `donchian_55_20_breakout`: entry is close above the prior 55-bar high; there is no separate prior-20-bar-low exit.
- `stochastic_reversal`: a one-bar %K threshold-crossing event is interpreted as a one-interval long pulse; no %K/%D crossover or overbought exit is implemented.
- `volume_confirmed_breakout` and `volatility_squeeze_breakout`: entry confirmation is embedded in the boolean state, so the common evaluator exits when the combined condition becomes false.

This metadata does not change signals, historical metrics, or candidate definitions. Existing Coinbase/Bitstamp results remain results for the exact proxy states used in those runs. Any canonical entry/exit redesign must use new candidate IDs, new trial manifests, and a new predeclared evaluation window; do not relabel prior results.

## Latest verified exact-calendar refresh — Coinbase run 40 / Bitstamp run 17 (2026-11-19)

This section supersedes the older run-33/run-35 exact-calendar figures above. The previous Bitstamp run 13/14 artifact still referenced Coinbase run 35; the current reference is now pinned to the immutable Coinbase run 40 snapshot and was re-evaluated on Bitstamp run 17.

### Reproducibility and sample sizes

- Coinbase workflow [run 40](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44414511120), code commit `f71f2427ffbb211d9b44aae2f2bd657bff4c88c8`, artifact [14479701180](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44414511120/artifacts/14479701180).
- Coinbase: 36,000 BTC-USD hourly candles, 25,200 train candles, 10,800 OOS candles / 10,799 OOS open-to-open returns; 13 hourly imputations are explicitly marked. Dataset SHA-256: `3b1d145f79f21e8e2a84d94e6d1f64b5845fc3c5557cc7d93a806f9cca043804` (recomputed from the decompressed snapshot and matched the report).
- Bitstamp workflow [run 17](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44415730207), code commit `631e35ea22ef1a9f15086cc8dd4dd9115dd0383a`, artifact [14479033160](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44415730207/artifacts/14479033160).
- Bitstamp: 72,000 BTCUSD hourly candles, 50,400 train candles, 21,600 OOS candles / 21,599 OOS open-to-open returns; zero duplicates, gaps, or imputed bars. Dataset SHA-256: `5e9d2343b3ba8484aa1430b5d3055965259ac4298d4a49e0ab2cf380004c054a` (recomputed and matched the report).
- Both reports evaluated the same 17 predeclared boolean long/flat signal-state proxies. No candidate rule was changed.

### Exact shared OOS calendar

- Both venues: 2025-08-25T22:00:00Z through 2026-11-18T21:00:00Z; 10,799 open-to-open returns.
- Coinbase matched 25% buy-and-hold: -11.3461%; Bitstamp: -11.3554%.
- Bitstamp matched-slice SHA-256: `1130c7411933db15e716e84cca132fc15e5303e3ac6cbff4d641028cc681d675`.
- Across the 17 candidate cumulative net returns: Spearman rank correlation 0.985294; Pearson 0.997082; mean absolute return difference 0.4702 percentage points; maximum difference 2.0931 percentage points; 13/17 ordinal ranks identical.

### Matched-calendar ranking — Bitstamp

Costs are 0.10% fee + 0.05% slippage per side at 1x; both are multiplied at 2x/3x. These are controlled comparison assumptions, not measured Bitstamp fees, spread, depth, or market impact.

| Rank | Candidate | 1x net | 2x net | 3x net | Max DD | Period PF | Sharpe | Closed trades |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | RSI14 mean reversion | -1.3451% | -2.1561% | -2.9608% | 1.3945% | 0.3548 | -1.8731 | 11 |
| 2 | Bollinger mean reversion | -8.5148% | -14.1036% | -19.3529% | 8.5148% | 0.2807 | -4.6322 | 84 |
| 3 | Z-Score20 mean reversion | -11.1827% | -20.3995% | -28.6628% | 11.1827% | 0.4368 | -4.9100 | 146 |
| 4 | Donchian 55/20 | -12.3958% | -24.2076% | -34.4304% | 12.6666% | 0.4340 | -4.9130 | 193 |
| 5 | Volatility Squeeze | -13.4058% | -25.6416% | -36.1521% | 13.4058% | 0.3583 | -6.6442 | 203 |
| 6 | SMA200 regime | -14.1413% | -24.8205% | -34.1747% | 17.1380% | 0.9125 | -1.9092 | 177 |
| 7 | Volume Breakout | -14.2474% | -29.0760% | -41.3445% | 14.5747% | 0.5035 | -4.4114 | 253 |
| 8 | ROC60 momentum | -15.4507% | -28.6398% | -39.7754% | 16.6895% | 0.8855 | -2.3215 | 226 |
| 9 | ROC120 momentum | -15.7731% | -27.1842% | -37.0528% | 18.6893% | 0.8884 | -2.3025 | 194 |
| 10 | RSI2 mean reversion | -17.0451% | -30.0905% | -41.0882% | 17.0451% | 0.3447 | -7.1281 | 228 |
| 11 | ATR Channel | -18.2907% | -35.7821% | -49.5337% | 18.5883% | 0.4789 | -5.3876 | 321 |
| 12 | ROC20 momentum | -19.5083% | -37.2120% | -51.0264% | 20.1801% | 0.8315 | -3.2269 | 331 |
| 13 | Donchian 20/10 | -19.9177% | -38.5542% | -52.8583% | 20.2094% | 0.4853 | -5.6793 | 353 |
| 14 | SMA20/50 trend | -25.1407% | -43.2898% | -57.0432% | 26.4076% | 0.7860 | -4.3013 | 370 |
| 15 | EMA12/26 trend | -27.2551% | -45.1803% | -58.6929% | 27.2551% | 0.8196 | -4.0860 | 377 |
| 16 | OBV trend confirmation | -34.1308% | -56.0438% | -70.6714% | 34.3257% | 0.7547 | -5.5217 | 539 |
| 17 | Stochastic reversal | -40.7810% | -65.3970% | -79.7848% | 40.7810% | 0.2733 | -12.2545 | 716 |

All 17 candidates are negative at all three cost levels. The best-ranked RSI14 proxy is not profitable: only 11 closed trades, PF below 1, and negative Sharpe. Its 25 active signal bars in this matched window all occur in the bullish regime bucket; regime figures are bar-level attribution, not independent regime portfolios.

### Full-history Bitstamp and walk-forward cross-check

- Full-history 70/30 OOS matched buy-and-hold: +2.83%; all 17 candidates negative at 1x/2x/3x.
- Full-history best RSI14: -3.3822%, DD 3.4275%, PF 0.4518, Sharpe -1.8949, 37 trades; 2x -6.0280%, 3x -8.6022%.
- Full-history PBO 0.0 and exact-window PBO 0.085714, each over 35 CSCV splits. Both are narrow ranking-selection diagnostics only.
- Expanding walk-forward selected SMA200 in all four folds. Stitched 28,800-bar adaptive OOS: -16.7937% at 1x versus +42.4975% benchmark, DD 26.5845%, Sharpe -0.6396, 501 closed trades; 2x -42.8682%, 3x -60.7772%.

### Decision

The exact-calendar replication supports the conclusion that the negative ranking is not a Coinbase-only price-series artifact. It does not validate the proxy semantics (F14 remains open), actual venue-specific execution costs, an untouched final holdout, or forward profitability. **NO CANDIDATE PROMOTED.**
