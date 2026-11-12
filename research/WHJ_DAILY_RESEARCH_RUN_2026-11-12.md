# WHJ daily research execution record — 2026-11-12

## Gold research run

- Workflow run: [43140755962](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43140755962)
- Conclusion: success
- Artifact: `whj-xauusd-gold-1` (artifact ID `13908339917`), SHA-256 `e7fe2bc3dfa12a3007c65e7facc66a546d9ea12b8d064d496a599a07d45eb9b6`
- Source: Yahoo Finance `GC=F`, continuous COMEX gold-futures reference; 2,513 daily candles from 2016-11-14 to 2026-11-10.
- Dataset SHA-256: `5094275e1b53b40559eb347bfbe3b26d8881fefea23e552128b146252afe6557`
- Validation steps: gold data/strategy/shadow-runner tests passed; historical fold evaluation passed; report artifact uploaded.

### Gold result and decision

The EMA50/EMA200 + past-only ATR90 filter returned +0.59%, +3.32%, and +0.10% in the three chronological OOS folds at 1x cost, versus matched 25%-allocation buy-and-hold returns of +1.72%, +16.55%, and +6.61%. At 2x cost, the filtered strategy returned +0.22%, +3.02%, and -0.26%, still below the matched benchmark in every fold. At 3x cost, it returned -0.14%, +2.72%, and -0.62%.

**Decision: reject promotion.** The tested gold candidates failed to outperform the matched buy-and-hold benchmark in all three folds. Trade counts are also small (7, 7, and 9 filtered-strategy closed trades), so the evidence is insufficient for a reliable performance claim.

Limitations: `GC=F` is not spot XAU/USD or a broker feed. The fixed fee/slippage assumptions do not model actual spread, swap/financing, market impact, broker markup, or session differences. These results are historical research, not future-profit evidence.

## Bitcoin research run

- Workflow run: [43140750323](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/43140750323)
- Status at record creation: in progress; no BTC result is claimed.
- The workflow evaluates 17 declared BTC signal candidates using public Coinbase BTC-USD hourly data, a 70/30 chronological split, matched buy-and-hold, 1x/2x/3x cost stress, trial manifests, CSCV/PBO where sample constraints permit, and block-bootstrap uncertainty for the five descriptive leaders.
- Promotion status remains `NO_CANDIDATE_PROMOTED`.

## Safety

- No live orders or broker credentials.
- No existing BTC or production paper ledger was read or written by the historical BTC/Gold evaluators.
- No candidate promoted.
- PR #122 remains open and draft; no merge performed.
