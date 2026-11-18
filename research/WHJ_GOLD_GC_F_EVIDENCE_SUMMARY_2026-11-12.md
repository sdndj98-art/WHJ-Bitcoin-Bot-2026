# WHJ Gold Research — GC=F Evidence Summary (2026-11-12)

## Data and protocol

- Instrument: Yahoo Finance continuous COMEX gold futures reference, `GC=F`.
- This is **not spot XAU/USD**, not a broker bid/ask feed, and not a tradable continuous futures contract without roll conventions.
- Daily observations: 2,514.
- Date range: 2016-11-14 through 2026-11-11 UTC.
- Dataset SHA-256: `6b1561ab63f51393cfed9f3930f36f081f9558521b169448272bf31ed086c9b1`.
- Validation: [GitHub Actions run 43208411769](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43208411769) succeeded; all 20 gold data, strategy, shadow-ledger, and runner tests passed; report artifact `whj-gc-f-gold-13` uploaded.
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

## Latest verified refresh — GC=F run 17 (2026-11-15)

The earlier table above is retained as historical evidence. The newer completed workflow artifact was downloaded, inspected, and its ZIP and dataset digests were independently recomputed.

- Workflow: [WHJ GC=F Gold Daily Research #17](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43771360299).
- Artifact: [whj-gc-f-gold-17](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43771360299/artifacts/14184397840).
- Artifact ZIP SHA-256: `d657e5ce7e6199e7aedc72b599f258c887fd5306ada439ed248112a4050b9736`.
- Code commit: `3acea79e56bf0748b94b9d4203fe8f31e2673b88`.
- Source: Yahoo Finance chart API, continuous COMEX gold futures reference `GC=F`; this is not spot XAU/USD.
- 2,514 daily candles, 2016-11-15T05:00Z through 2026-11-12T05:00Z.
- Dataset SHA-256: `b64ced282d8a0119c9752d5f66eee0beb5ea4593cb52e50adedc004082ee7337` (recomputed from the decompressed snapshot and matched the JSON report).
- Three chronological, non-overlapping OOS folds; each starts at $1,000. Signals use completed daily close and execute at next daily open. Maximum allocation is 25%, with 2% stop and 4% target. Fixed per-side fee/slippage proxies are 0.05%/0.05% at 1x, doubled/tripled for stress.

### EMA50/EMA200 + past-only ATR90 filter

All figures are independent fold returns, not one compounded continuous equity curve.

| OOS fold | Dates | Candidate 1x | Benchmark 1x | Candidate 2x | Candidate 3x | Closed trades | PF 1x | Intrabar DD 1x |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2022-05-16 to 2023-11-13 | +0.7495% | +1.6778% | +0.3845% | +0.0211% | 7 | 1.5594 | 1.6428% |
| 2 | 2023-11-14 to 2025-05-14 | +3.3208% | +15.4435% | +3.0204% | +2.7211% | 7 | 4.7491 | 1.3738% |
| 3 | 2025-05-15 to 2026-11-12 | +0.0987% | +4.8870% | -0.2634% | -0.6239% | 9 | 1.0343 | 2.2564% |

- Total closed trades: 23, below the 30-trade screening minimum.
- Candidate underperformed matched buy-and-hold in every fold at 1x, 2x, and 3x costs.
- At 3x costs, folds 1 and 3 are negative or near zero; fold 3 is -0.6239%.
- The EMA50/EMA200 baseline returned -0.2095%, +0.9610%, and -1.6801% at 1x across the three folds, with only 6, 1, and 4 closed trades; it also underperformed the benchmark.

**Decision remains NO CANDIDATE PROMOTED.** The newer GC=F results are not evidence of spot XAU/USD profitability. The gold workflow has no scheduled trigger (only workflow dispatch and selected-path pushes), and no broker XAUUSD history is present in the repository.

### Genuine XAUUSD blocker remains

The repository contains `xauusd_broker_data.py`, its tests, and the broker-feed contract, but no broker bid/ask OHLC or tick dataset. A valid spot evaluation still needs broker-specific bid/ask prices, session/DST calendar, actual spread history, commission, contract size, swap/financing and triple-swap rules, and an untouched holdout. GC=F must not be relabelled as XAUUSD.
