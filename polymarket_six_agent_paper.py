"""Six-role Polymarket-style order-book research pipeline.

Pure, paper-only decision functions. No API credentials, network calls, live orders,
or modifications to the existing WHJ BTC/gold paper ledgers.
"""
from __future__ import annotations

import math
from typing import Any

AGENTS = ("PULSE", "IMPACT", "EDGE", "SIZE", "ENTRY", "EXIT")
LIVE_TRADING_ENABLED = False


def _num(value: Any, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def _levels(levels, label):
    if not isinstance(levels, list) or not levels:
        raise ValueError(f"{label} book side is empty")
    parsed = []
    for level in levels:
        if not isinstance(level, dict):
            raise ValueError(f"{label} level must be an object")
        price = _num(level.get("price"), f"{label} price", 0)
        size = _num(level.get("size"), f"{label} size", 0)
        if price <= 0 or size <= 0:
            raise ValueError(f"{label} price and size must be positive")
        if price > 1:
            raise ValueError(f"{label} binary-token price must be <= 1")
        parsed.append({"price": price, "size": size})
    return parsed


def pulse(book: dict, depth_levels: int = 3) -> dict:
    """Compare top-level depth; skip outcomes whose books are empty."""
    if not isinstance(book, dict) or depth_levels < 1:
        raise ValueError("A book object and positive depth_levels are required")
    result = {}
    skipped = []
    for outcome in ("UP", "DOWN"):
        side = book.get(outcome)
        if not isinstance(side, dict):
            skipped.append(outcome)
            continue
        try:
            bids = _levels(side.get("bids"), f"{outcome} bids")
            asks = _levels(side.get("asks"), f"{outcome} asks")
        except ValueError:
            skipped.append(outcome)
            continue
        d_in = sum(level["size"] for level in bids[:depth_levels])
        d_out = sum(level["size"] for level in asks[:depth_levels])
        denominator = d_in + d_out
        imbalance = (d_in - d_out) / denominator if denominator > 0 else 0.0
        result[outcome] = {
            "d_in": d_in, "d_out": d_out, "imbalance": imbalance,
            "best_bid": max(level["price"] for level in bids),
            "best_ask": min(level["price"] for level in asks),
            "bid_depth": sum(level["size"] for level in bids[:depth_levels]),
            "ask_depth": sum(level["size"] for level in asks[:depth_levels]),
        }
    if not result:
        return {
            "agent": "PULSE", "outcomes": {},
            "stronger_demand_side": None, "imbalance": None,
            "skipped_empty_books": skipped, "status": "SKIP_EMPTY_BOOKS",
        }
    chosen = max(result, key=lambda key: result[key]["imbalance"])
    return {
        "agent": "PULSE",
        "outcomes": result,
        "stronger_demand_side": chosen,
        "imbalance": result[chosen]["imbalance"],
        "skipped_empty_books": skipped,
        "status": "BOOK_SNAPSHOT_ONLY",
    }

def impact(imbalance: float, observations: list, current_exit_bid: float,
           minimum_samples: int = 20) -> dict:
    """Fit OLS: next exit-bid change = intercept + beta * past imbalance.

    Each observation must be a completed historical pair:
    {"imbalance": float, "exit_bid_change": float}.
    """
    x = _num(imbalance, "current imbalance", -1)
    if x > 1:
        raise ValueError("current imbalance must be <= 1")
    bid = _num(current_exit_bid, "current exit bid", 0)
    if bid <= 0 or bid > 1:
        raise ValueError("current exit bid must be in (0, 1]")
    if not isinstance(observations, list) or len(observations) < minimum_samples:
        return {
            "agent": "IMPACT", "status": "INSUFFICIENT_HISTORY",
            "samples": len(observations) if isinstance(observations, list) else 0,
            "predicted_move": None, "expected_exit_bid": None,
        }
    xs, ys = [], []
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("impact observation must be an object")
        xi = _num(row.get("imbalance"), "historical imbalance", -1)
        yi = _num(row.get("exit_bid_change"), "historical exit bid change")
        if xi > 1:
            raise ValueError("historical imbalance must be <= 1")
        xs.append(xi)
        ys.append(yi)
    xbar = sum(xs) / len(xs)
    ybar = sum(ys) / len(ys)
    variance = sum((value - xbar) ** 2 for value in xs)
    beta = (sum((xi - xbar) * (yi - ybar) for xi, yi in zip(xs, ys)) / variance
            if variance > 1e-12 else 0.0)
    intercept = ybar - beta * xbar
    predicted_move = intercept + beta * x
    expected_exit = min(1.0, max(0.0, bid + predicted_move))
    return {
        "agent": "IMPACT", "status": "CALIBRATED_OLS",
        "samples": len(xs), "intercept": intercept, "beta": beta,
        "predicted_move": predicted_move,
        "expected_exit_bid": expected_exit,
        "model_is_validated_profitability": False,
    }


def edge(entry_ask: float, expected_exit_bid: float, round_trip_cost: float,
         buffer: float = 0.01) -> dict:
    ask = _num(entry_ask, "entry ask", 0)
    exit_bid = _num(expected_exit_bid, "expected exit bid", 0)
    costs = _num(round_trip_cost, "round trip cost", 0)
    margin = _num(buffer, "edge buffer", 0)
    if ask <= 0 or ask > 1 or exit_bid > 1:
        raise ValueError("Binary token entry/exit prices must be in (0, 1]")
    net_edge = exit_bid - ask - costs
    return {
        "agent": "EDGE", "gross_edge": exit_bid - ask,
        "estimated_costs": costs, "net_edge": net_edge,
        "required_buffer": margin,
        "approved": net_edge > margin,
        "status": "EDGE_FOUND" if net_edge > margin else "SKIP_NO_EDGE",
    }


def size_position(risk_budget: float, stressed_adverse_move: float,
                  entry_price: float, ask_depth: float, collateral: float,
                  q_cap: float) -> dict:
    budget = _num(risk_budget, "risk budget", 0)
    adverse = _num(stressed_adverse_move, "stressed adverse move", 0)
    price = _num(entry_price, "entry price", 0)
    depth = _num(ask_depth, "available ask depth", 0)
    cash = _num(collateral, "available collateral", 0)
    cap = _num(q_cap, "quantity cap", 0)
    if adverse <= 0 or price <= 0 or price > 1:
        raise ValueError("Adverse move and binary entry price must be positive")
    quantities = {
        "risk_budget": budget / adverse,
        "book_depth": depth,
        "collateral": cash / price,
        "configured_cap": cap,
    }
    quantity = max(0.0, min(quantities.values()))
    return {
        "agent": "SIZE", "quantity": quantity,
        "limits": quantities, "risk_budget": budget,
        "stressed_adverse_move": adverse,
        "status": "SIZED" if quantity > 0 else "NO_CAPACITY",
    }


def paper_entry(asks: list, quantity: float, max_entry_price: float) -> dict:
    """Consume asks up to the limit; cancel the unfilled remainder."""
    levels = _levels(asks, "entry asks")
    target = _num(quantity, "requested quantity", 0)
    limit = _num(max_entry_price, "maximum entry price", 0)
    if limit <= 0 or limit > 1:
        raise ValueError("Entry limit must be in (0, 1]")
    eligible = sorted((level for level in levels if level["price"] <= limit),
                     key=lambda level: level["price"])
    remaining = target
    filled = 0.0
    quote = 0.0
    for level in eligible:
        take = min(remaining, level["size"])
        filled += take
        quote += take * level["price"]
        remaining -= take
        if remaining <= 1e-12:
            break
    avg_price = quote / filled if filled > 0 else None
    return {
        "agent": "ENTRY", "mode": "PAPER_ONLY",
        "requested_quantity": target, "filled_quantity": filled,
        "average_fill_price": avg_price, "quote_spent": quote,
        "unfilled_cancelled": max(0.0, remaining),
        "limit_price": limit, "orders_submitted": False,
        "status": "FILLED" if remaining <= 1e-12 else (
            "PARTIAL_CANCEL_REMAINDER" if filled > 0 else "NO_FILL"
        ),
    }


def exit_pnl(quantity: float, entry_price: float, exit_price: float,
              total_costs: float) -> dict:
    qty = _num(quantity, "filled quantity", 0)
    entry = _num(entry_price, "average entry price", 0)
    exit_ = _num(exit_price, "average exit price", 0)
    costs = _num(total_costs, "all execution costs", 0)
    if entry > 1 or exit_ > 1:
        raise ValueError("Binary token prices must be <= 1")
    pnl = qty * (exit_ - entry) - costs
    return {
        "agent": "EXIT", "quantity": qty,
        "entry_price": entry, "exit_price": exit_,
        "all_costs": costs, "realized_pnl": pnl,
        "return_on_entry_pct": (pnl / (qty * entry) * 100
                                if qty > 0 and entry > 0 else None),
        "mode": "PAPER_ONLY",
    }


def run_six_agents(book: dict, observations: dict, risk: dict,
                    round_trip_cost: float, edge_buffer: float = 0.01) -> dict:
    """Unified research decision. It never creates an order or changes a ledger."""
    pulse_result = pulse(book)
    side = pulse_result["stronger_demand_side"]
    if side is None:
        return {
            "agents": [pulse_result], "decision": "HOLD",
            "reason": "ALL_BOOKS_EMPTY_OR_UNAVAILABLE",
            "paper_only": True, "live_orders_enabled": False,
            "orders_submitted": False,
        }
    selected = pulse_result["outcomes"][side]
    history = observations.get(side, []) if isinstance(observations, dict) else []
    impact_result = impact(
        pulse_result["imbalance"], history, selected["best_bid"]
    )
    if impact_result["status"] != "CALIBRATED_OLS":
        return {
            "agents": [pulse_result, impact_result],
            "decision": "HOLD", "reason": "IMPACT_HISTORY_INSUFFICIENT",
            "paper_only": True, "live_orders_enabled": False,
            "orders_submitted": False,
        }
    edge_result = edge(
        selected["best_ask"], impact_result["expected_exit_bid"],
        round_trip_cost, edge_buffer,
    )
    if not edge_result["approved"]:
        return {
            "agents": [pulse_result, impact_result, edge_result],
            "selected_side": side, "decision": "HOLD",
            "reason": "EDGE_BELOW_REQUIRED_BUFFER",
            "paper_only": True, "live_orders_enabled": False,
            "orders_submitted": False,
        }
    sizing = size_position(
        risk_budget=risk["risk_budget"],
        stressed_adverse_move=risk["stressed_adverse_move"],
        entry_price=selected["best_ask"],
        ask_depth=selected["ask_depth"],
        collateral=risk["collateral"],
        q_cap=risk["q_cap"],
    )
    return {
        "agents": [pulse_result, impact_result, edge_result, sizing],
        "selected_side": side,
        "decision": "PAPER_CANDIDATE" if sizing["quantity"] > 0 else "HOLD",
        "paper_only": True, "live_orders_enabled": False,
        "orders_submitted": False,
        "warning": "ENTRY and EXIT require a separate event-driven paper simulator and verified fill/fee data.",
    }
