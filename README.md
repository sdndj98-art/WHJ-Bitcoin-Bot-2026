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

## Persistent paper portfolio
Each hourly workflow run processes newly closed candles for five independent simulated accounts:
- SMA20/SMA50 trend
- EMA12/EMA26 trend
- RSI momentum with EMA trend confirmation
- SMA200 long-term regime filter
- EMA50/EMA200 long-term regime filter

A separate daily research workflow also maintains four multi-timeframe paper ledgers: daily SMA20/SMA50, 4-hour EMA50/EMA200, daily Bollinger mean reversion, and 6-hour RSI14 mean reversion. These are separate from the hourly portfolio and must not be combined when comparing results.

Each account starts with hypothetical $1,000, uses 25% allocation, models 0.1% fees and 0.05% slippage, and keeps a separate trade ledger. The workflow stores account state in GitHub Actions cache so later runs can continue from the previous processed candle. Cache retention is managed by GitHub and is not a permanent database; review artifacts and account state periodically.

Risk controls pause new entries after a 3% daily loss and permanently pause an account after a 10% peak-to-trough drawdown until manual review. A loss guard can liquidate an open simulated position. Recent missing hourly candles or stale market data also block paper execution. These limits are safeguards, not guarantees against losses.

## Automated schedule
GitHub Actions runs tests and hourly analysis on pushes to `main`, hourly at minute 7 (UTC), and when manually started. A separate five-year BTC/USD historical research job runs daily at 06:37 UTC and when relevant research files change. Hourly analysis artifacts are retained for 14 days; historical research reports are retained for 30 days. Telegram notifications are currently disabled.

## Indicator
- BUY when latest closed price > SMA20 > SMA50.
- SELL when latest closed price < SMA20 < SMA50.
- HOLD otherwise.

The backtest uses the same SMA20/SMA50 trend rule, evaluates a signal using the prior 50 completed candles, and simulates execution at the following candle close.

## Five-year strategy research
The research workflow downloads public Coinbase BTC-USD hourly candles, validates OHLCV data, and evaluates fixed-rule strategies on hourly, 4-hour, 6-hour, and daily bars. It uses chronological in-sample/out-of-sample splits, additional out-of-sample windows, and a higher-fee/slippage stress scenario. The current leading research candidate is daily Bollinger mean reversion, but its out-of-sample sample is small; it remains experimental and is not approved for live trading. Historical and paper results are not forecasts or guarantees.
