# Independent Bitstamp replication: EMA50/200 + ADX entry confirmation

**Latest workflow run:** 43139124171  
**Code commit tested:** 5babb73d3b36a1d663b8e86bc9f90a7033e94c4c  
**Data:** Bitstamp public BTCUSD spot hourly candles, aggregated to native 4h and 6h bars  
**Coverage:** 2018-08-25 22:00 UTC through 2026-11-12 01:00 UTC  
**Out-of-sample period:** 2024-05-26 12:00 UTC through 2026-11-12 00:00 UTC  
**Mode:** isolated historical research; paper ledgers untouched; live orders disabled

## Main out-of-sample comparison

Equal 50/50 4h + 6h sleeves, each starting from the same initial capital; 0.1% fee and 0.05% slippage per side.

| Variant | Net return | Profit factor | Max drawdown | Closed trades |
|---|---:|---:|---:|---:|
| EMA50/200 baseline | +7.33% | 1.42 | 7.45% | 98 |
| ADX >= 15 entry-only | +9.63% | 1.78 | 6.51% | 58 |
| ADX >= 20 entry-only (predeclared primary) | +7.87% | 1.57 | 7.70% | 54 |
| ADX >= 25 entry-only | +4.26% | 1.29 | 10.35% | 44 |
| Matched 50/50 buy-and-hold | +1.67% | n/a | 20.14% | n/a |

## Elevated-cost stress (2x fee and slippage)

| Variant | Net return | Profit factor | Max drawdown |
|---|---:|---:|---:|
| EMA50/200 baseline | +3.44% | 1.18 | 9.62% |
| ADX >= 15 entry-only | +7.26% | 1.53 | 7.16% |
| ADX >= 20 entry-only | +5.70% | 1.38 | 8.40% |
| ADX >= 25 entry-only | +2.54% | 1.16 | 11.17% |
| Matched 50/50 buy-and-hold | +1.59% | n/a | 20.10% |

## Temporal stability check

The ADX >= 15 variant returned +7.16%, +0.82%, and +1.45% in the three chronological OOS subperiods at 1x costs. At 2x costs, those returns were +6.31%, -0.05%, and +0.84%.

The predeclared ADX >= 20 primary returned +7.28%, -0.63%, and +1.13% at 1x costs; at 2x costs it returned +6.50%, -1.44%, and +0.56%. Thus neither threshold was positive in every subperiod at elevated costs.

## Separate expanding-window walk-forward selection

Workflow run **43139124035** independently selected an ADX threshold from prior training data only, then evaluated the next unseen fold. Each fold starts with $1,000; fold returns are not compounded.

| OOS fold | Training-only selection | Selected return | Selected return at 2x costs | Matched buy-and-hold |
|---|---|---:|---:|---:|
| 1 | ADX 25 | +4.72% | +4.00% | +5.28% |
| 2 | ADX 20 | -0.51% | -1.33% | +3.48% |
| 3 | ADX 20 | +1.11% | +0.54% | -5.72% |

The adaptive selection rule did not beat matched buy-and-hold in folds 1 or 2. Fold 2 was negative, including at 2x costs. This is a material robustness limitation, not a success to hide.

## Interpretation and limitations

- The fixed ADX >= 15 variant has the strongest aggregate result in this particular Bitstamp OOS replication and remains positive in aggregate under 2x costs.
- ADX >= 15 is not the predeclared primary threshold; its stronger aggregate result is exposed to selection and multiple-testing risk.
- The predeclared ADX >= 20 primary is positive in aggregate but has a negative middle OOS subperiod and does not beat buy-and-hold in the expanding-window fold 2.
- The training-only expanding-window selection rule is not consistently superior to buy-and-hold; no strategy is promoted.
- The result is specific to Bitstamp BTCUSD spot data and the stated 4h/6h sleeve protocol. Fixed percentage costs do not model actual spread, market impact, latency, partial fills, exchange outages, or broker financing.
- These are historical simulations, not forward-paper or live performance. No forward-only ADX ledger was created, seeded, reset, or changed by these workflows.

## Decision

**Research candidate only — not promoted.** Preserve the existing incumbent and all paper ledgers. The ADX family may proceed to a separately isolated, forward-only paper observation only after its ledger isolation and risk limits are reviewed. No live orders, automatic promotion, or changes to existing paper state are authorized by these results.

Artifacts:
- Cross-exchange replication: run 43139124171, artifact `whj-ema-adx-cross-exchange-211`.
- Expanding-window walk-forward: run 43139124035, artifact `whj-bitstamp-adx-expanding-walk-forward-62`.


## Audit rerun: independent expanding-window fold details (2026-11-12)

**Verified workflow run:** [43139793077](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43139793077)  
**Artifact:** `whj-bitstamp-adx-expanding-walk-forward-64`  
**Code commit:** `7fc69e6beff4c77ba14d9f7268382bddab6ed832`  
**Data:** 72,000 Bitstamp BTCUSD hourly candles, 2018-08-26 02:00 UTC to 2026-11-12 01:00 UTC.  
**OOS:** 2024-05-26 12:00 UTC to 2026-11-12 00:00 UTC.  
**Protocol:** 4h and 6h sleeves; threshold selected from prior training only among ADX 15/20/25; each fold independently starts at $1,000 and fold returns are not compounded. The simulator uses two 50%-allocation sleeves (not the separate 25% cap used in other research modules); therefore this experiment must not be presented as a 25%-risk portfolio.

| OOS fold | Training-only choice | Selected return (1x) | Selected return (2x) | Matched 50/50 buy-and-hold | Baseline EMA50/200 (1x) | Baseline EMA50/200 (2x) |
|---|---:|---:|---:|---:|---:|---:|
| 1 | ADX 25 | +4.72% | +4.00% | +5.28% | +5.50% | +3.72% |
| 2 | ADX 20 | -0.51% | -1.33% | +3.48% | +1.65% | +0.58% |
| 3 | ADX 20 | +1.11% | +0.54% | -5.72% | +0.14% | -0.86% |

This confirms that the training-only selector did not beat matched buy-and-hold in folds 1 and 2, and it lost money in fold 2 at both cost levels. Fold 3 benefited from a falling benchmark, so it should not be interpreted as universal alpha. The folds have independent starting capital and are not one continuous compounded portfolio. The reported 50% allocation per sleeve is a material risk-budget limitation and must be reconciled before any forward-paper trial.

**Decision unchanged: no promotion.** The result remains historical, cross-exchange evidence only; no forward-paper or live performance is established. Fixed costs do not represent actual spread, liquidity, market impact, latency, partial fills, or exchange outages. No paper ledger or order path was touched.
