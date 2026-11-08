# Candle-aligned CVD research diagnostic

`cvd_candle_research.py` aligns public Kraken aggressor-side trade events with
completed OHLCV candle intervals. It reports per-bar signed volume, normalized
delta, directional confirmation, and simple absorption-divergence diagnostics.

## Safety and data-integrity contract

- The caller must pass `continuity_verified=True` only when the collector has
  independently recovered every trade-ID gap for the relevant interval.
- Without that explicit assertion, every bar is unavailable and no flow
  confirmation can pass.
- Bars with too few trades or a last trade too far from the candle close are
  unavailable; missing events are never synthesized.
- Trade timestamps must be timezone-aware ISO-8601 or Unix seconds.
- Candle inputs must be contiguous, UTC-aligned completed Kraken OHLCV rows.
- This is a diagnostic alignment layer, not a strategy backtest. It does not
  promote scanner candidates, modify paper ledgers, read order-book depth, or
  place orders.

## Example

```python
from cvd_candle_research import align_trade_flow_to_candles

report = align_trade_flow_to_candles(
    closed_ohlcv_rows,
    normalized_trade_events,
    interval_seconds=3600,
    continuity_verified=collector_gap_recovery_verified,
)
for bar in report["bars"]:
    print(bar["status"], bar["delta_pct"],
          bar["bullish_flow_confirmation"])
```

A subsequent research phase must replay timestamp-aligned trade history,
compare baseline and CVD-filtered strategies on identical chronological
holdouts, include fees/slippage, and report coverage attrition before any
candidate is considered for forward paper review.
