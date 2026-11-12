# WHJ Bitcoin Strategy Research — Verified Rolling Walk-Forward Results (2026-11-12)

## Provenance and validation

- Repository: `sdndj98-art/WHJ-Bitcoin-Bot-2026`
- Research branch: `research/global-evidence-strategy-lab-20261112`
- Code commit evaluated: `b5bf04bfcbf2078106a50bc051ad0a7413fc4f3a`
- Historical workflow: [run 43209382505](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43209382505) — success; report artifact `whj-multi-strategy-research-28`.
- Repository validation: [run 43209382581](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43209382581) — success; 530 tests passed, Python compilation and whitespace checks passed.
- Dataset: Coinbase public BTC-USD hourly spot candles, 36,000 completed bars.
- Date range: 2022-10-04 11:00 UTC through 2026-11-12 10:00 UTC.
- Imputed short-gap candles: 13 (explicitly flagged by the loader).
- Dataset SHA-256: `6f46e4002b6025b7aebc3b550a7bbe5f148e57c1dc78b16c82e003e077db855b`.
- Universe: 17 predeclared long/flat candidate signal streams.
- Maximum allocation: 25%; no leverage, broker connection, live orders, or paper-ledger access.

## Separate 70/30 chronological comparison

The 17-candidate comparison used the final 30% of the hourly dataset as a single chronological OOS segment (10,800 candles). All 17 candidates had negative absolute net return at 1x costs.

The highest descriptive excess-return candidate was RSI14 mean reversion:
- Candidate net return: -1.36%.
- Matched 25% buy-and-hold: -8.88%.
- Excess return: +7.52 percentage points.
- Closed trades: 11.
- Periodic-return profit factor: 0.35.

This is not a profitable result: the candidate lost money in absolute terms, had very few trades, and its periodic profit factor was far below 1.0. The comparison's CSCV/PBO diagnostic was not computed because the return count did not meet the workflow's partition constraints.

## Expanding-window rolling walk-forward

Protocol:
- Initial training window: 19,800 hourly bars (55%).
- Four contiguous OOS folds of 3,600 return intervals each (14,400 OOS intervals total).
- 1,799 tail bars were left unused by this walk-forward run.
- At each fold, the candidate was selected using only the prior training history. The completed-close signal is executed at the next open.
- Fold signals were stitched into one continuous OOS portfolio; exposure and benchmark capital remain continuous across fold boundaries, and the benchmark entry cost is charged once.
- Cost stress reruns the frozen fold selections at 1x, 2x, and 3x fee/slippage assumptions.

### Aggregate stitched OOS results

| Costs | Adaptive strategy net | Matched buy-and-hold | Excess | Max open-to-open DD | Periodic PF | Sharpe | Closed trades | Exposure |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1x | -13.40% | -2.93% | -10.47 pp | -14.98% | 0.90 | -1.62 | 148 | 6.8% |
| 2x | -22.50% | -2.96% | -19.53 pp | -23.71% | 0.84 | -2.85 | 148 | 6.8% |
| 3x | -30.65% | -3.00% | -27.65 pp | -31.56% | 0.78 | -4.01 | 148 | 6.8% |

### Fold selections and 1x results

| Fold | Selected candidate | OOS open interval indices | Strategy return | Matched buy-and-hold | OOS closed trades |
|---:|---|---|---:|---:|---:|
| 1 | SMA200 regime | 19,800 → 23,400 | -7.02% | +2.52% | 66 |
| 2 | SMA200 regime | 23,400 → 27,000 | -5.64% | +1.76% | 73 |
| 3 | RSI14 mean reversion | 27,000 → 30,600 | -1.11% | -10.41% | 4 |
| 4 | RSI14 mean reversion | 30,600 → 34,200 | -0.19% | +3.74% | 5 |

The walk-forward procedure is an adaptive selection process, not one fixed strategy. It lost in all four folds in absolute terms and underperformed matched buy-and-hold in three of four folds. Its aggregate return, excess return, Sharpe, and periodic profit factor were all negative/poor; increasing costs worsened the result substantially.

## Decision and limitations

**No BTC candidate is approved or promoted.** The current evidence rejects deployment of this 17-candidate set as-is.

Important limits:
1. The 70/30 comparison and rolling walk-forward use overlapping portions of the same historical dataset; they are not independent replications.
2. There is no untouched final holdout left after these research experiments.
3. Fixed percentage fee/slippage assumptions do not model time-varying spread, order-book depth, market impact, latency, partial fills, or exchange-specific execution.
4. Periodic-return profit factor is not closed-trade profit factor.
5. CSCV/PBO was not computed for the 70/30 comparison; the manifest records only the 17 candidates in this workflow, not every experiment ever tried.
6. These are historical backtests, not forward-only paper results or live performance.

The next research stage should focus on independent data-source replication, explicit regime-by-regime diagnostics, uncertainty and concentration analysis, and an untouched final holdout. No paper balances, ledgers, risk limits, schedules, or live-order pathways were changed.
