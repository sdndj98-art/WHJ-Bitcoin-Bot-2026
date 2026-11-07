# WHJ Bitcoin Bot 2026

A read-only BTC/USD hourly market-analysis project. It retrieves public Kraken OHLC data, excludes the still-forming candle, calculates SMA20/SMA50, and reports a simple BUY / SELL / HOLD indicator.

## Safety
- **Paper / analysis only:** no real orders are submitted.
- No exchange API keys or trading secrets are needed.
- Signals are educational indicators, not financial advice or guaranteed profitable strategies.
- Do not enable real-money trading without a separately reviewed implementation, risk controls, and explicit authorization.

## Run locally
Requires Python 3.10 or newer. No third-party packages are required.

```bash
python -m unittest discover -s tests -v
python main.py
```

A successful run prints the analysis and writes `report.json`.

## Automated schedule
GitHub Actions runs the tests and analysis hourly at minute 7 (UTC), and can also be started manually from the Actions tab. Each successful run uploads `report.json` as an artifact retained for 14 days.

## Indicator
- BUY when latest closed price > SMA20 > SMA50.
- SELL when latest closed price < SMA20 < SMA50.
- HOLD otherwise.

This is a basic trend filter, not a complete trading strategy. It does not model fees, slippage, execution, portfolio sizing, or risk of loss.
