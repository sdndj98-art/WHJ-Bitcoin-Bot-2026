# EMA50/EMA200 + ADX research review — 2026-11-08

## Scope and safety

This note records the completed, boundary-aligned historical research on the 50/50 portfolio split across native 4h and 6h EMA50/EMA200 sleeves. It is research only: no live orders were enabled and no existing paper ledger was read, reset, or modified by these jobs.

The walk-forward folds use shared UTC 12-hour completed-bar close boundaries, so neither timeframe is split inside a native candle. Each test fold starts independently with $1,000; fold returns are **not compounded** into a continuous portfolio return.

## Fixed-threshold out-of-sample results

| Strategy | Return | Closed trades | Win rate | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|
| EMA baseline | +7.22% | 98 | 29.59% | 1.42 | 7.45% |
| ADX15 entry-only | +9.53% | 58 | 32.76% | 1.77 | 6.51% |
| ADX20 entry-only | +7.77% | 54 | 25.93% | 1.56 | 7.70% |
| ADX25 entry-only | +4.16% | 44 | 22.73% | 1.28 | 10.35% |
| Matched 50/50 buy-and-hold | +2.28% | — | — | — | 20.09% |

Execution assumptions: 0.10% fee and 0.05% slippage per side; completed native bars; entry confirmation only; an open position remains until the baseline EMA regime turns off; next native-bar close execution.

## Elevated-cost stress

At twice the base costs (0.20% fee and 0.10% slippage per side):

| Strategy | Return | Profit factor | Max drawdown |
|---|---:|---:|---:|
| EMA baseline | +3.35% | 1.17 | 9.62% |
| ADX15 entry-only | +7.16% | 1.52 | 7.16% |
| ADX20 entry-only | +5.60% | 1.37 | 8.40% |
| ADX25 entry-only | +2.44% | 1.15 | 11.17% |

## Independent Bitstamp replication

The independent BTCUSD Bitstamp dataset contained 72,000 hourly candles from 2018-08-22 19:00 UTC through 2026-11-08 18:00 UTC. The fixed-threshold results above replicated on this separate exchange feed. This is a useful robustness check, but it is still historical testing and not forward-paper evidence.

Three descriptive fixed-rule subperiods show that ADX15 returned +7.06%, +0.43%, and +1.80%; ADX20 returned +7.18%, -0.42%, and +0.97%. These are descriptive OOS slices, not rolling retraining.

## Boundary-aligned expanding-window walk-forward

Threshold choice used only the expanding training window before each test fold. The fixed training score was return minus half maximum drawdown; ADX20 was the predeclared fallback. The report confirms no same-fold test feedback.

| Fold | Selected threshold | Selected return | Baseline return | Benchmark return | Selected 2x-cost return |
|---|---:|---:|---:|---:|---:|
| 1 | ADX25 | +5.26% | +6.14% | +4.96% | +4.54% |
| 2 | ADX20 | -0.41% | +1.09% | +2.66% | -1.15% |
| 3 | ADX20 | +0.97% | +0.58% | -4.10% | +0.40% |

Fold 2 is a material weakness: the training-only selector chose ADX20, but the selected strategy lost money and underperformed both baseline and matched benchmark. Fold 3 was positive and beat baseline, but its return was small. These results argue against automatic promotion based only on the fixed-threshold aggregate.

## Current research decision

- Keep **ADX20** as the predeclared primary candidate for isolated forward-paper observation.
- Keep **ADX15** as a research comparator, not the production default; it has stronger aggregate and independent-exchange historical results, but was explored among thresholds and therefore carries selection-bias risk.
- Do not promote ADX25; its fixed-threshold return and drawdown were weaker.
- Do not use these historical figures as evidence of live profitability.
- Require genuine forward-only paper observations, with separate ADX15/ADX20 and 4h/6h ledgers, before any strategy qualification decision. Existing EMA paper ledgers remain untouched.
- The isolated ADX forward-paper workflow has not been bootstrapped or verified as running on the default branch. No forward trades are claimed in this note.

## Independent Bitstamp expanding-window walk-forward replication

A second walk-forward run applied the identical expanding-window selector and shared UTC 12-hour fold boundaries to 72,000 Bitstamp BTCUSD hourly candles (2018-08-22 19:00 UTC through 2026-11-08 18:00 UTC). This is a separate exchange-data replication of the selection process, not merely the fixed-threshold comparison.

| Fold | Selected threshold | Selected return | Baseline return | Benchmark return | Selected 2x-cost return |
|---|---:|---:|---:|---:|---:|
| 1 | ADX25 | +4.71% | +5.49% | +4.96% | +4.00% |
| 2 | ADX20 | -0.42% | +1.10% | +2.65% | -1.16% |
| 3 | ADX20 | +0.97% | +0.69% | -4.11% | +0.40% |

The same weakness reproduced on the independent exchange: fold 1 selected ADX25 but trailed both baseline and benchmark; fold 2 selected ADX20 and lost money, trailing both; only fold 3 modestly beat baseline. The similarity of fold outcomes across feeds is a useful warning against promoting the selector, not proof of future behavior. This independent replication materially strengthens the conclusion that the current adaptive ADX selector is **not qualified for promotion**.

## Updated decision after independent walk-forward

- Keep the EMA50/EMA200 baseline as the control strategy.
- Retain ADX20 only as the predeclared isolated forward-paper candidate; ADX15 remains a comparator, not a production default.
- Do not deploy the adaptive threshold selector or promote ADX25.
- Before reconsidering promotion, require forward-only paper evidence across enough market regimes and at least 30 closed forward trades per sleeve, with cost stress and benchmark comparison. The 30-trade threshold is a minimum review gate, not a guarantee of statistical confidence.
- No forward-paper run has been bootstrapped; no forward trades are claimed. Existing EMA paper ledgers remain untouched.

## Latest reproducibility

- Primary boundary-aligned research and independent Bitstamp walk-forward both completed successfully in workflow run `42516038074` (artifact `whj-ema-adx-research-71`).
- The same workflow completed successfully on the pull request in run `42516043530` (artifact `whj-ema-adx-research-72`).
- The independent fixed-threshold Bitstamp validation completed successfully in run `42516043586`.
- Latest source commit at the time of this update: `979917a4c59a227478b444af8b4dfcd41256a4f6`.

## Reproducibility

Research workflow run: `42513865324` (completed successfully; artifact `whj-ema-adx-research-66`).

Independent Bitstamp workflow run: `42513865303` (completed successfully; artifact `whj-ema-adx-cross-exchange-44`).

The outputs were generated from feature branch commit `4be3f46b72d881ea35f1ea17bd399c881f1de3e3`. All figures are rounded as shown; consult the JSON artifacts for full precision and metadata.
