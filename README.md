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
GitHub Actions runs tests and hourly analysis on pushes to `main`, hourly at minute 7 (UTC), and when manually started. A separate extended-history BTC/USD historical research job runs daily at 06:37 UTC and when relevant research files change. Hourly analysis artifacts are retained for 14 days; historical research reports are retained for 30 days. Telegram notifications are currently disabled.

## Browser dashboard

A responsive Arabic command-center dashboard is available in `web/index.html`. It displays the latest generated paper-analysis report, market signal, simulated portfolio metrics, strategy comparison, trade log, risk diagnostics, and market-data quality. The hourly GitHub Actions workflow packages the page together with `report.json` and publishes it to GitHub Pages on the `main` branch. The dashboard refreshes its report every 60 seconds. Before the first deployment, a repository administrator must enable GitHub Pages once in Settings → Pages → Build and deployment → Source → GitHub Actions. The workflow then publishes the site after successful hourly analysis; if Pages is not enabled or GitHub denies setup permissions, the bot analysis still completes and website deployment is skipped. The dashboard is read-only and does not submit exchange orders.

## Regime-aware consensus ensemble

The strategy lab also evaluates a long-only consensus candidate that gives equal weight to three strategy families rather than allowing the eight overlapping trend filters to dominate by count: trend (at least 4 of 8 filters), RSI momentum (active confirmation), and mean reversion (at least 2 of 3 rules). The ensemble enters only when at least two families agree. It is evaluated as its own strategy using the same chronological holdout, three non-overlapping walk-forward windows, 25% allocation, fees, slippage, and elevated-cost stress review. It is not assumed to be successful: it must independently pass every existing qualification gate before it can be considered for extended forward paper review. Component strategies and separate OHLC breakout / long-short / daily-regime labs remain separately reported because their signals and market bars are not interchangeable.

## Monte Carlo trade-risk diagnostics

The hourly report includes a seeded bootstrap resampling of the completed historical paper-backtest trade PnL. It reports median and tail final-equity scenarios, loss frequency, and maximum-drawdown percentiles across 2,000 resampled sequences. This is a diagnostic only: it assumes IID trade outcomes, keeps the trade count fixed, uses additive historical PnL, and does not model serial dependence, regime changes, or future execution. It is not a forecast, does not establish an edge, and must never override the fixed strategy qualification gates. A second circular moving-block bootstrap diagnostic samples short contiguous sequences of trade outcomes to test sensitivity to local ordering. Its default block length is three trades. This can preserve limited short-run ordering, but cannot reliably estimate dependence from a small sample and is not a forecast.

## MetaTrader 5 (MT5) connector

An optional read-only MT5 adapter is available for broker-provided instruments such as BTCUSD, XAUUSD, and FX pairs (exact symbols depend on the broker). It attaches to an already configured MetaTrader 5 desktop terminal, reads sanitized account/broker status, validated bid/ask quotes, and completed OHLCV candles. The adapter starts candle retrieval at MT5 bar position 1 to exclude the still-forming candle. Setup and usage are documented in [MT5_SETUP.md](MT5_SETUP.md). Run `python mt5_snapshot.py --symbol BTCUSD --update-paper-ledger` on the Windows terminal host, then import `mt5_snapshot.json` into the dashboard MT5 tab. The snapshot runs the WHJ scanner on 1h/4h/6h broker candles and can update five local virtual BTC paper accounts; private broker/account balances are excluded from the snapshot.

**Platform note:** the official MetaTrader5 Python package requires a supported Windows environment with the MT5 terminal. It cannot run directly inside Android Termux or the Linux-hosted GitHub Actions workflow. Keep Termux's existing crypto analysis workflow unchanged; use a Windows workstation/VPS for the MT5 connector.

**Safety boundary:** this integration is read-only and paper-data-only. It contains no order submission or position-closing method, does not store account passwords, and does not enable real trading. A future execution adapter must be a separate reviewed change with demo-account validation, broker-specific volume/stop checks, duplicate-order protection, reconciliation, and explicit live-trading safeguards. Broker permission to trade does not mean WHJ is permitted to send orders.

## Indicator
- BUY when latest closed price > SMA20 > SMA50.
- SELL when latest closed price < SMA20 < SMA50.
- HOLD otherwise.

The backtest uses the same SMA20/SMA50 trend rule, evaluates a signal using the prior 50 completed candles, and simulates execution at the following candle close.

