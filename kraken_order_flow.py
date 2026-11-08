"""Read-only Kraken trade-flow, order-book and incremental CVD diagnostics.

This module consumes public Kraken market data. It does not place orders or
infer hidden liquidity. WebSocket transport and durable state storage remain
caller-managed.
"""
import json
import math
import os
import re
import socket
import tempfile
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


def fetch_recent_trades(pair="XBTUSD", timeout=10, since=None):
    """Fetch a public trade batch, optionally resuming from Kraken's cursor."""
    if not isinstance(pair, str) or not pair or len(pair) > 32:
        raise ValueError("pair must be a non-empty Kraken pair identifier")
    params = {"pair": pair}
    if since is not None:
        if isinstance(since, bool) or not str(since).isdigit() or int(since) <= 0:
            raise ValueError("since must be a positive Kraken cursor or nanosecond timestamp")
        params["since"] = str(since)
    result = _kraken_get("Trades", params, timeout=timeout)
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


def _trade_event_timestamp_ns(value):
    """Convert Unix seconds or timezone-aware ISO-8601 to exact nanoseconds."""
    if isinstance(value, bool):
        raise ValueError("trade timestamp must be numeric or timezone-aware ISO text")
    if isinstance(value, (int, float)):
        number = _finite_number(value, "trade timestamp")
        if number < 0:
            raise ValueError("trade timestamp must be non-negative")
        from decimal import Decimal
        return int(Decimal(str(value)) * Decimal(1_000_000_000))
    if not isinstance(value, str) or not value:
        raise ValueError("trade timestamp must be numeric or timezone-aware ISO text")
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("trade timestamp must be valid ISO-8601 text") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("trade timestamp ISO text must include a timezone")
    base_seconds = int(parsed.replace(microsecond=0).timestamp())
    match = re.search(r"\.(\d+)", value)
    fraction_ns = int((match.group(1) + "000000000")[:9]) if match else 0
    timestamp_ns = base_seconds * 1_000_000_000 + fraction_ns
    if timestamp_ns < 0:
        raise ValueError("trade timestamp must be non-negative")
    return timestamp_ns


def _trade_event_timestamp(value):
    """Compatibility float timestamp derived from the exact nanosecond value."""
    return _trade_event_timestamp_ns(value) / 1_000_000_000.0


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
        self.last_trade_timestamp_ns = None
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
        timestamp_ns = state.get("last_trade_timestamp_ns")
        if timestamp_ns is not None:
            if isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int) or timestamp_ns < 0:
                raise ValueError("last_trade_timestamp_ns must be a non-negative integer")
        elif timestamp is not None:
            from decimal import Decimal
            timestamp_ns = int(Decimal(str(timestamp)) * Decimal(1_000_000_000))
        self.last_trade_id = last_id
        self.cumulative_buy_volume = buy
        self.cumulative_sell_volume = sell
        self.processed_trade_count = count
        self.last_trade_timestamp = timestamp
        self.last_trade_timestamp_ns = timestamp_ns

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
            "last_trade_timestamp_ns": self.last_trade_timestamp_ns,
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
            timestamp_ns = _trade_event_timestamp_ns(event.get("timestamp"))
            timestamp = timestamp_ns / 1_000_000_000.0
            side = event.get("side")
            if price <= 0 or quantity <= 0 or timestamp < 0:
                raise ValueError("trade price/quantity must be positive and timestamp non-negative")
            if side not in ("buy", "sell"):
                raise ValueError("trade side must be 'buy' or 'sell'")
            item = (price, quantity, timestamp_ns, side)
            if trade_id in normalized and normalized[trade_id] != item:
                raise ValueError("conflicting payloads for duplicate trade_id")
            normalized[trade_id] = item

        accepted = []
        ignored = 0
        last_timestamp_ns = self.last_trade_timestamp_ns
        for trade_id in sorted(normalized):
            if trade_id <= self.last_trade_id:
                ignored += 1
                continue
            price, quantity, timestamp_ns, side = normalized[trade_id]
            if last_timestamp_ns is not None and timestamp_ns < last_timestamp_ns:
                raise ValueError("new trade timestamps must be non-decreasing by trade_id")
            expected_id = (
                accepted[-1][0] + 1 if accepted
                else self.last_trade_id + 1 if self.processed_trade_count else None
            )
            if expected_id is not None and trade_id != expected_id:
                raise TradeIdGapError(
                    f"trade ID gap detected: expected {expected_id}, received {trade_id}; "
                    "recover missing trades before applying this batch"
                )
            accepted.append((trade_id, quantity, timestamp_ns, side))
            last_timestamp_ns = timestamp_ns

        # Commit only after every event has passed validation.
        for trade_id, quantity, timestamp_ns, side in accepted:
            if side == "buy":
                self.cumulative_buy_volume += quantity
            else:
                self.cumulative_sell_volume += quantity
            self.last_trade_id = trade_id
            self.last_trade_timestamp_ns = timestamp_ns
            self.last_trade_timestamp = timestamp_ns / 1_000_000_000.0
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


