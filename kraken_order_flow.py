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


def evaluate_microstructure_confluence(
    ohlcv_analysis,
    trade_flow,
    order_book,
    max_spread_bps=15.0,
    min_total_depth_notional=100000.0,
    max_level_concentration=0.65,
):
    """Fuse completed-bar OHLCV context with one trade batch and depth snapshot.

    This is a research diagnostic only. Callers must independently enforce
    timestamp freshness/alignment; a single snapshot cannot establish durable
    liquidity or spoofing. The function never emits an order instruction.
    """
    if not all(isinstance(value, dict) for value in (ohlcv_analysis, trade_flow, order_book)):
        raise ValueError("OHLCV, trade-flow and order-book inputs must be dictionaries")

    limits = {
        "max_spread_bps": max_spread_bps,
        "min_total_depth_notional": min_total_depth_notional,
        "max_level_concentration": max_level_concentration,
    }
    for name, value in limits.items():
        if isinstance(value, bool):
            raise ValueError(f"{name} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        if number < 0:
            raise ValueError(f"{name} must be non-negative")
        limits[name] = number
    if limits["max_level_concentration"] > 1:
        raise ValueError("max_level_concentration cannot exceed 1")

    ohlcv_status = ohlcv_analysis.get("status")
    if ohlcv_status not in (
        "BULLISH_RESEARCH_CANDIDATE",
        "BEARISH_RESEARCH_CANDIDATE",
        "WATCH",
    ):
        raise ValueError("OHLCV analysis has an unknown status")
    trade_bias = trade_flow.get("batch_bias")
    book_bias = order_book.get("snapshot_bias")
    if trade_bias not in ("BUY_PRESSURE", "SELL_PRESSURE", "BALANCED"):
        raise ValueError("trade-flow analysis has an unknown batch bias")
    if book_bias not in (
        "BID_DEPTH_DOMINANT", "ASK_DEPTH_DOMINANT", "DEPTH_BALANCED"
    ):
        raise ValueError("order-book analysis has an unknown snapshot bias")

    spread = _finite_number(order_book.get("spread_bps"), "spread_bps")
    bid_depth = _finite_number(
        order_book.get("bid_depth_notional"), "bid_depth_notional"
    )
    ask_depth = _finite_number(
        order_book.get("ask_depth_notional"), "ask_depth_notional"
    )
    bid_concentration = _finite_number(
        order_book.get("largest_bid_level_share"), "largest_bid_level_share"
    )
    ask_concentration = _finite_number(
        order_book.get("largest_ask_level_share"), "largest_ask_level_share"
    )
    if min(spread, bid_depth, ask_depth, bid_concentration, ask_concentration) < 0:
        raise ValueError("Order-book metrics must be non-negative")
    if max(bid_concentration, ask_concentration) > 1:
        raise ValueError("Order-book concentration shares cannot exceed 1")

    total_depth = bid_depth + ask_depth
    concentration = max(bid_concentration, ask_concentration)
    quality_checks = {
        "spread_within_limit": spread <= limits["max_spread_bps"],
        "minimum_visible_depth": total_depth >= limits["min_total_depth_notional"],
        "no_single_level_concentration": concentration <= limits["max_level_concentration"],
    }
    quality_ok = all(quality_checks.values())

    direction = (
        "BULLISH" if ohlcv_status == "BULLISH_RESEARCH_CANDIDATE"
        else "BEARISH" if ohlcv_status == "BEARISH_RESEARCH_CANDIDATE"
        else "NEUTRAL"
    )
    flow_agrees = (
        (direction == "BULLISH" and trade_bias == "BUY_PRESSURE")
        or (direction == "BEARISH" and trade_bias == "SELL_PRESSURE")
    )
    depth_agrees = (
        (direction == "BULLISH" and book_bias == "BID_DEPTH_DOMINANT")
        or (direction == "BEARISH" and book_bias == "ASK_DEPTH_DOMINANT")
    )
    if not quality_ok:
        context = "LIQUIDITY_QUALITY_FAIL"
    elif direction == "NEUTRAL":
        context = "NO_DIRECTIONAL_OHLCV_SIGNAL"
    elif flow_agrees and depth_agrees:
        context = f"{direction}_THREE_LAYER_ALIGNMENT"
    elif flow_agrees or depth_agrees:
        context = "PARTIAL_MICROSTRUCTURE_CONFIRMATION"
    else:
        context = "MICROSTRUCTURE_DIVERGENCE"

    return {
        "context": context,
        "ohlcv_direction": direction,
        "trade_flow_agrees": flow_agrees,
        "order_book_agrees": depth_agrees,
        "liquidity_quality_checks": quality_checks,
        "visible_depth_notional": round(total_depth, 8),
        "spread_bps": round(spread, 4),
        "max_level_concentration": round(concentration, 6),
        "research_only": True,
        "execution_enabled": False,
        "live_orders_placed": False,
        "timestamp_alignment_verified": False,
        "limitations": [
            "The caller must align OHLCV close time, trade-batch time bounds and order-book capture time.",
            "Trade flow is limited to the supplied exchange batch; it is not persistent CVD.",
            "Visible depth is a single exchange snapshot and can be cancelled or spoofed.",
            "Quote-notional depth thresholds are venue and instrument specific.",
            "This diagnostic is not a backtested order-book strategy or an execution instruction.",
        ],
    }


def _trade_event_timestamp(value):
    """Normalize a numeric Unix timestamp or timezone-aware ISO timestamp."""
    if isinstance(value, bool):
        raise ValueError("trade timestamp must be numeric or timezone-aware ISO text")
    if isinstance(value, (int, float)):
        return _finite_number(value, "trade timestamp")
    if not isinstance(value, str) or not value:
        raise ValueError("trade timestamp must be numeric or timezone-aware ISO text")
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("trade timestamp must be valid ISO-8601 text") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("trade timestamp ISO text must include a timezone")
    return parsed.timestamp()


class PersistentCvdLedger:
    """Incremental, serializable CVD ledger for uniquely identified trade events.

    Feed adapters should pass one event per executed trade with a monotonically
    increasing numeric trade_id, price, qty, side ('buy'/'sell'), and timestamp.
    The ledger deduplicates replayed IDs and can be restored from to_state().
    It does not connect to a websocket or persist state to disk by itself.
    """

    STATE_VERSION = 1

    def __init__(self, symbol=None, state=None):
        if symbol is not None and (not isinstance(symbol, str) or not symbol.strip()):
            raise ValueError("symbol must be a non-empty string when provided")
        self.symbol = symbol
        self.last_trade_id = 0
        self.cumulative_buy_volume = 0.0
        self.cumulative_sell_volume = 0.0
        self.processed_trade_count = 0
        self.last_trade_timestamp = None
        if state is not None:
            self._restore_state(state)

    @staticmethod
    def _trade_id(value):
        if isinstance(value, bool):
            raise ValueError("trade_id must be a positive integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("trade_id must be a positive integer") from exc
        if parsed <= 0 or str(parsed) != str(value).strip():
            raise ValueError("trade_id must be a positive integer")
        return parsed

    def _restore_state(self, state):
        if not isinstance(state, dict):
            raise ValueError("CVD state must be an object")
        if state.get("version") != self.STATE_VERSION:
            raise ValueError("Unsupported CVD state version")
        stored_symbol = state.get("symbol")
        if self.symbol is not None and stored_symbol not in (None, self.symbol):
            raise ValueError("CVD state symbol does not match ledger symbol")
        if self.symbol is None:
            self.symbol = stored_symbol
        last_id = self._trade_id(state.get("last_trade_id", 0)) if state.get("last_trade_id", 0) else 0
        buy = _finite_number(state.get("cumulative_buy_volume", 0.0), "cumulative_buy_volume")
        sell = _finite_number(state.get("cumulative_sell_volume", 0.0), "cumulative_sell_volume")
        count = state.get("processed_trade_count", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("processed_trade_count must be a non-negative integer")
        if buy < 0 or sell < 0:
            raise ValueError("Cumulative volumes must be non-negative")
        timestamp = state.get("last_trade_timestamp")
        if timestamp is not None:
            timestamp = _finite_number(timestamp, "last_trade_timestamp")
            if timestamp < 0:
                raise ValueError("last_trade_timestamp must be non-negative")
        self.last_trade_id = last_id
        self.cumulative_buy_volume = buy
        self.cumulative_sell_volume = sell
        self.processed_trade_count = count
        self.last_trade_timestamp = timestamp

    def to_state(self):
        """Return JSON-serializable state for caller-managed durable storage."""
        return {
            "version": self.STATE_VERSION,
            "symbol": self.symbol,
            "last_trade_id": self.last_trade_id,
            "cumulative_buy_volume": self.cumulative_buy_volume,
            "cumulative_sell_volume": self.cumulative_sell_volume,
            "processed_trade_count": self.processed_trade_count,
            "last_trade_timestamp": self.last_trade_timestamp,
        }

    def process(self, events):
        """Apply a batch atomically; duplicate/replayed IDs are ignored."""
        if not isinstance(events, (list, tuple)):
            raise ValueError("events must be a list or tuple")
        normalized = {}
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("each trade event must be an object")
            event_symbol = event.get("symbol")
            if self.symbol is not None and event_symbol not in (None, self.symbol):
                raise ValueError("trade event symbol does not match ledger symbol")
            trade_id = self._trade_id(event.get("trade_id"))
            price = _finite_number(event.get("price"), "trade price")
            quantity = _finite_number(event.get("qty"), "trade quantity")
            timestamp = _trade_event_timestamp(event.get("timestamp"))
            side = event.get("side")
            if price <= 0 or quantity <= 0 or timestamp < 0:
                raise ValueError("trade price/quantity must be positive and timestamp non-negative")
            if side not in ("buy", "sell"):
                raise ValueError("trade side must be 'buy' or 'sell'")
            item = (price, quantity, timestamp, side)
            if trade_id in normalized and normalized[trade_id] != item:
                raise ValueError("conflicting payloads for duplicate trade_id")
            normalized[trade_id] = item

        accepted = []
        ignored = 0
        last_timestamp = self.last_trade_timestamp
        for trade_id in sorted(normalized):
            if trade_id <= self.last_trade_id:
                ignored += 1
                continue
            price, quantity, timestamp, side = normalized[trade_id]
            if last_timestamp is not None and timestamp < last_timestamp:
                raise ValueError("new trade timestamps must be non-decreasing by trade_id")
            accepted.append((trade_id, quantity, timestamp, side))
            last_timestamp = timestamp

        # Commit only after every event has passed validation.
        for trade_id, quantity, timestamp, side in accepted:
            if side == "buy":
                self.cumulative_buy_volume += quantity
            else:
                self.cumulative_sell_volume += quantity
            self.last_trade_id = trade_id
            self.last_trade_timestamp = timestamp
            self.processed_trade_count += 1

        result = self.snapshot()
        result["accepted_in_batch"] = len(accepted)
        result["ignored_replayed_or_stale_in_batch"] = ignored
        return result

    def snapshot(self):
        total = self.cumulative_buy_volume + self.cumulative_sell_volume
        delta = self.cumulative_buy_volume - self.cumulative_sell_volume
        delta_pct = delta / total if total > 0 else 0.0
        bias = (
            "BUY_PRESSURE" if delta_pct >= 0.10 else
            "SELL_PRESSURE" if delta_pct <= -0.10 else
            "BALANCED"
        )
        return {
            "status": "OK",
            "symbol": self.symbol,
            "last_trade_id": self.last_trade_id,
            "processed_trade_count": self.processed_trade_count,
            "cumulative_buy_volume": round(self.cumulative_buy_volume, 12),
            "cumulative_sell_volume": round(self.cumulative_sell_volume, 12),
            "cumulative_delta": round(delta, 12),
            "cumulative_delta_pct": round(delta_pct * 100.0, 4),
            "cumulative_buy_volume_ratio": round(
                self.cumulative_buy_volume / total if total > 0 else 0.0, 6
            ),
            "last_trade_timestamp": self.last_trade_timestamp,
            "cumulative_bias": bias,
            "metric_scope": "persistable_incremental_trade_id_ledger",
            "is_persistent_cvd": True,
            "durable_storage_managed_by_caller": True,
            "limitations": [
                "The caller must persist to_state() atomically and restore it after restart.",
                "The feed adapter must provide unique, monotonic trade IDs and recover missed events after reconnect.",
                "This ledger does not prove gap-free ingestion; reconnect recovery must be verified by the adapter.",
                "CVD is specific to the supplied venue, symbol and feed.",
            ],
        }
