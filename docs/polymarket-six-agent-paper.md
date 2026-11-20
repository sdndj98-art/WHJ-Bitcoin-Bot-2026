# WHJ Six-Agent Order-Book Strategy (Paper Research)

## Status

This is a pure, deterministic, paper-only research module. It is not connected to a Polymarket wallet, live order API, or persistent paper portfolio. It does not claim the reported PnL in the social post is verified.

Module: \`polymarket_six_agent_paper.py\`

## Six roles

1. **PULSE** — computes a top-level bid/ask depth imbalance for UP and DOWN outcomes. Empty outcome books are skipped; if both are unavailable, the pipeline returns HOLD.
2. **IMPACT** — fits a simple ordinary least squares model from historical pairs of imbalance and subsequent exit-bid changes. Fewer than 20 samples means HOLD. This baseline is not a validated forecasting model.
3. **EDGE** — compares expected exit bid to entry ask, subtracting round-trip costs and a configurable buffer.
4. **SIZE** — limits quantity by risk budget / stressed adverse move, visible ask depth, collateral, and configured quantity cap.
5. **ENTRY** — simulates taking available asks up to the calculated maximum entry price. Partial remainder is treated as canceled. No live order is sent.
6. **EXIT** — provides paper close triggers for pressure reversal, risk stop, or maximum holding horizon; PnL uses average prices and supplied total costs.

## Safety

- \`live_trading_enabled = false\`
- \`orders_submitted = false\`
- No credentials or private keys are read.
- No existing WHJ BTC/gold paper ledger is modified.
- Bad, empty, or insufficient data fails closed to HOLD.

## Important model limitations

The social post does not define all queue fields, calibration windows, event-time handling, fee calculation, slippage model, or exact pressure-reversal rule. This implementation makes those assumptions explicit and must not be treated as a reproduction of the account's proprietary strategy.

The current WHJ multi-market scanner uses crypto OHLCV and provider metal quotes. Those are not equivalent to Polymarket binary-outcome CLOB snapshots. A separate public Polymarket market-data adapter, historical order-book recorder, and event-resolution paper simulator are required before meaningful backtesting. Polymarket API access and eligibility must be checked separately before any future live trading work.

## Run unit tests

\`\`\`bash
python -m unittest tests.test_polymarket_six_agent_paper -v
\`\`\`

The module can also be imported directly for deterministic unit tests using synthetic order books and historical samples.