class TradeIdGapError(ValueError):
    """Raised when a per-symbol trade sequence has a missing ID."""


def normalize_kraken_ws_v2_trade_message(message, expected_symbol=None):
    """Convert a Kraken Spot WebSocket v2 trade envelope to ledger events."""
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except json.JSONDecodeError as exc:
            raise ValueError("WebSocket message must be valid JSON") from exc
    if not isinstance(message, dict):
        raise ValueError("WebSocket message must be an object")
    if message.get("channel") != "trade":
        return []
    if message.get("type") not in ("snapshot", "update"):
        raise ValueError("Unknown Kraken WebSocket trade message type")
    rows = message.get("data")
    if not isinstance(rows, list):
        raise ValueError("Kraken WebSocket trade data must be a list")
    events = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Kraken WebSocket trade item must be an object")
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("Kraken WebSocket trade is missing symbol")
        if expected_symbol is not None and symbol != expected_symbol:
            raise ValueError("Kraken WebSocket trade symbol does not match subscription")
        events.append({
            "symbol": symbol,
            "trade_id": row.get("trade_id"),
            "price": row.get("price"),
            "qty": row.get("qty"),
            "side": row.get("side"),
            "timestamp": row.get("timestamp"),
        })
    return events


def normalize_kraken_rest_trade_rows(rows, symbol):
    """Normalize REST Trades rows; require the exchange-provided seventh ID field."""
    if not isinstance(rows, (list, tuple)):
        raise ValueError("Kraken REST trade rows must be a list")
    events = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            raise ValueError(
                "Kraken REST trade row lacks trade_id; refusing unsafe CVD backfill"
            )
        side = row[3]
        if side not in ("b", "s"):
            raise ValueError("Kraken REST trade row has an unknown aggressor side")
        events.append({
            "symbol": symbol,
            "trade_id": row[6],
            "price": row[0],
            "qty": row[1],
            "side": "buy" if side == "b" else "sell",
            "timestamp": row[2],
        })
    return events


class TradeJournalPersistenceError(RuntimeError):
    """Raised when raw trade journal persistence fails after ledger validation."""


