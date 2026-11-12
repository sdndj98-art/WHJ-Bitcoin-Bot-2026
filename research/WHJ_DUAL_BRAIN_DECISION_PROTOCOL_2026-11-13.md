# WHJ Dual-Brain Decision Protocol — 2026-11-13

## Status

Research-only design specification. This protocol does not create a second independent model provider, execute orders, mutate paper ledgers, or promote strategies. The current office has one optional xAI/Grok adapter and deterministic Python workers. Bull/Bear roles run as adversarial review stages within that bounded workflow; they are not statistically independent models.

## Purpose

Require every proposed BTC or gold paper-trade thesis to survive an explicit opposing case and a separate risk gate. BTC and gold are evaluated independently. A market regime label is context, never a trade signal by itself.

## Decision sequence

1. **Bull case (thesis author):** identify instrument and exact data source; state regime and timestamp; give one causal setup; cite exact repository/data evidence; define entry trigger, invalidation, stop, target/exit logic, expected holding period, and estimated costs. If any required input is unavailable, mark UNKNOWN.
2. **Bear case (adversarial reviewer):** assume the Bull thesis is wrong. Identify regime misclassification, contradictory evidence, stale/partial candles, look-ahead, survivorship/selection bias, spread/slippage/financing omissions, event risk, and benchmark weakness. It must provide a concrete falsification condition, not generic caution.
3. **Risk Judge (independent gate):** check data freshness and integrity, completed-bar timing, next-bar execution, position sizing, stop distance, gap risk, fee/slippage stress, portfolio exposure, daily loss and drawdown guards, and whether the paper engine can execute the exact proposed action safely.
4. **Decision:** exactly one of ACCEPT_FOR_PAPER_TEST, REJECT, WAIT_FOR_DATA, or BLOCKED. Acceptance only permits a bounded paper test; it is not evidence of profitability and never authorizes live trading.
5. **Logger:** persist the two theses, citations, timestamp, dataset fingerprint, code commit, costs, risk checks, decision, and reason. Duplicate inputs must be idempotent.

## Evidence requirements

- Use only timestamped, traceable data for the relevant instrument. Do not treat COMEX GC=F futures as spot XAUUSD.
- Signals use completed candles only; execution is no earlier than the next available bar/event.
- Bull and Bear claims must cite exact source paths and excerpts or immutable dataset/artifact identifiers.
- Numeric performance claims require a reproducible report and matching benchmark; no invented fills, prices, win rates, or P&L.
- Report trade count, net return after costs, max drawdown, longest losing streak, exposure, worst month, and uncertainty.
- Evaluate chronologically with walk-forward / untouched holdout. Do not tune on the final holdout.
- Include base and stressed fees, spread, slippage, and financing where applicable. Unknown costs block a promotion claim.
- A small sample, one lucky trade, or an attractive equity curve is not sufficient evidence.

## Hard safety rules

- Paper-only. No exchange/broker order endpoints or live credentials.
- Bull/Bear disagreement never bypasses the Risk Judge.
- Missing or stale market data means WAIT_FOR_DATA or BLOCKED, never a guessed value.
- Risk Judge cannot increase risk limits or alter the paper ledger.
- No automatic code merge, candidate promotion, or switch to live trading.
- A passing decision means only "eligible for controlled paper observation"; it does not mean profitable.

## Current implementation boundary

The existing WHJ office already provides strategy, red-team, risk, QA, and safety roles plus a bounded optional Grok worker. In the first implementation stage, the Bull case is produced by the relevant strategy specialist, the Bear case by the red-team reviewer, and the Risk Judge by the risk/safety review stages. These are separate prompts/tasks but currently share the same optional Grok model when enabled; therefore correlated model error remains possible. The free worker only inventories files and runs deterministic syntax/readability checks.

A genuinely independent second brain requires a separately configured provider/model, a separate budget and credentials boundary, explicit provider identity in the run report, and tests showing that its output cannot see or simply echo the first model's conclusion. Do not claim this exists until implemented and verified.

## Promotion gate

No candidate can be promoted unless it passes:
1. data-lineage and causal-timing checks;
2. independent Bull/Bear review with resolved material objections;
3. risk and execution-cost stress tests;
4. multiple chronological out-of-sample folds and matched benchmarks;
5. adequate trade count and uncertainty analysis;
6. forward-only paper monitoring with no duplicate or historical backfill trades;
7. human review of the complete evidence bundle.

Until all gates pass, the published status remains NO_CANDIDATE_PROMOTED.
