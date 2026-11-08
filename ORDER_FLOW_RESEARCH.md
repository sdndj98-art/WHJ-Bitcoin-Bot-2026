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
- The `KrakenSpotTradeFeedAdapter` converts public Spot WebSocket v2 trade envelopes into ledger events and detects missing per-symbol trade IDs. It attempts REST `Trades` backfill from the last exact nanosecond timestamp before applying a later WebSocket update. The caller still owns the socket, subscription, heartbeat, reconnect loop, and atomic state persistence.
- Persistent CVD requires incremental cursor ingestion, durable last-trade cursor storage, trade-ID deduplication, reconnect recovery, and explicit handling of gaps and out-of-order events. Do not sum overlapping API batches.
- Order-book depth is one venue-specific snapshot. It can change or be cancelled; it does not prove resting liquidity will remain available or identify spoofing.
- Kraken trade-side labels represent the exchange's aggressor-side classification. They do not describe the entire crypto market.
- Volume and depth values are venue-specific and cannot be assumed to match other exchanges or MT5 tick volume.

## Safety and integration

This module uses only Kraken public market data: REST `Trades`/`Depth` and the caller-supplied public Spot WebSocket v2 trade channel. It contains no private API credentials, order submission, cancellation, position management, or live execution. It is not imported into `main.py` or the existing scanner until data-quality, latency, cursor recovery, and forward paper behavior have been independently reviewed.

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


## Kraken Spot WebSocket v2 CVD adapter

The public Spot v2 `trade` channel sends trade objects with `symbol`, `side`, `qty`, `price`, `trade_id`, and an ISO-8601 `timestamp`. Pass decoded envelopes to the adapter; no private token is needed for this public channel.

```python
from kraken_order_flow import PersistentCvdLedger, KrakenSpotTradeFeedAdapter

# Restore this JSON object from your own durable store on process startup.
saved_state = None
ledger = PersistentCvdLedger(symbol="BTC/USD", state=saved_state)
feed = KrakenSpotTradeFeedAdapter(ledger, pair="BTC/USD")

# In your WebSocket receive loop:
# message = websocket.recv()
# result = feed.handle_message(message)
# if result["status"] == "OK":
#     atomically_save_json(ledger.to_state())
```

The adapter validates each event, rejects non-monotonic timestamps, deduplicates replayed IDs, and fails closed on trade-ID gaps. It attempts to recover missing trades through the public REST `Trades` endpoint, requiring the REST response's seventh trade-row field to contain the exchange trade ID; it will not synthesize IDs from timestamps or prices. Exact nanosecond timestamps are retained in the serialized state for restart recovery.

Operational constraints:
- Persist `ledger.to_state()` atomically after every successful update; store it separately per symbol.
- If a gap cannot be recovered within the configured page cap, stop consuming that stream and alert the operator; do not treat the CVD as continuous.
- The adapter does not implement the socket itself, reconnect policy, rate-limit backoff, or process supervision.
- On first start, the initial WS snapshot establishes a baseline only; historical completeness before that snapshot is not claimed.
- This remains a read-only research feed and cannot send or manage orders.
