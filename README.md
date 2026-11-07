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
Each hourly workflow run processes only newly closed candles for four independent simulated accounts:
- SMA20/SMA50 trend
- EMA12/EMA26 trend
- RSI momentum with EMA trend confirmation
- SMA200 long-term regime filter

Each account starts with hypothetical $1,000, uses 25% allocation, models 0.1% fees and 0.05% slippage, and keeps a separate trade ledger. The workflow stores account state in GitHub Actions cache so later runs can continue from the previous processed candle. Cache retention is managed by GitHub and is not a permanent database; review artifacts and account state periodically.

Risk controls pause new entries after a 3% daily loss and permanently pause an account after a 10% peak-to-trough drawdown until manual review. A loss guard can liquidate an open simulated position. These limits are safeguards, not guarantees against losses.

## Automated schedule
GitHub Actions runs tests and analysis on pushes to `main`, hourly at minute 7 (UTC), and when manually started from the Actions tab. Each successful run uploads `report.json` and `dashboard.html` as an artifact retained for 14 days. Telegram notifications are currently disabled.

## Indicator
- BUY when latest closed price > SMA20 > SMA50.
- SELL when latest closed price < SMA20 < SMA50.
- HOLD otherwise.

The backtest uses the same SMA20/SMA50 trend rule, evaluates a signal using the prior 50 completed candles, and simulates execution at the following candle close.