## Extended historical strategy research
The research workflow downloads approximately 8.2 years of public Coinbase BTC-USD hourly candles when that interval is complete and available, validates OHLCV data, and evaluates fixed-rule strategies on hourly, 4-hour, 6-hour, and daily bars. It uses chronological in-sample/out-of-sample splits, additional out-of-sample windows, and a higher-fee/slippage stress scenario. The OHLC breakout lab tests a pre-defined 3×20-bar ATR trailing-close exit alongside Donchian exits, plus a combined SMA200 regime gate with the same ATR exit; it also replays fixed signals at 1×, 1.5×, 2×, and 3× fee/slippage assumptions against a matched 25%-allocation buy-and-hold benchmark; the stop is evaluated only on completed closes and simulated at the following close, with the same costs and qualification gates. No strategy is treated as a winner merely because it ranks first. The qualification report is the source of truth for current pass/fail status; strategies that fail any gate remain experimental and are not approved for live trading. Historical and paper results are not forecasts or guarantees. Each research run publishes both `historical_research.json` (machine-readable metrics) and `strategy_qualification_report.md` (human-readable pass/fail gates and failure reasons). Qualification is applied consistently to hourly/multi-timeframe, OHLC breakout, long/short research, and daily-regime labs. Long/short results remain hypothetical research only and are not connected to an exchange.

### Genuine forward-only paper ledgers

The legacy paper accounts above are historical backfills with persistent risk guards; they are useful diagnostics but are not a clean forward-performance record. Separate 4h and 6h EMA50/200 ledgers now seed their indicator state from the latest fully closed candles without generating historical trades or PnL. Their starting capital is $500 per sleeve, with 10% sleeve-equity allocation per entry, a 10% maximum-drawdown pause, a 3% daily-loss pause, and a five-consecutive-loss pause. After seeding, only newly completed candles are processed on scheduled runs. Existing legacy ledgers are not reset or overwritten. No live orders are sent.

The forward health review also tracks the latest 20 closed trades in each sleeve. Once at least 10 trades are available, a non-positive rolling net result, rolling profit factor below 1.0, or peak-to-trough drawdown of at least 8% of that sleeve's initial simulated capital marks the sleeve for review. The rolling drawdown is displayed in the browser dashboard and the hourly workflow summary. The same 8% rolling drawdown threshold is enforced inside the paper ledger: after at least 10 closed trades, it persistently pauses new entries for that sleeve and liquidates any open paper position on the next processed candle. The pause requires manual review/reset. This is a conservative paper-only safeguard, not an exchange action and not a replacement for the existing 10% account drawdown, 3% daily-loss, or consecutive-loss safeguards.

### Qualified 4h / 6h EMA50/200 portfolio candidate

The extended-history lab evaluates the 4-hour and 6-hour EMA50/200 regime strategies separately and as a 50/50 capital-weighted portfolio. Each sleeve runs on its own native completed-bar schedule, starts with $500 of a $1,000 simulated portfolio, and allocates 25% of its own available cash per entry. The combined maximum initial notional is therefore 25% of total portfolio capital. Portfolio drawdown is calculated from synchronized sleeve equity curves, not by averaging individual drawdowns.

The latest contiguous 3,000-day research run (72,000 closed hourly candles through 2026-11-07 17:00 UTC) found the 50/50 blend eligible for extended forward paper review: 7.61% out-of-sample return, 98 closed trades, 1.45 profit factor, 7.51% maximum drawdown, and 3.72% return under elevated fees/slippage. The standalone 4h EMA50/200 sleeve returned 7.75% out of sample (60 trades, 1.39 profit factor, 8.46% drawdown; +3.00% under elevated costs), while the 6h sleeve returned 7.47% (38 trades, 1.53 profit factor, 8.20% drawdown; +4.43% under elevated costs). The genuine forward-only 4h/6h ledger is tracked separately from legacy historical backfills; at the time of that report it had just been seeded, with 0 forward trades and $1,000 simulated equity. It outperformed the matched 25%-allocation buy-and-hold benchmark in both cost scenarios and had non-negative returns in all three walk-forward windows. This is historical qualification only, not proof of future profitability or authorization for live trading. Two separate $500 persistent paper ledgers now track the 4h and 6h sleeves; their drawdowns are reported separately in the paper report.

### Strategy promotion policy
A strategy is only eligible for extended forward paper review when it passes all fixed gates: at least 30 out-of-sample closed trades, positive out-of-sample and elevated-cost stress returns, profit factor of at least 1.2, out-of-sample maximum drawdown no greater than 10%, and non-negative returns in all three chronological out-of-sample windows. In addition, both the normal-cost and elevated-cost out-of-sample returns must strictly outperform a matched 25%-allocation buy-and-hold BTC benchmark; missing benchmark data is an automatic failure. Passing is only eligibility for extended forward paper review, not a live-trading approval. If no strategy passes, the correct result is to keep all strategies in research/paper mode rather than force a winner.


