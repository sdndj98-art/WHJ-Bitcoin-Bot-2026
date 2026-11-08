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
)

trade_batch = fetch_recent_trades("XBTUSD")
book_snapshot = fetch_order_book("XBTUSD", count=100)

flow = analyze_trade_flow(trade_batch["trades"])
depth = analyze_order_book(book_snapshot, levels=20)
context = combine_microstructure(flow, depth)

print(flow["net_delta"], flow["batch_bias"])
print(depth["spread_bps"], depth["depth_imbalance"])
print(context["context"])
```

## Metrics

- Trade flow: aggressive buy volume, aggressive sell volume, signed batch delta, buy-volume ratio, trade VWAP, and batch time bounds.
- Order book: best bid/ask, spread in basis points, visible bid/ask notional depth, depth imbalance, and largest visible level share.
- Combined context: agreement, disagreement, or neutral/mixed conditions between the recent trade batch and the single depth snapshot.

## Important semantics

- `net_delta` is the signed volume delta of the exact supplied batch. It is **not** persistent cumulative CVD.
- Persistent CVD requires incremental cursor ingestion, durable last-trade cursor storage, trade-ID deduplication, reconnect recovery, and explicit handling of gaps and out-of-order events. Do not sum overlapping API batches.
- Order-book depth is one venue-specific snapshot. It can change or be cancelled; it does not prove resting liquidity will remain available or identify spoofing.
- Kraken trade-side labels represent the exchange's aggressor-side classification. They do not describe the entire crypto market.
- Volume and depth values are venue-specific and cannot be assumed to match other exchanges or MT5 tick volume.

## Safety and integration

This module uses only Kraken public `Trades` and `Depth` endpoints. It contains no private API credentials, order submission, cancellation, position management, or live execution. It is not imported into `main.py` or the existing scanner until data-quality, latency, cursor recovery, and forward paper behavior have been independently reviewed.

The output is research context only, not an entry signal or profitability claim. Before any scanner integration, add replay tests, stale-data handling, rate-limit/backoff policy, cross-source timestamp alignment, and out-of-sample evaluation.
