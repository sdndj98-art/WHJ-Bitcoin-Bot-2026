"""Harmonic patterns, supply/demand zones and RSI divergence.

Closed-candle diagnostics only. No order execution or trading recommendations.
"""
import math


PATTERNS = {
    "GARTLEY": {"ab": (0.618, 0.055), "bc": (0.382, 0.886), "cd": (1.272, 1.618), "ad": (0.786, 0.055)},
    "BAT": {"ab": (0.50, 0.12), "bc": (0.382, 0.886), "cd": (1.618, 2.618), "ad": (0.886, 0.07)},
    "BUTTERFLY": {"ab": (0.786, 0.06), "bc": (0.382, 0.886), "cd": (1.618, 2.24), "ad": (1.27, 0.10)},
    "CRAB": {"ab": (0.50, 0.12), "bc": (0.382, 0.886), "cd": (2.24, 3.618), "ad": (1.618, 0.12)},
}


def _rsi_series(closes, period=14):
    if len(closes) <= period:
        return [50.0] * len(closes)
    result = [50.0] * len(closes)
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = sum(max(x, 0.0) for x in changes[:period]) / period
    loss = sum(max(-x, 0.0) for x in changes[:period]) / period
    def value(g, l):
        if l == 0:
            return 100.0 if g else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)
    result[period] = value(gain, loss)
    for i in range(period + 1, len(closes)):
        change = changes[i - 1]
        gain = (gain * (period - 1) + max(change, 0.0)) / period
        loss = (loss * (period - 1) + max(-change, 0.0)) / period
        result[i] = value(gain, loss)
    for i in range(period):
        result[i] = result[period]
    return result


def _pivots(rows, left=3, right=3):
    pivots = []
    for i in range(left, len(rows) - right):
        high = rows[i][2]
        low = rows[i][3]
        if high >= max(rows[j][2] for j in range(i-left, i+right+1) if j != i):
            pivots.append({"index": i, "kind": "H", "price": high})
        if low <= min(rows[j][3] for j in range(i-left, i+right+1) if j != i):
            pivots.append({"index": i, "kind": "L", "price": low})
    pivots.sort(key=lambda p: p["index"])
    compact = []
    for point in pivots:
        if compact and compact[-1]["kind"] == point["kind"]:
            better = (point["price"] > compact[-1]["price"] if point["kind"] == "H"
                      else point["price"] < compact[-1]["price"])
            if better:
                compact[-1] = point
        else:
            compact.append(point)
    return compact


def _near(value, target, tolerance):
    return abs(value - target) <= tolerance


def _harmonic(pivots):
    if len(pivots) < 5:
        return {"status": "NO_CONFIRMED_PATTERN", "pattern": None, "direction": "NONE"}
    x, a, b, c, d = pivots[-5:]
    if len({p["kind"] for p in (x, a, b, c, d)}) != 2:
        return {"status": "NO_CONFIRMED_PATTERN", "pattern": None, "direction": "NONE"}
    bullish = [p["kind"] for p in (x, a, b, c, d)] == ["L", "H", "L", "H", "L"]
    bearish = [p["kind"] for p in (x, a, b, c, d)] == ["H", "L", "H", "L", "H"]
    if not (bullish or bearish):
        return {"status": "NO_CONFIRMED_PATTERN", "pattern": None, "direction": "NONE"}
    xa, ab, bc, cd = abs(a["price"]-x["price"]), abs(b["price"]-a["price"]), abs(c["price"]-b["price"]), abs(d["price"]-c["price"])
    ad = abs(d["price"]-a["price"])
    if min(xa, ab, bc, cd) <= 0:
        return {"status": "NO_CONFIRMED_PATTERN", "pattern": None, "direction": "NONE"}
    ratios = {"ab": ab/xa, "bc": bc/ab, "cd": cd/bc, "ad": ad/xa}
    matched = []
    for name, rules in PATTERNS.items():
        if (_near(ratios["ab"], *rules["ab"]) and
            rules["bc"][0] <= ratios["bc"] <= rules["bc"][1] and
            rules["cd"][0] <= ratios["cd"] <= rules["cd"][1] and
            _near(ratios["ad"], *rules["ad"])):
            matched.append(name)
    # Cypher has a distinct BC extension and CD-to-XC retracement definition.
    xc = abs(c["price"] - x["price"])
    if xa and ab and bc and xc:
        if (0.382 <= ratios["ab"] <= 0.618 and
            1.272 <= abs(c["price"]-b["price"])/xa <= 1.414 and
            _near(cd/xc, 0.786, 0.08)):
            matched.append("CYPHER")
    return {
        "status": "PATTERN_DETECTED" if matched else "NO_CONFIRMED_PATTERN",
        "pattern": matched[0] if matched else None,
        "other_matches": matched[1:],
        "direction": "BULLISH" if bullish else "BEARISH",
        "completion_price": round(d["price"], 2),
        "pivot_indices": [p["index"] for p in (x, a, b, c, d)],
        "ratios": {k: round(v, 4) for k, v in ratios.items()},
        "confirmed_pivots_only": True,
    }


