# WHJ Profitability Development Program

## Objective
Keep the research office cycling through market-data validation, candidate research, strategy QA, paper-engine QA, risk review, and evidence review until a candidate has enough independent evidence for human review. The objective is positive cumulative net paper PnL with controlled drawdown, not a guaranteed profit promise.

## Research loop
- Daily historical opportunity research for BTC and XAUUSD using the existing fixed-rule strategy lab.
- Evaluate candidates at normal and 2x transaction-cost assumptions.
- Reject candidates without at least 30 OOS closed trades, positive net OOS at both cost levels, drawdown no greater than 8%, and all three walk-forward windows positive at both cost levels.
- A historical pass means only ELIGIBLE FOR FORWARD PAPER REVIEW. It does not mean a strategy is successful or ready for live trading.
- The shared $100 paper portfolio and multi-market paper workflow remain separate evidence sources. Never infer candidate-level profitability from a combined wallet result.

## Forward evidence required before a success label
A candidate must be evaluated in a separate, untouched forward-only paper ledger, with fees and slippage applied, at least 100 closed forward trades (or a longer sample if needed), positive cumulative net PnL, profit factor above 1.2, maximum drawdown below 10%, and no unresolved data-quality, duplicate-order, or risk-guard failures. Review across different market regimes and instruments. If the sample is too small or results fail, continue paper collection or reject the candidate.

## Governance
- No guaranteed profit, fabricated market data, look-ahead, or optimization on the final forward sample.
- No automatic strategy promotion, weakening risk limits, wallet reset, or real orders.
- Reports and test failures are evidence for the next development cycle; GitHub Actions runs are best-effort and may be delayed.
- Human review is required before any change to the shared paper portfolio strategy; live trading is outside this program.
