# WHJ Six-Agent Paper Signal Engine

The `six_agent_signal_engine.py` module provides a deterministic, rule-based
six-agent signal ensemble for research and paper testing.

## Agents

- **SCANNER** — short/long moving-average alignment.
- **MOMENTUM** — 5-bar price change.
- **MEAN_REVERSION** — 20-bar standardized deviation.
- **BREAKOUT** — close beyond the previous 20-bar high/low.
- **VOLUME** — direction confirmed by elevated volume.
- **RISK** — vetoes entries when average recent high-low range exceeds the configured limit.

The five directional agents vote BUY, SELL, or HOLD. A directional result requires
at least 3 of 5 votes and at least 60% of all directional agents. Otherwise the
result is HOLD. The risk agent can always force HOLD.

## Python usage

```python
from six_agent_signal_engine import analyze_market, analyze_universe

# Each symbol requires at least 25 recent OHLCV bars.
report = analyze_market(bars)
signal = report["signal"]  # BUY / SELL / HOLD

reports = analyze_universe({"BTCUSD": bars, "XAUUSD": gold_bars})
signals = {symbol: result["signal"] for symbol, result in reports.items()}
```

Bars must be chronological dictionaries with finite `close`, `high`, and
`low`; `volume` is optional and defaults to zero. Use broker-provided,
time-aligned candle history. Do not mix timeframes or use incomplete candles
without explicitly accounting for them.

## Paper safety

This module is a deterministic heuristic, not an AI model and not a profit
guarantee. It does not fetch prices or place orders. Its output must be combined
with fresh quote validation, broker contract metadata, currency conversion,
market health checks, position sizing, and risk limits in
`multi_asset_paper.py`. Missing or invalid history returns HOLD through
`analyze_universe`.

WHJ remains paper-only: `live_trading_enabled=False` and
`orders_submitted=False`. Do not connect this signal output to a live order
endpoint.
