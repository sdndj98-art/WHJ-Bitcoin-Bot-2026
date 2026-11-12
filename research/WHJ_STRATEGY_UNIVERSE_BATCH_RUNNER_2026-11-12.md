# WHJ Strategy Universe Batch Runner

`strategy_family_runner.py` now evaluates all 17 currently implemented signal candidates with one shared call and one shared protocol. Every candidate uses the same candle rows, completed-close signal, next-open exposure change, following open-to-open return interval, fee/slippage assumptions, and matched buy-and-hold sample.

The returned ranking is descriptive only and sorted by terminal excess equity. It is not a robust ranking: it does not account for uncertainty, multiple testing, sample sufficiency, regime stability, parameter sensitivity, independent venues, or an untouched final holdout. It never promotes a candidate.

The runner remains disconnected from paper ledgers and all execution paths. Do not interpret a synthetic fixture test as market performance.