class KrakenSpotTradeFeedAdapter:
    """Bridge decoded Kraken WS v2 trade envelopes into a persistent CVD ledger.

    The caller owns the WebSocket connection, subscription, heartbeat,
    reconnect loop, and atomic persistence of ledger.to_state(). On a detected
    trade-ID gap, this adapter backfills through Kraken REST Trades before
    applying the incoming WebSocket update.
    """

    def __init__(self, ledger, pair, timeout=10, max_backfill_pages=10, on_accepted_trades=None, require_initial_snapshot=False):
        if not isinstance(ledger, PersistentCvdLedger):
            raise ValueError("ledger must be a PersistentCvdLedger")
        if not isinstance(pair, str) or not pair.strip():
            raise ValueError("pair must be a non-empty string")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        if isinstance(max_backfill_pages, bool) or not isinstance(max_backfill_pages, int) or max_backfill_pages < 1:
            raise ValueError("max_backfill_pages must be a positive integer")
        if ledger.symbol not in (None, pair):
            raise ValueError("ledger symbol does not match adapter pair")
        ledger.symbol = pair
        self.ledger = ledger
        self.pair = pair
        self.timeout = timeout
        if on_accepted_trades is not None and not callable(on_accepted_trades):
            raise ValueError("on_accepted_trades must be callable")
        if not isinstance(require_initial_snapshot, bool):
            raise ValueError("require_initial_snapshot must be boolean")
        self.max_backfill_pages = max_backfill_pages
        self.on_accepted_trades = on_accepted_trades
        self.require_initial_snapshot = require_initial_snapshot
        self.continuity_start_trade_id = None

    def _emit_accepted_trades(self, events, previous_trade_id):
        if self.on_accepted_trades is None:
            return
        accepted = sorted(
            (event for event in events
             if previous_trade_id < self.ledger._trade_id(event.get("trade_id")) <= self.ledger.last_trade_id),
            key=lambda event: self.ledger._trade_id(event.get("trade_id")),
        )
        if accepted:
            try:
                self.on_accepted_trades(accepted)
            except Exception as exc:
                raise TradeJournalPersistenceError(
                    "raw trade journal persistence failed; collector stopped"
                ) from exc

    def _backfill_until(self, target_trade_id):
        if self.ledger.last_trade_timestamp is None:
            raise TradeIdGapError(
                "cannot recover a gap without a prior trade timestamp; bootstrap a fresh snapshot"
            )
        cursor = str(
            self.ledger.last_trade_timestamp_ns
            if self.ledger.last_trade_timestamp_ns is not None
            else int(self.ledger.last_trade_timestamp * 1_000_000_000)
        )
        pages = 0
        accepted = 0
        while self.ledger.last_trade_id < target_trade_id and pages < self.max_backfill_pages:
            batch = fetch_recent_trades(self.pair, timeout=self.timeout, since=cursor)
            rows = batch.get("trades")
            if not isinstance(rows, list):
                raise ValueError("Kraken REST response is missing trade rows")
            events = normalize_kraken_rest_trade_rows(rows, self.pair)
            before_id = self.ledger.last_trade_id
            if events:
                result = self.ledger.process(events)
                accepted += result["accepted_in_batch"]
                self._emit_accepted_trades(events, before_id)
            next_cursor = batch.get("last")
            pages += 1
            if self.ledger.last_trade_id >= target_trade_id:
                break
            if not next_cursor or str(next_cursor) == cursor or self.ledger.last_trade_id == before_id:
                break
            cursor = str(next_cursor)
        return {
            "pages": pages,
            "accepted_trades": accepted,
            "recovered": self.ledger.last_trade_id >= target_trade_id,
            "last_trade_id": self.ledger.last_trade_id,
        }

    def handle_message(self, message):
        """Process a WS v2 envelope, backfilling a sequence gap before retry."""
        message_type = message.get("type") if isinstance(message, dict) else None
        if (self.require_initial_snapshot and self.continuity_start_trade_id is None
                and self.ledger.last_trade_id == 0 and message_type != "snapshot"):
            raise TradeIdGapError(
                "a fresh journal must begin with Kraken's initial trade snapshot"
            )
        events = normalize_kraken_ws_v2_trade_message(message, self.pair)
        if not events:
            return {
                "status": "IGNORED_NON_TRADE_MESSAGE",
                "execution_enabled": False,
                "live_orders_placed": False,
            }
        target_id = max(self.ledger._trade_id(event.get("trade_id")) for event in events)
        previous_id = self.ledger.last_trade_id
        try:
            result = self.ledger.process(events)
            self._emit_accepted_trades(events, previous_id)
            recovery = {"attempted": False, "recovered": True, "pages": 0}
        except TradeIdGapError:
            recovery = self._backfill_until(target_id)
            if not recovery["recovered"]:
                raise TradeIdGapError(
                    "REST backfill did not reach the WebSocket trade ID; "
                    "state is partial and must be persisted before retry"
                )
            previous_id = self.ledger.last_trade_id
            result = self.ledger.process(events)
            self._emit_accepted_trades(events, previous_id)
        if (self.require_initial_snapshot and self.continuity_start_trade_id is None
                and message_type == "snapshot" and self.ledger.last_trade_id > 0):
            self.continuity_start_trade_id = min(
                self.ledger._trade_id(event.get("trade_id")) for event in events
            )
        return {
            "status": "OK",
            "ledger": result,
            "backfill": recovery,
            "continuity_verified_to_trade_id": self.ledger.last_trade_id,
            "research_only": True,
            "execution_enabled": False,
            "live_orders_placed": False,
            "limitations": [
                "The caller must persist ledger.to_state() atomically after each successful update.",
                "The caller owns WebSocket connection, heartbeat, reconnect and subscription lifecycle.",
                "Recovery is limited to Kraken REST history availability and the configured page cap.",
                "A fresh ledger snapshot establishes a baseline; it does not recover trades before that baseline.",
            ],
        }


def load_cvd_state(path):
    """Load saved CVD JSON state; missing files return None, corrupt files raise."""
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise ValueError("state path must be a non-empty path")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return None
    if not isinstance(state, dict):
        raise ValueError("saved CVD state must be a JSON object")
    return state


def save_cvd_state_atomic(path, state):
    """Durably replace CVD JSON state using same-directory atomic rename."""
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise ValueError("state path must be a non-empty path")
    if not isinstance(state, dict):
        raise ValueError("CVD state must be an object")
    target = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".whj-cvd-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        try:
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class StatePersistenceError(RuntimeError):
    """Raised when the caller's durable CVD state callback fails."""


