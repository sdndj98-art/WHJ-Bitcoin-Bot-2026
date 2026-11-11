# Independent Bitstamp replication: EMA50/200 + ADX entry confirmation

**Workflow run:** 43109126854  
**Code commit tested:** 863897c6a04375bb71f3328be8805ff41332831d  
**Data:** Bitstamp public BTCUSD spot hourly candles, aggregated to native 4h and 6h bars  
**Coverage:** 2018-08-25 22:00 UTC through 2026-11-11 21:00 UTC  
**Out-of-sample period:** 2024-05-26 through 2026-11-11  
**Mode:** isolated historical research; paper ledgers untouched; live orders disabled

## Main out-of-sample comparison

| Variant | Net return | Profit factor | Max drawdown | Closed trades |
|---|---:|---:|---:|---:|
| EMA50/200 baseline | +7.26% | 1.42 | 7.45% | 98 |
| ADX >= 15 entry-only | +9.56% | 1.77 | 6.51% | 58 |
| ADX >= 20 entry-only (predeclared primary) | +7.80% | 1.57 | 7.70% | 54 |
| ADX >= 25 entry-only | +4.19% | 1.28 | 10.35% | 44 |
| Matched 50/50 buy-and-hold | +1.76% | n/a | 20.11% | n/a |

All figures are for the equal 50/50 4h+6h sleeve portfolio, under the workflow's stated 0.1% fee and 0.05% per-side slippage assumptions.

## Elevated-cost stress (2x fee and slippage)

| Variant | Net return | Profit factor | Max drawdown |
|---|---:|---:|---:|
| EMA50/200 baseline | +3.37% | 1.17 | 9.62% |
| ADX >= 15 entry-only | +7.19% | 1.52 | 7.16% |
| ADX >= 20 entry-only | +5.63% | 1.37 | 8.40% |
| ADX >= 25 entry-only | +2.47% | 1.15 | 11.17% |
| Matched 50/50 buy-and-hold | +1.68% | n/a | 20.07% |

## Interpretation and limitations

- The fixed ADX >= 15 entry-confirmation variant is the strongest of these Bitstamp historical comparisons and remains positive in all three chronological OOS subperiods (+7.09%, +0.93%, +1.43%) and under 2x costs.
- It does **not** outperform matched buy-and-hold in every individual subperiod; it does so only in two of three. Therefore do not describe it as uniformly dominant.
- ADX >= 20, the predeclared primary threshold, is also positive overall and under 2x costs, but its middle OOS subperiod is negative (-0.51%).
- ADX >= 25 fails the 10% drawdown limit under 2x costs and has weaker PF.
- The >=15 threshold is one of several tested variants; its stronger historical result carries selection/ multiple-testing risk. It is not permission to promote or deploy.
- This is a cross-exchange replication for the EMA50/200 + ADX family, **not** a result for the newly added 8/12/16-week slow-momentum candidate.
- No forward-only ADX ledger was created, seeded, reset, or changed by this workflow.

## Decision

**Research candidate only — not promoted.** Preserve the existing incumbent and all paper ledgers. Any next test should use a new isolated forward-only paper ledger after explicit ledger-isolation review, with the current risk caps unchanged. The slow-momentum lab must be evaluated separately on its own data and cost model before comparing it with this result.

Source artifact: GitHub Actions run 43109126854, artifact `whj-ema-adx-cross-exchange-101`.
