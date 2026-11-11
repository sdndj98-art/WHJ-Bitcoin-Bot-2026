# Global Evidence-Informed Strategy Research Plan (2026-11-12)

## Status and safety

This is a research specification, not a claim that a new strategy is profitable. It does not change existing strategy signals, paper ledgers, risk limits, schedules, or live-trading permissions. All experiments must remain isolated paper/backtest research. No exchange credentials or order endpoints are permitted.

The current production research universe is BTC-USD spot candles. Do not silently mix spot and perpetual-futures data. Funding, borrow, liquidation, and short-sale mechanics are out of scope unless a separately validated derivatives dataset and simulator are added.

## What the external evidence suggests

1. **Slow time-series momentum deserves a controlled candidate test.** A 2026 Bitcoin study reports that slower momentum signals (around a 12-week baseline) outperform faster variants in its sample, and that dynamic speed switching adds little. Treat this as a hypothesis to test, not a transferable parameter.
   - Kang & Ryu (2026), *Time-series momentum and market timing in Bitcoin*: https://ideas.repec.org/a/pal/risman/v28y2026i3d10.1057_s41283-026-00234-7.html
2. **Information-driven sampling and Triple Barrier labels are promising research methods.** A 2025 open-access crypto study reports better results from CUSUM event sampling plus Triple Barrier labels than conventional time bars/next-bar labels in its BTC/ETH experiments. Reproduce cautiously with strictly causal event timestamps and realistic fills.
   - Grądzki, Wójcik & Lessmann (2025): https://link.springer.com/article/10.1186/s40854-025-00866-w
3. **Volatility forecasts should be regime-aware, but are risk inputs rather than directional alpha by default.** A 2026 Bitcoin study finds model rankings differ between normal and crisis regimes; it emphasizes common information sets and rolling out-of-sample comparison.
   - Wafi et al. (2026): https://link.springer.com/article/10.1007/s42521-026-00229-9
4. **Intraday trend evidence is encouraging but not automatically net-profitable for this implementation.** A 2025 study reports a multi-model intraday BTC trend benchmark with gross-of-fees Sharpe around 1.6, while a volatility-targeted passive BTC benchmark is lower. Gross performance must not be treated as net performance.
   - Zarattini, Pagani & Barbon (2025): https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/
5. **Backtest selection itself creates overfitting risk.** Testing many variants and selecting the best can produce false winners; use explicit trial counts and estimate selection risk where feasible.
   - Bailey et al. (2017), *The Probability of Backtest Overfitting*: https://escholarship.org/uc/item/4w1110bb
6. **Technical rules are sensitive to costs and market conditions.** A 69-rule cryptocurrency study explicitly evaluates costs and bubble periods; transaction-cost assumptions must be part of the primary result, not an afterthought.
   - Hudson & Urquhart, *Technical trading and cryptocurrencies*: https://link.springer.com/article/10.1007/s10479-019-03357-1
   - *Technical analysis in cryptocurrency markets: Do transaction costs and bubbles matter?* (2022): https://www.sciencedirect.com/science/article/pii/S1042443122000816

Preprints, working papers, theses, and single-sample studies are lower-confidence evidence than independently replicated peer-reviewed work. Extraordinary reported machine-learning returns must not be copied as expected performance.

## Candidate families to test (not promote)

### A. Existing qualified baseline
- Keep the existing 4h + 6h EMA50/EMA200 paper ensemble as the incumbent.
- Preserve its current signal timing, next-available-close execution, costs, allocation, and risk stops.
- Do not overwrite or reseed its forward ledgers.

### B. Slow time-series momentum
- Candidate horizons: 8, 12, and 16 weeks, evaluated on completed daily closes.
- Position is long only when the trailing return over the horizon is positive; otherwise flat.
- Add a slow trend regime check only as a separately named ablation, not silently embedded.
- Compare simple 12-week rule against the incumbent; no optimization on final holdout.

### C. CUSUM event sampling + Triple Barrier research
- Build event timestamps from a causal volatility-scaled CUSUM filter.
- Label events using predeclared profit-taking, stop-loss, and maximum-holding barriers based only on information available after the event.
- Use purging and embargo around overlapping label horizons.
- Start with a simple interpretable baseline (logistic regression or tree) before deep models.
- This is a separate event-driven research module; do not substitute event bars for the existing hourly ledger.

