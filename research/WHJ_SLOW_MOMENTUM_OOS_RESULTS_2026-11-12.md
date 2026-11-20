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


## Latest verified refresh — 2026-11-14, run #21

The earlier run above is retained as historical evidence. The latest dedicated workflow artifact was downloaded and inspected directly; these values supersede the older run-17 table for the newer immutable snapshot.

- Workflow: [WHJ Isolated Slow Momentum Historical Research #21](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43649648867)
- Artifact: [whj-isolated-slow-momentum-21](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43649648867/artifacts/14135087494)
- Code commit: `c110b7f330425c894f968eaca066efe88780f8b5`
- Generated: 2026-11-14T22:45:14Z
- Source: Coinbase public BTC-USD hourly spot, aggregated into complete UTC daily candles.
- Sample: 36,000 hourly candles → 1,499 daily candles; 2022-10-07 through 2026-11-13.
- Imputed hourly observations: 13 (explicitly marked).
- Dataset SHA-256: `9b3f47270eef545e813e0e73837dad322ac88291b7f5cc4720e31b44fb2793ea`
- Chronological split: 70%/30%; OOS daily index 1,049 onward. This remains a historical OOS segment, not a rolling retraining test or an untouched final holdout.
- Execution: completed daily-close signal, next daily close fill; 25% allocation; 0.10% fee and 0.05% slippage per side.

### Latest normal-cost OOS results

| Lookback | Net return | Matched 25% buy-and-hold | Excess | Close-to-close DD | Closed trades | Closed-trade PF |
|---:|---:|---:|---:|---:|---:|---:|
| 56 days | -2.9508% | -9.8791% | +6.9283 pp | 8.4002% | 15 | 0.6253 |
| 84 days | -8.0912% | -9.8791% | +1.7879 pp | 10.2742% | 7 | 0.0207 |
| 112 days | -9.9203% | -9.8791% | -0.0412 pp | 12.2350% | 11 | 0.0616 |

### Latest cost sensitivity

| Lookback | 2x return | 2x PF | 3x return | 3x PF |
|---:|---:|---:|---:|---:|
| 56 days | -4.0295% | 0.5335 | -5.0945% | 0.4600 |
| 84 days | -8.5548% | 0.0111 | -9.0153% | 0.0024 |
| 112 days | -10.7060% | 0.0271 | -11.4837% | 0.0070 |

Matched buy-and-hold returned -9.92% at 2x and -9.97% at 3x. Relative outperformance by the 56-day candidate does not change its negative absolute return.

### Latest uncertainty and fragility

- 56-day 95% circular moving-block bootstrap CI: **-16.4635% to +13.7391%** (7-day blocks, 2,000 resamples).
- 84-day CI: **-19.9606% to +4.7972%**.
- 112-day CI: **-21.4315% to +2.1616%**.
- CSCV/PBO across only these three declared variants: **0.50**, 6 partitions, 10 splits, 75 observations per partition. This is a narrow selection-bias diagnostic, not a future-profit probability or an untouched holdout.
- 56-day top winner contributed 89.3424% of gross winning P&L; its top five winners contributed 100%. Net P&L excluding those five winners was -$78.7581.
- 84-day top winner contributed 100% of gross winning P&L; 112-day top winner contributed 41.7121%.
- The 112-day candidate ended with one open position and -$25.2177 unrealized net-liquidation P&L; its total reported return includes this mark-to-market value.
- The 56-day OOS slices were -3.6419%, -3.7134%, and +4.8931%, with 7, 4, and 4 closed trades. These are chronological slices, not rolling walk-forward retraining.

**Decision remains NO CANDIDATE PROMOTED.** The 56-day variant is less negative than the matched benchmark in this sample, but still loses money, has only 15 closed trades, PF below 1, highly concentrated winners, and a bootstrap interval spanning large losses and gains. Do not connect it to paper or live execution.


## Latest verified refresh — 2026-11-17, run #22

This refresh was generated after the slow-momentum cost-input validation fix. The report and compressed dataset were downloaded from the completed workflow artifact and checked against GitHub's artifact digest and the canonical dataset hash.

- Workflow: [WHJ Isolated Slow Momentum Historical Research #22](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44151979400)
- Artifact: [whj-isolated-slow-momentum-22](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44151979400/artifacts/14359971027)
- Artifact ZIP SHA-256: `3d640f573cab6412447b9d8e2885ac9450018bc8fe5d37aac710fe07055deab3`
- Code commit: `63a82b8bf9768ba85bca14c2b00eb08e8567daf4`
- Generated: 2026-11-17T18:50:30Z
- Source: Coinbase public BTC-USD hourly spot, aggregated to complete UTC daily candles.
- Sample: 36,000 hourly candles → 1,499 daily candles; 2022-10-10 through 2026-11-16.
- Imputed hourly observations: 13 (explicitly marked).
- Canonical daily dataset SHA-256: `5feba5d5f2f97eaec192ae058b2a689d09556717a7dabc686e1715a470f765db`; independently recomputed from the decompressed artifact snapshot and matched both the JSON report and all three trial manifests.
- Chronological split: 70%/30%; OOS daily index 1,049 onward (2025-08-24 through 2026-11-16). This remains a historical OOS segment, not rolling retraining or a newly reserved final holdout.
- Execution: completed daily-close signal, next daily close fill; 25% allocation; 0.10% fee and 0.05% slippage per side.
- Artifact flags: `research_only=true`, `execution_enabled=false`, `live_orders=false`, `paper_ledgers_read_or_written=false`.

### Latest normal-cost OOS results

| Lookback | Net return | Matched 25% buy-and-hold | Excess | Close-to-close DD | Closed trades | Closed-trade PF | Open position |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 56 days | -3.1590% | -10.7632% | +7.6042 pp | 7.7682% | 15 | 0.6087 | No |
| 84 days | -8.2911% | -10.7632% | +2.4721 pp | 10.2742% | 7 | 0.0201 | No |
| 112 days | -10.9921% | -10.7632% | -0.2289 pp | 13.4259% | 12 | 0.0422 | No |

The 56-day candidate remains negative in absolute terms despite relative outperformance. Its 95% seven-day circular moving-block bootstrap interval is **-16.4932% to +13.1444%**. Its top winning trade contributes 89.3424% of gross winning P&L; the top five contribute 100%. The 56-day OOS slices are -5.5386%, -2.6047%, and +4.8931%, so only the final slice is positive.

### Latest cost sensitivity

| Lookback | 2x return | 3x return |
|---:|---:|---:|
| 56 days | -4.2349% | -5.2972% |
| 84 days | -8.7532% | -9.2123% |
| 112 days | -11.7660% | -12.5320% |

Matched buy-and-hold under the corresponding 2x/3x assumptions remains the report's benchmark; every candidate still has a negative absolute return under both stress levels.

### Latest trial-governance diagnostic

- CSCV/PBO: **0.40**, six partitions and ten splits, across only the three declared 56/84/112-day variants.
- The PBO is a narrow selection-bias diagnostic on this same OOS segment; it is not a future-profit probability, global experiment census, or substitute for an untouched final holdout.
- All candidates remain below the 30-closed-trade screening minimum.
- No candidate is selected or promoted.

**Decision remains NO CANDIDATE PROMOTED.** The 56-day variant is less negative than the matched benchmark in this sample but loses money, has PF below 1, only 15 closed trades, concentrated winners, and a bootstrap interval spanning material losses and gains. Do not connect it to paper or live execution.


## Review note — 2026-11-19: current source validation versus latest artifact

The latest dedicated slow-momentum artifact retrievable in this review remains run #22:

- Workflow: [run 44151979400](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44151979400).
- Artifact: [whj-isolated-slow-momentum-22](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44151979400/artifacts/14359971027).
- Artifact ZIP SHA-256: `3d640f573cab6412447b9d8e2885ac9450018bc8fe5d37aac710fe07055deab3`; recomputed during this review and matched the GitHub artifact digest.
- Artifact code commit: `63a82b8bf9768ba85bca14c2b00eb08e8567daf4`; decompressed daily dataset SHA-256 recomputed as `5feba5d5f2f97eaec192ae058b2a689d09556717a7dabc686e1715a470f765db`, matching the report's trial-governance manifest.

On 2026-11-19, F25 added overflow-safe validation for unrepresentably large integer inputs in the slow-momentum evaluator and its direct signal/periodic-return/cost-stress helpers. This is validation-only: it does not change the momentum rule, next-close fill timing, fee/slippage formulas, allocation cap, candidate parameters, or metric calculations. The run-22 performance figures above therefore remain historical evidence from the pre-F25 code commit, not a fresh run of the updated source.

No later slow-momentum artifact was exposed by the available workflow/artifact lookup in this review. The workflow definition currently has `workflow_dispatch` and branch-push triggers but no scheduled trigger. A post-F25 run and its artifact remain pending; no new performance result is claimed.


## Verification refresh — 2026-11-20: Slow Momentum run #24

The earlier review note in this file recorded run #22 as the newest retrievable artifact at that time. That was superseded by the successful push-triggered run #24 on commit `632929b296daf7bf7a923c14875774fc29b97b81`.

- Workflow: [Slow Momentum #24](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44592930502)
- Artifact: [whj-isolated-slow-momentum-24](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44592930502/artifacts/14564311691)
- Artifact ZIP SHA-256: `6fc2b8e193863cc80ec37aa12690a84c2c88e597b009b137302bf77ca79d3cd5`
- Daily dataset SHA-256, recomputed from the decompressed artifact: `aa1003c9bdd6d8addb3c05fc9d27990f5dda4c9fff985b2ff685d12dde716f35`
- Source: public Coinbase BTC-USD hourly candles aggregated into complete UTC daily bars; 36,000 hourly source bars, 1,499 daily bars, 13 hourly observations explicitly imputed and disclosed
- Daily interval: 2022-10-12 through 2026-11-18 UTC; 70/30 chronological split at daily index 1,049; 450 daily OOS bars
- The three-variant manifest records only these slow-momentum trials; it is not a count of all repository experiments

| Lookback | OOS 1x | OOS 2x | OOS 3x | Max DD 1x | PF | Closed trades |
|---:|---:|---:|---:|---:|---:|---:|
| 56 days | -2.8041% | -3.8848% | -4.9518% | 7.5232% | 0.6375 | 15 |
| 84 days | -7.9504% | -8.4150% | -8.8765% | 10.2742% | 0.0211 | 7 |
| 112 days | -11.3866% | -12.2221% | -13.0484% | 13.8074% | 0.0436 | 12 |

- The 25%-allocation buy-and-hold benchmark returned -10.9571% over the same OOS interval.
- The 56-day candidate's three fixed OOS subperiods were -4.9049%, -2.5588%, and +4.8931%; it remains negative overall.
- The 56-day candidate's top winner contributed 89.3424% of its net winning-trade contribution; its dependence-aware moving-block bootstrap 95% return interval was -15.7018% to +13.6967%.
- The 84-day candidate had only seven closed trades; the 112-day candidate ended with one open position and -$7.161 unrealized net-liquidation P&L.
- CSCV/PBO was 0.50 across three declared variants, six partitions, ten splits, and 75 observations per partition. This is a selection-bias diagnostic only, not a probability of future profit.
- These are historical OOS and fixed subperiod results, not rolling walk-forward or forward paper-trading evidence. All three variants remain research-only and unqualified.



## Latest verified refresh — 2026-11-20, isolated run #26 (post-F34)

This supersedes the earlier notes that listed run #22 or #24 as the newest verified artifact. The successful push-triggered workflow on code commit `d17474580190ab587ae5f675940a8eaeac625b9d` includes the F34 positive-price input guard in `momentum_signals()`.

- Workflow: [WHJ Isolated Slow Momentum Historical Research #26](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44792072224)
- Artifact: [whj-isolated-slow-momentum-26](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44792072224/artifacts/14657465785)
- Artifact ZIP SHA-256: `5d9fac2ddcfb0f833a22bfb8560e4c9e3270787715c159264aa8ce3a536b0a63`; independently recomputed from the downloaded ZIP and matched the GitHub artifact digest.
- Canonical daily dataset SHA-256: `d078cc223c281d1bb91a8a9f6139f46a33271ac835864e3b07605ae3bda600ee`; independently recomputed from the decompressed `btc_daily_dataset.json.gz` and matched the JSON report and all three trial manifests.
- Generated UTC: 2026-11-20T18:23:39.568658Z.
- Source: public Coinbase BTC-USD hourly spot aggregated into complete UTC daily bars; 36,000 hourly source bars, 1,499 daily bars, 13 hourly observations explicitly imputed and disclosed.
- Daily interval: 2022-10-13T00:00:00Z through 2026-11-19T00:00:00Z; chronological 70/30 split at daily index 1,049; 450 daily OOS bars.
- The manifest records exactly three declared lookbacks (56/84/112 days), not a global experiment census. Protocol: three fixed chronological OOS subperiods; not rolling walk-forward.
- Execution remains completed daily-close signal, next daily-close fill; 25% maximum allocation; 0.10% fee and 0.05% slippage per side. Costs are fixed proxies, not venue-specific spread/depth/impact.

| Lookback | OOS 1x | OOS 2x | OOS 3x | Max close-to-close DD | Closed-trade PF | Closed trades | 95% block-bootstrap CI | Top-1 winner share |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 56 days | -2.6896% | -3.7718% | -4.8403% | 7.5257% | 0.6474 | 15 | [-15.5019%, +13.7127%] | 89.3424% |
| 84 days | -7.8404% | -8.3058% | -8.7681% | 10.2742% | 0.0214 | 7 | [-19.4569%, +4.4709%] | 100.0000% |
| 112 days | -11.6508% | -12.4832% | -13.3064% | 14.1759% | 0.0401 | 13 | [-23.1984%, +1.4525%] | 41.7121% |

- Matched 25%-allocation buy-and-hold OOS return: -11.1290% at 1x, -11.17% at 2x, and -11.21% at 3x (rounded stress values from the report).
- The 56-day candidate's three OOS subperiods were -4.7928%, -2.5588%, and +4.8931%; only the final slice was positive. The 84-day slices were -0.7699%, -4.3247%, and -2.9273%; the 112-day slices were -1.8367%, -5.1065%, and -5.1545%.
- The 56-day candidate had four winning trades; its top winner contributed 89.3424% of gross winning P&L and its top five contributed 100%. Net P&L excluding the top five winners was -$76.2787. The 84-day candidate had one winning trade, which contributed 100% of gross winning P&L. These are fragility diagnostics, not alternate performance estimates.
- CSCV/PBO was 0.50 across only the three declared variants, six partitions, ten splits, and 75 observations per partition. It is not a future-profit probability and does not restore an untouched holdout.
- All three lookbacks remain negative at 1x/2x/3x. The 56-day candidate is less negative than the matched benchmark in this sample but still loses absolutely, has only 15 closed trades, PF below 1, concentrated winners, and a bootstrap interval spanning material losses and gains.

**Decision: NO CANDIDATE PROMOTED.** This is historical OOS evidence only, not rolling walk-forward and not forward paper-trading evidence. The artifact explicitly reports `live_orders=false` and `paper_ledgers_read_or_written=false`; no paper or live execution was invoked.