## Harmonic patterns and supply/demand divergence

The hourly report also includes a research-only diagnostic for approximate Gartley, Bat, Butterfly, Crab, and Cypher XABCD patterns; pivot-derived supply/demand zones; and bullish/bearish RSI14 divergence. Only confirmed swing pivots from closed candles are used. These are descriptive research signals, not verified institutional order flow, forecasts, or order instructions. The analysis is separate from the existing scanner score and does not enable live execution.


## Guarded MT5 demo execution prototype

A separate manual demo-only order gateway is documented in [MT5_DEMO_EXECUTION.md](MT5_DEMO_EXECUTION.md). It requires two explicit opt-ins, a positively identified MT5 demo account, mandatory stop-loss/take-profit, broker constraint validation, and a local idempotency guard. It is not connected to the scanner or dashboard and does not support live accounts.


## Optional Kraken CVD market-data collector

The optional collector connects to Kraken's **public** Spot WebSocket v2 trade channel, maintains a per-symbol cumulative volume delta (CVD), and saves its cursor/volume state locally. It is separate from the scanner and paper/live execution paths.

Install its optional transport dependency:

```bash
python -m pip install websocket-client
```

Start the BTC/USD collector:

```bash
python kraken_cvd_collector.py --pair BTC/USD
```

Choose a custom state file or another pair:

```bash
python kraken_cvd_collector.py --pair ETH/USD --state-file state/eth_usd_cvd.json
```

Stop with Ctrl+C. The collector uses atomic JSON state replacement and resumes from the saved trade ID/timestamp. If it cannot recover a trade-ID gap, it stops/retries rather than silently claiming a continuous CVD series. The first WebSocket snapshot establishes a baseline; it does not claim historical completeness before startup.

The collector is read-only: no API key is required, and it cannot place, amend, or cancel orders. It does not alter the main bot's scanner, MT5 integration, or any paper portfolio. To run multiple symbols, start one process and one state file per symbol. The generated `dashboard.html` also reads the default BTC/USD CVD state file and labels it fresh, stale, clock-skewed, or unavailable; custom state paths are not auto-discovered by the dashboard.

### Multi-timeframe CVD replay

To retain the accepted raw trades for later replay, start the collector with its bounded JSONL journal enabled:

```bash
python kraken_cvd_collector.py --pair BTC/USD --trade-log state/kraken_btc_usd_trades.jsonl --max-trade-log-mb 250
```

In another Termux session (or after stopping the collector), build native trade-flow bars:

```bash
python cvd_timeframes.py --trade-log state/kraken_btc_usd_trades.jsonl --output state/kraken_cvd_timeframes.json
```

The replay produces 1s, 5s, 15s, 30s, 1m, 3m, 5m, 15m, 30m, 1h, 4h, 6h, 12h and 1d bars with OHLC, buy/sell volume, delta, cumulative CVD, closed-bar status and missing-interval flags. Empty intervals are not fabricated. The CVD history begins at the first event retained in the journal; it is venue-specific and is not a consolidated-market signal or a trading instruction.


## XAU/USD gold research (separate from BTC)

The research branch includes an isolated daily gold study for Yahoo Finance's `XAUUSD=X` spot-reference series. It validates daily OHLC data, drops the final potentially incomplete candle, fingerprints the dataset, and compares the same fixed EMA50/EMA200 and past-only ATR-volatility filter under three chronological out-of-sample folds. Signals execute at the next daily open; the OHLC simulator applies a 25% allocation cap, fixed 2% stop / 4% target, stop-first collision handling, and 1x/2x/3x fee-and-slippage sensitivity. Cash and a matched 25%-allocated buy-and-hold baseline are included.

This is a **separate gold research track**, not a claim that BTC parameters transfer to gold. Yahoo's XAUUSD=X is a spot-price reference series, not a broker bid/ask feed; costs are proxies and do not include actual broker spread, commission, overnight swap/financing, markup, or market impact. For broker-specific live quotes or paper monitoring, the existing optional MT5 adapter can read broker symbols such as `XAUUSD` (exact suffix varies), but it is read-only and its BTC paper-ledger update is deliberately blocked for non-BTC symbols. The gold workflow does not access or modify existing paper ledgers and never sends orders.