### D. Volatility-regime risk overlay
- Compare a simple rolling realized-volatility forecast with GARCH-family forecasts; HMM/regime classification is optional and must be evaluated out of sample.
- First test whether forecasts improve risk calibration and drawdown without changing directional signals.
- Position sizing may only decrease risk relative to current limits; it must never raise the existing maximum allocation or risk budget.
- Missing or stale external data must fail closed to the baseline or flat, never create a trade.

### E. External information (optional, only with reliable licensed/public data)
- Funding/open interest are derivatives-market data and must be stored separately from spot BTC-USD data.
- Sentiment/news/on-chain metrics require timestamp provenance, publication-lag handling, survivorship/coverage checks, and a missing-data policy.
- Run ablations: price-only, price + one source, and price + source under stress. Keep a source only if it improves independent net results and stability.
- Do not scrape private accounts, bypass access controls, or use unlicensed/private datasets.

## Mandatory experimental design

1. Freeze the incumbent and save immutable input-data hashes, code commit, parameter manifest, and number of variants tested.
2. Validate OHLCV chronology, duplicate timestamps, gaps, timezone alignment, partial candles, and exchange-specific anomalies. Never forward-fill large gaps into tradable bars.
3. Use nested chronological evaluation: training/selection windows, validation windows, and a final untouched holdout. Add rolling walk-forward windows.
4. Apply purging/embargo when labels or positions overlap. Never use a candle's high/low/close before that candle has completed; execute no earlier than the next available bar under the simulator's fill rule.
5. Report all variants tried, not only winners. Where feasible, calculate Probability of Backtest Overfitting / CSCV and a multiple-testing-adjusted comparison.
6. Include matched buy-and-hold and flat-cash benchmarks with identical capital allocation assumptions.
7. Model entry and exit fees, spread, slippage, latency, and market impact. Test baseline, 2x, and 3x costs; if cost inputs are unknown, label them as assumptions.
8. Report net return, annualized return, Sharpe/Sortino with stated frequency, profit factor, trade count, exposure, turnover, max drawdown, time-under-water, tail loss, and regime/window breakdowns. Do not rank candidates on raw return alone.
9. Run sensitivity tests around parameters and start/end dates. A strategy that works only at one narrow setting fails robustness review.
10. Keep final holdout untouched until all design decisions are frozen. No repeated tuning against the holdout.

## Promotion gates

- Retain the repository's existing gates as the minimum: at least 30 closed out-of-sample trades, positive net OOS and elevated-cost stress results, profit factor at least 1.2, maximum drawdown no greater than 10%, all three chronological OOS windows non-negative, and outperformance versus matched buy-and-hold in normal and elevated costs.
- Require a separate forward-only paper sample before any promotion discussion. Historical warm-up candles do not count as forward trades.
- If the trade sample is too small, report **INSUFFICIENT EVIDENCE**, not pass/fail or a winner.
- Any risk-control breach, data-integrity failure, or missing ledger blocks the run and must not be repaired by silently reseeding state.
- Passing historical gates only qualifies a candidate for extended paper review. It never authorizes live trading.

## First implementation sequence

1. Audit and freeze the incumbent paper ledger and workflow cache state.
2. Implement candidate B (slow 8/12/16-week momentum) in an isolated research module with unit tests and deterministic fixtures.
3. Run historical and walk-forward tests with the same cost model and benchmarks as the incumbent.
4. If B survives, add candidate C (CUSUM + Triple Barrier) in a separate module.
5. Add D as a risk-only overlay after forecasting tests establish incremental value.
6. Publish a complete comparison report, including failures and the full trial count. Do not merge a candidate into the forward monitor until code review, tests, and explicit ledger-isolation checks pass.

## Decision rule

The objective is not to find the highest historical return. It is to identify a simple, reproducible strategy whose net performance survives independent time periods, realistic costs, parameter perturbations, and forward-only paper execution. If no candidate passes, the correct result is **no qualified strategy yet**.