def analyze_harmonic_supply_demand(candles, pivot_left=3, pivot_right=3, zone_lookback=120):
    """Analyze confirmed XABCD patterns, pivot-derived zones and RSI divergence."""
    if not isinstance(candles, list) or len(candles) < 40:
        raise ValueError("At least 40 closed OHLC candles are required")
    rows = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            raise ValueError("Each candle must contain timestamp and OHLC values")
        vals = [float(row[i]) for i in range(1, 5)]
        if any(not math.isfinite(v) or v <= 0 for v in vals):
            raise ValueError("OHLC prices must be finite and positive")
        op, hi, lo, cl = vals
        if hi < max(op, lo, cl) or lo > min(op, hi, cl):
            raise ValueError("Invalid OHLC bounds")
        rows.append((op, hi, lo, cl))
    closes = [r[3] for r in rows]
    rsi = _rsi_series(closes)
    pivots = _pivots(rows, pivot_left, pivot_right)
    harmonic = _harmonic(pivots)
    recent = pivots[-max(2, zone_lookback):]
    supplies, demands = [], []
    for p in recent:
        i = p["index"]
        op, hi, lo, cl = rows[i]
        if p["kind"] == "H":
            lower, upper, kind = min(op, cl), hi, "SUPPLY"
        else:
            lower, upper, kind = lo, max(op, cl), "DEMAND"
        zone = {"type": kind, "lower": round(lower, 2), "upper": round(upper, 2),
                "pivot_index": i, "distance_pct": round((min(abs(closes[-1]-lower), abs(closes[-1]-upper))/closes[-1])*100, 3)}
        (supplies if kind == "SUPPLY" else demands).append(zone)
    price = closes[-1]
    active_supply = next((z for z in reversed(supplies) if z["lower"] <= price <= z["upper"]), None)
    active_demand = next((z for z in reversed(demands) if z["lower"] <= price <= z["upper"]), None)
    nearest_supply = min(supplies, key=lambda z: z["distance_pct"]) if supplies else None
    nearest_demand = min(demands, key=lambda z: z["distance_pct"]) if demands else None
    lows = [p for p in pivots if p["kind"] == "L"][-2:]
    highs = [p for p in pivots if p["kind"] == "H"][-2:]
    bullish_div = bool(len(lows) == 2 and lows[-1]["price"] < lows[-2]["price"] and
                       rsi[lows[-1]["index"]] > rsi[lows[-2]["index"]])
    bearish_div = bool(len(highs) == 2 and highs[-1]["price"] > highs[-2]["price"] and
                       rsi[highs[-1]["index"]] < rsi[highs[-2]["index"]])
    divergence = "BULLISH" if bullish_div else "BEARISH" if bearish_div else "NONE"
    return {
        "mode": "CLOSED_CANDLE_RESEARCH_ONLY",
        "harmonic": harmonic,
        "supply_demand": {
            "status": "IN_DEMAND_ZONE" if active_demand else "IN_SUPPLY_ZONE" if active_supply else "BETWEEN_ZONES",
            "nearest_demand": nearest_demand,
            "nearest_supply": nearest_supply,
            "active_demand": active_demand,
            "active_supply": active_supply,
            "zones_are_pivot_estimates": True,
        },
        "divergence": {
            "indicator": "RSI14",
            "signal": divergence,
            "bullish": bullish_div,
            "bearish": bearish_div,
            "rsi14": round(rsi[-1], 2),
            "confirmed_pivots_only": True,
        },
        "paper_only": True,
        "live_execution_enabled": False,
        "limitations": [
            "Harmonic ratios use approximate tolerances and require independent visual/backtest validation.",
            "Supply and demand zones are pivot-candle estimates, not verified institutional orders or order-book liquidity.",
            "RSI divergence is calculated only from confirmed swing pivots and can appear late.",
            "No signal is a forecast or a trading instruction.",
        ],
    }
