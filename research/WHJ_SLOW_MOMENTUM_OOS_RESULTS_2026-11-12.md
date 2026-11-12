# WHJ isolated slow-momentum OOS results — 2026-11-12

## Reproducibility

- Workflow: [WHJ Isolated Slow Momentum Historical Research, run 43205660391](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43205660391)
- Artifact: `whj-isolated-slow-momentum-17`
- Code commit used by the run: `7236e2b1ecbd094d63f8e9ac3da98a685465587c`
- Source: Coinbase public BTC-USD spot hourly candles aggregated into complete UTC daily bars.
- Daily sample: 1,499 observations, 2022-10-05 through 2026-11-11; 13 hourly observations were explicitly imputed in the source series.
- Dataset SHA-256: `8dd886564c9efa8058fcda85e484b919d91493e71bfab477d3af256ff3456ff4`
- OOS: chronological 30% segment, daily index 1,049 through 1,498 (2025-08-19 through 2026-11-11).
- Initial capital: $1,000; allocation: 25%; 0.10% fee and 0.05% slippage per side.
- Execution: completed daily-close signal, next-close execution; 56-, 84-, and 112-day lookbacks.
- This is a historical OOS segment, not a rolling retraining test and not a new untouched final holdout.

## Normal-cost OOS results

| Lookback | Net return | Matched 25% buy-and-hold | Excess | Close-to-close DD | Closed trades | Closed-trade PF |
|---:|---:|---:|---:|---:|---:|---:|
| 56 days | -3.03% | -8.67% | +5.64 pp | 8.40% | 15 | 0.619 |
| 84 days | -6.43% | -8.67% | +2.25 pp | 8.64% | 6 | 0.031 |
| 112 days | -8.27% | -8.67% | +0.40 pp | 10.62% | 11 | 0.061 |

The 56-day candidate is the least-bad of these three in this sample and outperforms the matched benchmark in relative terms, but it still loses money and its closed-trade profit factor is below 1. It is not a profitable strategy.

## Cost sensitivity

| Lookback | 2x-cost return | 2x PF | 3x-cost return | 3x PF |
|---:|---:|---:|---:|---:|
| 56 days | -4.11% | 0.529 | -5.17% | 0.456 |
| 84 days | -6.90% | 0.016 | -7.37% | 0.003 |
| 112 days | -9.08% | 0.027 | -9.87% | 0.007 |

Relative to the matched buy-and-hold stream, the 56-day candidate's excess was +4.61 pp at 2x and +3.60 pp at 3x costs; absolute net returns remained negative at both levels.

## Uncertainty and fragility

- 56-day circular moving-block bootstrap (7-day blocks, 2,000 samples): 95% interval **-16.27% to +13.84%**. This interval is conditional on this one OOS series and the selected block length; it is not a future-profit probability.
- 84-day interval: **-18.26% to +6.40%**.
- 112-day interval: **-18.82% to +3.64%**.
- CSCV/PBO across only these three declared variants: **0.60** (6 partitions, 10 splits). This is a narrow selection-bias diagnostic; it does not cover all repository experiments and does not create an untouched holdout.
- The 56-day candidate's top single winning trade contributed 89.34% of its net positive winner contribution; its top five winners accounted for 100%. Excluding those five winners leaves negative net P&L. This is a concentration/fragility warning, not an alternative performance estimate.
- The 84- and 112-day candidates ended with open positions and negative unrealized net-liquidation P&L; the report includes that mark-to-market component.
- Drawdown is close-to-close net-liquidation drawdown, not intraday OHLC/tick-level liquidation drawdown.

## Temporal slices for the 56-day candidate

The three chronological OOS slices returned -3.60%, -4.17%, and +4.89%, with 7, 4, and 4 closed trades respectively. The final positive slice does not erase the two preceding losing slices or the overall negative OOS return.

## Decision

**NO CANDIDATE PROMOTED.** The 56-day candidate is a relative benchmark-beater in this particular falling/volatile OOS sample, but it is not profitable in absolute terms, has a low profit factor, few trades, highly concentrated winners, and a bootstrap interval spanning substantial losses and gains. Do not connect it to paper or live execution. Further evaluation requires an independently sourced venue replication, a predeclared untouched holdout, realistic spread/liquidity costs, and more forward-only observations.

This workflow used public historical data and an isolated evaluator. It did not read or write paper ledgers and did not place live orders.
