"""Read-only Kraken trade-flow and order-book microstructure diagnostics.

This module consumes Kraken public Trades and Depth payloads. It does not
place orders, maintain a persistent CVD ledger, or infer hidden liquidity.
"""
import json
import math
import urllib.parse
import urllib.request


KRAKEN_PUBLIC_URL = "https://api.kraken.com/0/public"


def _finite_number(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric, not boolean")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _extract_pair_result(result):
    if not isinstance(result, dict):
        raise ValueError("Kraken response result must be an object")
    keys = [key for key in result if key != "last"]
    if len(keys) != 1:
        raise ValueError("Expected exactly one Kraken pair result")
    return result[keys[0]]


def _kraken_get(endpoint, params, timeout=10):
    if endpoint not in ("Trades", "Depth"):
        raise ValueError("Only public Trades and Depth endpoints are allowed")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be positive")
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{KRAKEN_PUBLIC_URL}/{endpoint}?{query}",
        headers={"User-Agent": "WHJ-Order-Flow-Research/1.0",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Kraken response must be a JSON object")
    errors = payload.get("error") or []
    if not isinstance(errors, list):
        raise ValueError("Kraken response error field must be a list")
    if errors:
        raise RuntimeError("Kraken API error: " + ", ".join(map(str, errors)))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Kraken response result must be an object")
    return result


def fetch_recent_trades(pair="XBTUSD", timeout=10):
    """Fetch a recent public trade batch; returned delta is batch-scoped."""
    if not isinstance(pair, str) or not pair or len(pair) > 32:
        raise ValueError("pair must be a non-empty Kraken pair identifier")
    result = _kraken_get("Trades", {"pair": pair}, timeout=timeout)
    pair_rows = _extract_pair_result(result)
    if not isinstance(pair_rows, list):
        raise ValueError("Kraken Trades payload must contain a trade list")
    return {"trades": pair_rows, "last": result.get("last")}


def fetch_order_book(pair="XBTUSD", count=100, timeout=10):
    """Fetch one public order-book snapshot; it is not historical depth."""
    if not isinstance(pair, str) or not pair or len(pair) > 32:
        raise ValueError("pair must be a non-empty Kraken pair identifier")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 500:
        raise ValueError("count must be an integer from 1 to 500")
    result = _kraken_get("Depth", {"pair": pair, "count": count}, timeout=timeout)
    book = _extract_pair_result(result)
    if not isinstance(book, dict):
        raise ValueError("Kraken Depth payload must contain an order-book object")
    return book


def analyze_trade_flow(trades):
    """Calculate aggressive buy/sell volume for one supplied trade batch.

    Kraken public Trades rows use [price, volume, time, side, orderType, misc].
    The returned net_delta is a batch delta, not a persistent cumulative CVD.
    """
    if not isinstance(trades, (list, tuple)) or not trades:
        raise ValueError("trades must be a non-empty list")
    buy_volume = 0.0
    sell_volume = 0.0
    total_notional = 0.0
    total_volume = 0.0
    buy_count = 0
    sell_count = 0
    timestamps = []
    seen_ids = set()

    for row in trades:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise ValueError("Each Kraken trade must contain at least six fields")
        price = _finite_number(row[0], "trade price")
        volume = _finite_number(row[1], "trade volume")
        timestamp = _finite_number(row[2], "trade timestamp")
        side = row[3]
        if price <= 0 or volume <= 0 or timestamp < 0:
            raise ValueError("Trade price/volume must be positive and timestamp non-negative")
        if side not in ("b", "s"):
            raise ValueError("Kraken trade side must be 'b' or 's'")
        if len(row) > 6 and row[6] not in (None, ""):
            trade_id = str(row[6])
            if trade_id in seen_ids:
                raise ValueError("Duplicate trade id in supplied batch")
            seen_ids.add(trade_id)

        if side == "b":
            buy_volume += volume
            buy_count += 1
        else:
            sell_volume += volume
            sell_count += 1
        total_volume += volume
        total_notional += price * volume
        timestamps.append(timestamp)

    delta = buy_volume - sell_volume
    delta_pct = delta / total_volume if total_volume > 0 else 0.0
    buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.0
    if delta_pct >= 0.10:
        bias = "BUY_PRESSURE"
    elif delta_pct <= -0.10:
        bias = "SELL_PRESSURE"
    else:
        bias = "BALANCED"

    return {
        "status": "OK",
        "trade_count": len(trades),
        "buy_trade_count": buy_count,
        "sell_trade_count": sell_count,
        "buy_volume": round(buy_volume, 12),
        "sell_volume": round(sell_volume, 12),
        "total_volume": round(total_volume, 12),
        "net_delta": round(delta, 12),
        "net_delta_pct": round(delta_pct * 100.0, 4),
        "buy_volume_ratio": round(buy_ratio, 6),
        "trade_vwap": round(total_notional / total_volume, 10),
        "first_trade_timestamp": min(timestamps),
        "last_trade_timestamp": max(timestamps),
        "batch_bias": bias,
        "metric_scope": "supplied_trade_batch_only",
        "is_persistent_cvd": False,
        "limitations": [
            "This is the signed volume delta for the supplied batch, not a persistent cumulative CVD series.",
            "A cumulative series requires cursor-based incremental ingestion, durable trade-id deduplication and gap recovery.",
            "Aggressor-side labels reflect the exchange feed and are not a complete view of all venues.",
        ],
    }


def analyze_order_book(book, levels=20):
    """Measure visible depth and spread from one order-book snapshot."""
    if not isinstance(book, dict):
        raise ValueError("book must be an object")
    if isinstance(levels, bool) or not isinstance(levels, int) or levels < 1:
        raise ValueError("levels must be a positive integer")
    bids = book.get("bids")
    asks = book.get("asks")
    if not isinstance(bids, (list, tuple)) or not bids:
        raise ValueError("book must contain at least one bid")
    if not isinstance(asks, (list, tuple)) or not asks:
        raise ValueError("book must contain at least one ask")

    def normalize(rows, side):
        output = []
        for row in rows[:levels]:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise ValueError(f"Malformed {side} level")
            price = _finite_number(row[0], f"{side} price")
            volume = _finite_number(row[1], f"{side} volume")
            if price <= 0 or volume <= 0:
                raise ValueError(f"{side} price and volume must be positive")
            output.append((price, volume))
        if not output:
            raise ValueError(f"No usable {side} levels")
        prices = [price for price, _ in output]
        if side == "bid" and any(a <= b for a, b in zip(prices, prices[1:])):
            raise ValueError("Bid levels must be strictly descending")
        if side == "ask" and any(a >= b for a, b in zip(prices, prices[1:])):
            raise ValueError("Ask levels must be strictly ascending")
        return output

    bid_levels = normalize(bids, "bid")
    ask_levels = normalize(asks, "ask")
    best_bid = max(price for price, _ in bid_levels)
    best_ask = min(price for price, _ in ask_levels)
    if best_bid >= best_ask:
        raise ValueError("Order book is crossed or locked")

    midpoint = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / midpoint * 10000.0
    bid_notional = sum(price * volume for price, volume in bid_levels)
    ask_notional = sum(price * volume for price, volume in ask_levels)
    total_depth = bid_notional + ask_notional
    imbalance = ((bid_notional - ask_notional) / total_depth
                 if total_depth > 0 else 0.0)
    bid_concentration = max(price * volume for price, volume in bid_levels) / bid_notional
    ask_concentration = max(price * volume for price, volume in ask_levels) / ask_notional

    if imbalance >= 0.10:
        bias = "BID_DEPTH_DOMINANT"
    elif imbalance <= -0.10:
        bias = "ASK_DEPTH_DOMINANT"
    else:
        bias = "DEPTH_BALANCED"

    return {
        "status": "OK",
        "levels_analyzed": min(len(bid_levels), len(ask_levels)),
        "best_bid": round(best_bid, 10),
        "best_ask": round(best_ask, 10),
        "mid_price": round(midpoint, 10),
        "spread_bps": round(spread_bps, 4),
        "bid_depth_notional": round(bid_notional, 8),
        "ask_depth_notional": round(ask_notional, 8),
        "depth_imbalance": round(imbalance, 6),
        "largest_bid_level_share": round(bid_concentration, 6),
        "largest_ask_level_share": round(ask_concentration, 6),
        "snapshot_bias": bias,
        "metric_scope": "single_visible_order_book_snapshot",
        "limitations": [
            "Visible depth can be cancelled or changed and does not prove executable liquidity.",
            "A single snapshot cannot identify spoofing or persistent order-book behavior.",
            "Depth is venue-specific and excludes hidden liquidity and other exchanges.",
        ],
    }


def combine_microstructure(trade_flow, order_book):
    """Return a cautious context label; never a trade instruction."""
    if not isinstance(trade_flow, dict) or not isinstance(order_book, dict):
        raise ValueError("trade_flow and order_book must be analysis dictionaries")
    trade_bias = trade_flow.get("batch_bias")
    book_bias = order_book.get("snapshot_bias")
    if trade_bias not in ("BUY_PRESSURE", "SELL_PRESSURE", "BALANCED"):
        raise ValueError("trade_flow contains an unknown batch bias")
    if book_bias not in ("BID_DEPTH_DOMINANT", "ASK_DEPTH_DOMINANT", "DEPTH_BALANCED"):
        raise ValueError("order_book contains an unknown snapshot bias")
    if trade_bias == "BUY_PRESSURE" and book_bias == "BID_DEPTH_DOMINANT":
        context = "BULLISH_MICROSTRUCTURE_ALIGNMENT"
    elif trade_bias == "SELL_PRESSURE" and book_bias == "ASK_DEPTH_DOMINANT":
        context = "BEARISH_MICROSTRUCTURE_ALIGNMENT"
    elif trade_bias == "BALANCED" or book_bias == "DEPTH_BALANCED":
        context = "MIXED_OR_NEUTRAL"
    else:
        context = "DIVERGENT_MICROSTRUCTURE"
    return {
        "context": context,
        "trade_batch_bias": trade_bias,
        "order_book_snapshot_bias": book_bias,
        "research_only": True,
        "execution_enabled": False,
        "live_orders_placed": False,
    }
