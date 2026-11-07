# WHJ Bitcoin Bot 2026

A read-only BTC/USD hourly analysis, historical paper-backtesting, and reporting project. It retrieves public Kraken OHLC data, excludes the still-forming candle, calculates SMA20/SMA50, reports a BUY / SELL / HOLD indicator, and simulates a simple long-only strategy on historical candles.

## Safety
- **No real trading:** the program never submits exchange orders.
- No exchange API keys or trading secrets are needed.
- Historical results are not forecasts, guarantees, or financial advice.
- The simulator starts with a hypothetical $1,000 USD, models a 0.1% fee and 0.05% slippage per execution, and uses next-candle close execution to reduce look-ahead bias.
- This is a basic educational model, not a complete strategy. It does not model order-book depth, partial fills, exchange outages, taxes, or all market risks.

## Run locally
Requires Python 3.10 or newer. No third-party packages are required.

```bash
python -m unittest discover -s tests -v
python main.py
python dashboard.py
```

A successful run prints the analysis and writes `report.json`. The dashboard generator creates a self-contained `dashboard.html`.

## Optional Telegram notifications
Create two GitHub Actions repository secrets:
- `TELEGRAM_BOT_TOKEN`: token from BotFather.
- `TELEGRAM_CHAT_ID`: destination chat ID.

If both secrets exist, each successful analysis sends a concise report. Without them, the Telegram step is skipped. Never put tokens in source code, commits, or workflow text.

## Automated schedule
GitHub Actions runs tests and analysis on pushes to `main`, hourly at minute 7 (UTC), and when manually started from the Actions tab. Each run uploads `report.json` and `dashboard.html` as an artifact retained for 14 days. The optional Telegram step is skipped safely unless both repository secrets are configured.

## Indicator
- BUY when latest closed price > SMA20 > SMA50.
- SELL when latest closed price < SMA20 < SMA50.
- HOLD otherwise.

The backtest uses the same SMA20/SMA50 trend rule, evaluates a signal using the prior 50 completed candles, and simulates execution at the following candle close.
