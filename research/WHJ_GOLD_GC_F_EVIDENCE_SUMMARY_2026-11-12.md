# WHJ Gold Research — GC=F Evidence Summary (2026-11-12)

## Data and protocol

- Instrument: Yahoo Finance continuous COMEX gold futures reference, `GC=F`.
- This is **not spot XAU/USD**, not a broker bid/ask feed, and not a tradable continuous futures contract without roll conventions.
- Daily observations: 2,514.
- Date range: 2016-11-14 through 2026-11-11 UTC.
- Dataset SHA-256: `6b1561ab63f51393cfed9f3930f36f081f9558521b169448272bf31ed086c9b1`.
- Three chronological, non-overlapping OOS folds over the final 45%; each fold starts with $1,000.
- Completed daily-close signals execute at the next daily open.
- Costs are fixed per-side fee/slippage proxies at 1x, 2x, and 3x.
- No paper ledger, broker, or live order path was accessed.

## Main candidate: EMA50/EMA200 + past-only ATR90 filter

All figures below are percentage returns for each independent fold, not one compounded continuous equity curve.

| OOS fold | Dates | Candidate 1x | Matched 25% buy/hold 1x | Candidate 2x | Candidate 3x | Closed trades |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2022-05-13 to 2023-11-10 | +0.5878% | +1.7192% | +0.2235% | -0.1390% | 7 |
| 2 | 2023-11-13 to 2025-05-13 | +3.3208% | +16.5489% | +3.0204% | +2.7211% | 7 |
| 3 | 2025-05-14 to 2026-11-11 | +0.0987% | +6.3797% | -0.2634% | -0.6239% | 9 |

- Total closed trades across the three independent folds: 23, below the 30-trade minimum screening gate.
- Candidate underperformed matched buy-and-hold in all three folds at 1x, 2x, and 3x costs.
- At 1x, closed-trade profit factors by fold were 1.5594, 4.7491, and 1.0343. Sparse trades mean these estimates are weak evidence.
- At 3x costs, fold 1 and fold 3 became negative.

## EMA50/EMA200 baseline

- 1x fold returns: -0.3697%, +0.9610%, -0.1995%.
- Matched 25% buy-and-hold: +1.7192%, +16.5489%, +6.3797%.
- Closed trades: 6, 1, and 4 respectively.
- This baseline also failed to beat the matched benchmark and has very sparse trades.

## Decision

**No gold candidate is eligible for promotion.** The ATR-filtered candidate is less weak than the baseline in some folds, but it underperformed the matched benchmark in every fold and did not meet the minimum trade-count gate. Its 3x-cost performance was negative in two of three folds.

## What is still missing for genuine XAU/USD work

1. Broker-specific XAU/USD spot candles or tick data, with bid/ask prices and verified timestamps.
2. Actual session calendar, spread history, commissions, swaps/financing, and contract specifications.
3. Execution and gap stress using the intended broker's price feed.
4. A separate untouched holdout and forward-only spot shadow observations.

This report is historical research only. It is not a claim that gold trading is profitable and is not a recommendation to trade.