class KrakenSpotWebSocketRunner:
    """Reconnect-capable public WS v2 runner around KrakenSpotTradeFeedAdapter.

    The default transport uses the optional websocket-client package. Tests
    and alternate transports can inject a websocket_factory(url, timeout).
    The caller supplies an atomic persist_state callback; private endpoints and
    order execution are never used.
    """

    URL = "wss://ws.kraken.com/v2"

    def __init__(
        self,
        adapter,
        timeout=20,
        initial_backoff=1.0,
        max_backoff=30.0,
        max_reconnect_attempts=0,
    ):
        if not isinstance(adapter, KrakenSpotTradeFeedAdapter):
            raise ValueError("adapter must be a KrakenSpotTradeFeedAdapter")
        for name, value in (
            ("timeout", timeout),
            ("initial_backoff", initial_backoff),
            ("max_backoff", max_backoff),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if max_backoff < initial_backoff:
            raise ValueError("max_backoff must be at least initial_backoff")
        if isinstance(max_reconnect_attempts, bool) or not isinstance(max_reconnect_attempts, int) or max_reconnect_attempts < 0:
            raise ValueError("max_reconnect_attempts must be a non-negative integer")
        self.adapter = adapter
        self.timeout = float(timeout)
        self.initial_backoff = float(initial_backoff)
        self.max_backoff = float(max_backoff)
        self.max_reconnect_attempts = max_reconnect_attempts

    @staticmethod
    def _default_websocket_factory(url, timeout):
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError(
                "Install the optional websocket-client package to open Kraken WS"
            ) from exc
        return websocket.create_connection(url, timeout=timeout)

    def run(self, stop_event, persist_state, websocket_factory=None):
        """Run until stopped; reconnect with exponential backoff.

        persist_state receives a JSON-serializable ledger state after each
        successful batch/backfill. Persistence errors stop the runner rather
        than allowing it to continue with unsaved CVD state.
        """
        if not all(hasattr(stop_event, name) for name in ("is_set", "wait")):
            raise ValueError("stop_event must provide is_set() and wait()")
        if not callable(persist_state):
            raise ValueError("persist_state must be callable")
        factory = websocket_factory or self._default_websocket_factory
        reconnects = 0
        received_trades = 0
        backfilled_trades = 0
        last_error = None
        backoff = self.initial_backoff

        while not stop_event.is_set():
            ws = None
            try:
                ws = factory(self.URL, self.timeout)
                ws.settimeout(self.timeout)
                ws.send(json.dumps({
                    "method": "subscribe",
                    "params": {
                        "channel": "trade",
                        "symbol": [self.adapter.pair],
                        "snapshot": True,
                    },
                    "req_id": 1,
                }))
                while not stop_event.is_set():
                    try:
                        raw_message = ws.recv()
                    except Exception as exc:
                        if isinstance(exc, (TimeoutError, socket.timeout)) or exc.__class__.__name__ == "WebSocketTimeoutException":
                            continue
                        raise
                    if raw_message in (None, ""):
                        raise ConnectionError("Kraken WebSocket closed the connection")
                    message = json.loads(raw_message) if isinstance(raw_message, str) else raw_message
                    if isinstance(message, dict) and (
                        message.get("success") is False or message.get("error")
                    ):
                        raise RuntimeError(f"Kraken WebSocket error: {message}")
                    result = self.adapter.handle_message(message)
                    if result.get("status") != "OK":
                        continue
                    ledger_result = result.get("ledger", {})
                    accepted = ledger_result.get("accepted_in_batch", 0)
                    backfilled = result.get("backfill", {}).get("accepted_trades", 0)
                    if accepted or backfilled:
                        try:
                            persist_state(self.adapter.ledger.to_state())
                        except Exception as exc:
                            raise StatePersistenceError(
                                "CVD state persistence failed; runner stopped"
                            ) from exc
                        received_trades += accepted
                        backfilled_trades += backfilled
            except (StatePersistenceError, TradeJournalPersistenceError):
                raise
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if stop_event.is_set():
                    break
                reconnects += 1
                if self.max_reconnect_attempts and reconnects > self.max_reconnect_attempts:
                    raise RuntimeError(
                        f"Kraken WebSocket reconnect limit reached: {last_error}"
                    ) from exc
                stop_event.wait(backoff)
                backoff = min(backoff * 2.0, self.max_backoff)
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

        return {
            "status": "STOPPED",
            "reconnects": reconnects,
            "accepted_websocket_trades": received_trades,
            "accepted_backfill_trades": backfilled_trades,
            "last_trade_id": self.adapter.ledger.last_trade_id,
            "last_error": last_error,
            "execution_enabled": False,
            "live_orders_placed": False,
        }
