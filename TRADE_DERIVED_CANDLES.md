# Trade-derived multi-timeframe candles

trade_candle_builder.py constructs completed OHLCV candles from normalized Kraken trade events. This is the required path for 1-second through 30-second bars; it can also construct larger intervals from the same feed.

```python
from trade_candle_builder import build_trade_candles
from multi_timeframe_cvd import analyze_multi_timeframe_cvd

now = 1794132000.5  # caller supplies a trusted UTC Unix timestamp
candles_by_frame = {}
trades_by_frame = {}
continuity_by_frame = {}

for label, seconds in {
    "1s": 1, "5s": 5, "15s": 15, "30s": 30,
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600,
}.items():
    built = build_trade_candles(normalized_trades, seconds, now)
    candles_by_frame[label] = built["candles"]
    trades_by_frame[label] = built["trades"]
    # Set True only from independently verified feed cursor/gap recovery.
    continuity_by_frame[label] = feed_integrity_verified_for_this_window

report = analyze_multi_timeframe_cvd(
    candles_by_frame, trades_by_frame, continuity_by_frame
)
```

## Candle rules

- UTC interval boundaries are deterministic; a trade exactly on a boundary belongs to the new candle.
- The current still-forming interval is excluded, even if it contains trades.
- OHLC, VWAP, volume, and trade count are derived only from included trades.
- Empty interior intervals are represented by a flat carry-forward candle with zero volume and zero trades. No volume is invented.
- Input trades must be timestamp ordered and have unique positive integer IDs, positive price/quantity, and a buy/sell aggressor side.
- Each timeframe gets its own trade subset because the latest completed interval ends at a different boundary for each timeframe.
- The builder does not recover dropped events or certify continuity. The separate feed adapter must prove gap recovery before a timeframe is allowed to vote in the consensus.

## Research boundary

This builder and the CVD consensus are diagnostics only. They do not change scanner scores, authorize MT5 or exchange orders, or establish profitability. The next validation stage is replay against timestamped historical trades, chronological holdouts, realistic fees/slippage, coverage attrition, and forward paper monitoring.
