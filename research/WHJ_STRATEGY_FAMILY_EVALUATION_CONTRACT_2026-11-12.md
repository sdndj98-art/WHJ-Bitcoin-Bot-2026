# Common Evaluation Contract for the Expanded BTC Signal Library

Date: 2026-11-12
Branch: research/global-evidence-strategy-lab-20261112

`strategy_family_evaluator.py` adds a common, isolated evaluator for long/flat candidate signal streams. It uses a strict timing contract: signal observed at completed close t, exposure changes at open t+1, and the measured return interval is open t+1 to open t+2. Turnover costs are charged at the next open. A matched buy-and-hold stream uses the same intervals and an initial entry cost.

Metrics include net return, close-to-close equity drawdown over the evaluator's open-to-open return stream, period Sharpe with an explicit bars-per-year assumption, profit factor, exposure, turnover, closed round trips and whether a position remains open. Raw strategy and benchmark net return streams are returned for later uncertainty and multiple-testing analysis.

Limitations: the evaluator does not model intrabar stops, spread, order-book depth, market impact, latency, partial fills, funding, borrow, or liquidation. Its drawdown is not the OHLC intrabar envelope produced by `ohlc_execution_lab.py`. Profit factor is based on periodic net returns, not closed-trade P&L. The returned `excess_return` is the difference between terminal equity multiples, not a percentage-point excess-return statistic.

Only signals with identical timestamps and matching data coverage may be compared. Do not compare candidates on mismatched samples. The evaluator is not connected to paper ledgers, order routes, or the dashboard's trading controls. It makes no promotion decision and does not claim profitability.