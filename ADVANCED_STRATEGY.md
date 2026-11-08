# WHJ Advanced Volume, Liquidity & Momentum Layer

This module adds an independent diagnostic layer; it does not silently change the existing scanner's qualification score or promote a strategy to live trading.

## Python

```python
from advanced_market_analysis import analyze_advanced_market

# Pass completed OHLCV rows using the repository's 8-column format:
# [timestamp, open, high, low, close, unused, volume, trade_count]
result = analyze_advanced_market(completed_candles)
print(result["status"], result["bullish_score"], result["bearish_score"])
```

The analyzer reports relative volume (current volume / mean of the prior 20 bars), CMF(20), normalized recent OBV slope, rolling 20-bar volume-weighted typical price, prior rolling swing extremes, liquidity sweep/reclaim events, break of structure, ATR-normalized candle displacement, MACD(12,26,9), and RSI(14). All references are causal and use no future bars. Exclude the still-forming candle before calling it.

A sweep (wick beyond a prior extreme and close back inside) and a BOS (close beyond that extreme) are different events and cannot both occur on the same side on the same candle. The score is out of nine. A research candidate requires at least six confirmations, a sweep or BOS, and either CMF or OBV confirmation. Long and short diagnostics are separate.

## TradingView

Open `tradingview/whj_advanced_confluence.pine` in Pine Editor, add it to a chart, and use confirmed-bar alerts only. The Pine script is an indicator, not a strategy/order executor. Its rolling volume-weighted typical price is an approximation named Rolling VWAP 20, not session VWAP.

## Interpretation and limitations

- Relative volume and all volume-derived features are vendor-dependent. MT5 often provides tick volume; that is not centralized traded volume.
- A rolling swing high/low is only a proxy for a possible liquidity pool. OHLCV candles cannot reveal actual resting orders, stop orders, spoofing, or order-book depth.
- CMF/OBV/VWAP do not prove institutional accumulation or distribution.
- Thresholds (RVOL 1.5, CMF ±0.05, OBV normalized slope ±0.05, displacement 0.8 ATR, score 6/9) are initial research parameters, not optimized or qualified parameters.
- The Python analyzer is independently tested; Pine uses corresponding formulas but has not been compiler-validated by TradingView in CI.
- Compare the old scanner and this layer on identical chronological data. Require out-of-sample trade-count sufficiency, walk-forward stability, elevated fee/slippage stress, benchmark outperformance, and forward-only paper tracking before any promotion.
- This module does not connect to `mt5_demo_executor.py`, does not generate orders, and does not enable live trading.
