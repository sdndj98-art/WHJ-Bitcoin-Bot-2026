# XAUUSD broker-feed research contract — 2026-11-13

## Decision and scope

The existing GC=F historical path is a continuous COMEX gold-futures reference series, not broker spot XAUUSD. Keep its results labelled as futures-proxy research. Do not relabel it as spot performance and do not reuse BTC's fee/slippage constants as if they represented a gold broker.

This branch now has a separate, research-only ingestion and cost-accounting contract:

- xauusd_broker_data.py
- tests/test_xauusd_broker_data.py
- .github/workflows/gold-xauusd-daily-research.yml runs the new contract tests independently of the existing GC=F historical test suite.

No broker connection, credentials, order routing, paper ledger, or live execution is used.

## Required broker export

The CSV schema is deliberately strict and requires:

- symbol = XAUUSD (or XAU/USD)
- timeframe_minutes
- timezone-aware timestamp_utc representing the bar-open time
- bid_open, bid_high, bid_low, bid_close
- ask_open, ask_high, ask_low, ask_close

The parser rejects another symbol such as GC=F, mismatched timeframe, naive timestamps, duplicate/out-of-order bars, crossed quotes, impossible OHLC, and bars outside the supplied broker session. It preserves the raw CSV SHA-256, reports spread in basis points, records observed timestamp gaps, and never imputes missing bars or silently drops out-of-session rows.

## Broker session calendar

A caller must supply the broker's actual UTC schedule:

- weekly open weekday and UTC minute
- weekly close weekday and UTC minute
- daily rollover/break intervals
- broker-declared closed dates

Bars that overlap daily breaks or cross weekly open/close boundaries are rejected. A static UTC schedule is valid only for one broker daylight-saving regime; split historical exports at DST transitions and validate each segment with its corresponding UTC schedule. The module does not infer broker DST, holidays, early closes, or session exceptions.

## Broker-specific execution and cost model

The explicit cost model requires:

- contract size in ounces per lot
- commission in USD per lot per side
- adverse slippage in basis points per side
- signed long and short swap in USD per ounce per rollover
- broker's triple-swap weekday
- USD quote currency

Round-trip accounting uses ask for a long entry and bid for a long exit; the short side uses bid entry and ask exit. Actual bid/ask spread is embedded in those executable prices and separately reported as a diagnostic (not subtracted twice). Slippage, two-sided commission, and date-specific rollover financing are reported independently. Triple rollover is applied only on the broker-declared weekday. This is an accounting helper, not a broker execution simulator or an order function.

## Verified existing GC=F evidence

Artifact: [run 43208411769](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43208411769), artifact whj-gc-f-gold-13.

- Yahoo Finance GC=F, daily, 2,514 bars, 2016-11-14 through 2026-11-11.
- Dataset SHA-256: 6b1561ab63f51393cfed9f3930f36f081f9558521b169448272bf31ed086c9b1.
- Three chronological OOS folds: 2022-05-13–2023-11-10, 2023-11-13–2025-05-13, and 2025-05-14–2026-11-11.
- EMA50/EMA200 plus the past-only ATR90 filter produced +0.5878%, +3.3208%, and +0.0987% at 1x costs, versus matched 25% buy-and-hold of +1.7192%, +16.5489%, and +6.3797%.
- At 2x costs the candidate returned +0.2235%, +3.0204%, and -0.2634%; at 3x it returned -0.1390%, +2.7211%, and -0.6239%.
- The ATR-filtered candidate closed 23 trades across the three folds; the baseline EMA candidate closed 11. The ATR candidate underperformed matched buy-and-hold in every fold and remains below the 30-trade screening gate.

These are GC=F futures-reference results, not XAUUSD spot results. The historical workflow's fixed fee/slippage percentages do not model broker spread, swap, financing, markup, liquidity, market impact, or broker-specific session/holiday rules. No candidate is promoted.

## Validation and blockers

- Local isolated contract test run: 10 tests passed against the committed module/test design.
- Existing GC=F workflow run 43208411769: all four test groups passed (4 + 4 + 9 + 3 = 20 tests), historical evaluation completed, artifact uploaded.
- The latest workflow revision adds the XAUUSD contract test to the gold workflow. A completed GitHub Actions result for that new revision has not yet been verified; do not report it as CI-green.
- No broker-exported XAUUSD bid/ask dataset, broker session calendar, contract-size specification, commission schedule, slippage observations, or long/short swap schedule is present in the repository. Therefore no XAUUSD spot backtest, strategy ranking, or forward result is claimed.

## Next research step

Obtain a non-secret broker-exported XAUUSD bid/ask OHLC sample plus its contract, session, commission, and swap specification. Validate the source and DST-specific session segments first. Only then build a separate XAUUSD OHLC evaluator with next-bar execution, spread-aware fills, slippage/commission/swap accounting, matched cash and buy-and-hold baselines, chronological OOS folds, and 1x/2x/3x cost stress. Keep the entire path disconnected from all paper and live order systems.
