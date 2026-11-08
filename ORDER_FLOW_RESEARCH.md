# WHJ Kraken Order-Flow Research Layer

This optional module adds read-only microstructure diagnostics from Kraken's public market-data endpoints. It is deliberately separate from the existing scanner and execution adapters.

## Quick start

```python
from kraken_order_flow import (
    fetch_recent_trades,
    fetch_order_book,
    analyze_trade_flow,
    analyze_order_book,
    combine_microstructure,
    evaluate_microstructure_confluence,
)

trade_batch = fetch_recent_trades("XBTUSD")
book_snapshot = fetch_order_book("XBTUSD", count=100)

flow = analyze_trade_flow(trade_batch["trades"])
depth = analyze_order_book(book_snapshot, levels=20)
context = combine_microstructure(flow, depth)

# Optional: fuse completed OHLCV analysis with the trade batch and depth.
from advanced_market_analysis import analyze_advanced_market
ohlcv = analyze_advanced_market(closed_candles)
confluence = evaluate_microstructure_confluence(ohlcv, flow, depth)

print(flow["net_delta"], flow["batch_bias"])
print(depth["spread_bps"], depth["depth_imbalance"])
print(context["context"])
print(confluence["context"])
```

## Metrics

- Trade flow: aggressive buy volume, aggressive sell volume, signed batch delta, buy-volume ratio, trade VWAP, and batch time bounds.
- Order book: best bid/ask, spread in basis points, visible bid/ask notional depth, depth imbalance, and largest visible level share.
- Combined context: agreement, disagreement, or neutral/mixed conditions between the recent trade batch and the single depth snapshot.

## Important semantics

- `net_delta` is the signed volume delta of the exact supplied batch. It is **not** persistent cumulative CVD.
- `PersistentCvdLedger` accepts incremental uniquely identified trade events, accumulates buy/sell volume, ignores replayed/stale IDs, and exports JSON-serializable state through `to_state()` for caller-managed durable storage.
- The CVD ledger does not open a websocket, write files, or guarantee gap-free ingestion. A feed adapter must restore state, resume from the last trade ID, recover missed events after reconnect, and atomically persist updated state.
- Persistent CVD requires incremental cursor ingestion, durable last-trade cursor storage, trade-ID deduplication, reconnect recovery, and explicit handling of gaps and out-of-order events. Do not sum overlapping API batches.
- Order-book depth is one venue-specific snapshot. It can change or be cancelled; it does not prove resting liquidity will remain available or identify spoofing.
- Kraken trade-side labels represent the exchange's aggressor-side classification. They do not describe the entire crypto market.
- Volume and depth values are venue-specific and cannot be assumed to match other exchanges or MT5 tick volume.

## Safety and integration

This module uses only Kraken public `Trades` and `Depth` endpoints. It contains no private API credentials, order submission, cancellation, position management, or live execution. It is not imported into `main.py` or the existing scanner until data-quality, latency, cursor recovery, and forward paper behavior have been independently reviewed.

The output is research context only, not an entry signal or profitability claim. Before any scanner integration, add replay tests, stale-data handling, rate-limit/backoff policy, cross-source timestamp alignment, and out-of-sample evaluation.


## Three-layer confluence diagnostic

`evaluate_microstructure_confluence(ohlcv_analysis, trade_flow, order_book)` combines:
1. Completed-bar OHLCV direction from the existing advanced market analysis output.
2. Aggressor-side buy/sell pressure from one public trade batch.
3. Visible bid/ask depth, spread and top-level concentration from one order-book snapshot.

The default liquidity-quality gates are a maximum 15 bps spread, at least 100,000 quote-currency units of visible notional depth, and no single level exceeding 65% of its side depth. These are configurable research defaults, not universal market thresholds.

The output distinguishes three-layer alignment, partial confirmation, divergence, and liquidity-quality failure. It always returns `execution_enabled: false` and `timestamp_alignment_verified: false`. The caller must explicitly align candle close time, trade timestamps and local order-book capture time before interpreting the result. It is not connected to the scanner or order execution.


## Persistent CVD ledger

```python
from kraken_order_flow import PersistentCvdLedger

ledger = PersistentCvdLedger(symbol="BTC/USD")
result = ledger.process([
    {"symbol": "BTC/USD", "trade_id": 101, "price": "100", "qty": "0.2",
     "side": "buy", "timestamp": "2026-11-08T09:00:00Z"},
    {"symbol": "BTC/USD", "trade_id": 102, "price": "99", "qty": "0.1",
     "side": "sell", "timestamp": "2026-11-08T09:00:01Z"},
])
state_to_save = ledger.to_state()  # Persist atomically in the caller.
print(result["cumulative_delta"], result["cumulative_bias"])

# On restart: restore the saved state, then resume the feed after last_trade_id.
restored = PersistentCvdLedger(state=state_to_save)
```

The ledger validates IDs, sides, prices, quantities and timestamps; deduplicates replayed IDs; rejects conflicting IDs and out-of-order new timestamps atomically; and reports that continuity depends on adapter-managed reconnect recovery.
