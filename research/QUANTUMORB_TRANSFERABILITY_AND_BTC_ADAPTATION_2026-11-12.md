# QuantumOrb Transferability Audit and BTC Research Adaptation

Date: 2026-11-12
Target branch: research/global-evidence-strategy-lab-20261112
Status: research design only; no strategy, paper ledger, risk limit, schedule, or execution path changed.

## Executive decision

QuantumOrb is a Solana / pump.fun token due-diligence and holder-distribution scanner, not a BTC trading strategy. Its score describes distribution cleanliness and selected rug-risk factors; it is not a calibrated probability of future appreciation. Its reported launch counts and example multiple are claims from the supplied post and are not independently verified here.

Do not port its 0-100 score, wallet thresholds, creator graduation tests, or token launch filters into BTC strategy selection. Doing so would mix incompatible market structures and create false precision.

The transferable idea is the architecture: separate discovery, provenance/risk screening, participant concentration, liquidity stress, hard vetoes, and a transparent verdict. For WHJ, adapt only the market-microstructure concepts that can be measured from BTC data.

## Source review

Reviewed the public QuantumOrb repository and its published scoring, Guard/Shield, and architecture documents:
- https://github.com/QuantumOrb/QuantOrb
- https://github.com/QuantumOrb/QuantOrb/blob/main/docs/scoring.md
- https://github.com/QuantumOrb/QuantOrb/blob/main/docs/guard.md
- https://github.com/QuantumOrb/QuantOrb/blob/main/docs/architecture.md

The public repository describes itself as a Solana memecoin holder scanner. It says roughly one tenth of the operational code is open; the live launch stream, wallet-link discovery, scan orchestration, server and bot infrastructure remain closed. Its public rules combine top-holder concentration, wallet freshness, transfers, early snipers, linked operators, creator history, launch-slot buying, developer holdings, owner powers and liquidity control.

The documentation also states important limitations: wallets are not people; unlinked wallets cannot be inferred to share an owner; unavailable data must not be treated as a pass; a clean score is not a promise; liquidity and off-chain information may be outside the scan.

## Transferability matrix

| QuantumOrb concept | BTC/WHJ analogue | Decision |
|---|---|---|
| RADAR: new launches and curve progress | Market regime / volatility / breakout event detector | Adapt concept, not token-launch logic |
| SHIELD: creator launch history | Strategy/data-source provenance and exchange quality checks | Use as research governance, not a BTC alpha signal |
| SCANNER: first buyers and holder histories | Trade-flow imbalance, aggressive buy/sell volume, CVD and volume participation | Adapt only where timestamped trade data exists |
| CARTOGRAPHER: linked wallet operators | No reliable equivalent from ordinary centralized-exchange OHLCV; exchange trade IDs rarely identify beneficial owners | Do not infer participant identities |
| GUARD: developer concentration and owner powers | Exchange/venue concentration, order-book depth, spread, liquidity withdrawal/outage and data integrity | Adapt as venue/liquidity risk checks |
| ORB: weighted score plus hard red flags | Transparent research eligibility report with separate alpha and risk dimensions | Do not compress into one opaque profit score |

## Proposed WHJ research-only module

Create an isolated BTC market-quality and flow-risk evaluator, separate from signal generation and all paper-account code.

Inputs:
- Completed, timestamped public BTC trades and/or order-book snapshots where available.
- Existing OHLCV only as a lower-confidence fallback.
- Venue identity, source timestamp, receive timestamp, sequence/gap diagnostics, and data freshness.

Candidate measurements:
1. Aggressive buy/sell volume imbalance over fixed, predeclared horizons.
2. Cumulative volume delta (CVD) slope and divergence against price.
3. Trade-size concentration and volume participation; label these as prints/flow concentration, never as unique trader or wallet concentration.
4. Spread, quoted depth, and conservative estimated liquidation impact at fixed hypothetical notionals, only when valid order-book data exists.
5. Volatility-conditioned liquidity deterioration and gap/stale-feed flags.
6. Venue disagreement and source freshness; do not combine venues without explicit normalization and timestamp alignment.

Hard data/risk vetoes:
- Missing, stale, out-of-order, or materially gapped inputs.
- Inconsistent timestamps or unverified candle completion.
- Missing order-book depth when an impact estimate is requested.
- Venue outage / abnormal spread / depth collapse.
- Any unavailable feature is UNKNOWN, never silently zero or PASS.

Output:
- Separate alpha_context, flow_quality, liquidity_risk, data_quality, and eligibility fields.
- Every metric includes its source, window, timestamp, units, and confidence/availability.
- No universal 0-100 score until weights and thresholds are calibrated on training data and evaluated on untouched chronological data.
- No trade recommendation; this module may only annotate isolated research reports.

## Validation plan

1. Unit tests for timestamp alignment, completed-bar causality, duplicate/out-of-order trades, missing intervals, stale order books, zero/negative depth, and venue normalization.
2. Synthetic tests proving that unavailable data returns UNKNOWN and never a clean pass.
3. Replay on historical BTC data with a frozen specification; no tuning on the final holdout.
4. Compare each feature alone and as a predeclared ablation against the current BTC candidate and matched buy-and-hold.
5. Test incremental value after fees, spread, slippage, participation and conservative market-impact stress.
6. Report performance by volatility/liquidity regime and independent venue.
7. Require forward-only paper observation after historical gates; never use a flow score to bypass existing safety gates.

## Explicit non-goals

- No Solana/pump.fun scanner added to the BTC bot.
- No wallet clustering or attribution claims from centralized-exchange BTC data.
- No live orders, API keys, real funds, or Telegram.
- No changes to existing paper ledgers, risk limits, schedules, or dashboard execution controls.
- No PR merge or strategy promotion.

## Research conclusion

The strongest lesson from QuantumOrb is not its numeric thresholds. It is the separation of signal discovery from structural-risk screening, evidence-backed hard flags, and honest UNKNOWN states. WHJ should adopt that discipline through BTC trade-flow and liquidity-quality research, while keeping its strategy evaluation independent and falsifiable.