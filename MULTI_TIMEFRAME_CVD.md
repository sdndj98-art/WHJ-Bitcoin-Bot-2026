# Multi-timeframe CVD research

The multi-timeframe layer is implemented in `multi_timeframe_cvd.py`. It can
analyze the supported chart intervals below using the same normalized Kraken
aggressor-side trade batch:

| Label | Seconds |
|---|---:|
| 1s | 1 |
| 5s | 5 |
| 15s | 15 |
| 30s | 30 |
| 1m | 60 |
| 2m | 120 |
| 3m | 180 |
| 5m | 300 |
| 10m | 600 |
| 15m | 900 |
| 30m | 1800 |
| 45m | 2700 |
| 1h | 3600 |

## Data requirements

- Supply completed, contiguous OHLCV candles separately for every timeframe.
- Supply normalized raw trades covering the relevant candle windows.
- Supply an independent continuity-verification boolean for every timeframe.
- Missing or unverified timeframes are marked unavailable and do not vote.
- Sub-minute candles (1s through 30s) must be constructed from timestamped
  trade events using deterministic UTC interval boundaries. Kraken's standard
  OHLC REST endpoint does not provide one-second candles.
- Each timeframe's candle series must have its own valid interval boundaries.
  A shared trade batch must fall within the candle coverage for every supplied
  timeframe; otherwise the base alignment validator rejects the batch.

## Consensus

Each available timeframe contributes BULLISH, BEARISH, or NEUTRAL based on
flow confirmation and absorption-divergence diagnostics. The default consensus
requires at least 60% directional agreement among available frames. Conflicting
or insufficient votes produce MIXED; zero verified frames produce UNAVAILABLE.
Unavailable frames never count as neutral votes.

This is an analysis layer only. It does not change scanner scores, authorize
orders, or claim profitability. Before strategy use, build a timestamped replay
dataset, compare baseline and filtered signals on identical chronological
holdouts, account for fees/slippage and data-coverage attrition, and run
walk-forward and paper-forward validation.
