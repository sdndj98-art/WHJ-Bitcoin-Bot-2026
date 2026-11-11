"""Isolated CUSUM + triple-barrier logistic research candidate.

Uses only completed BTC-USD spot bars, purged historical labels, and a
fixed interpretable logistic baseline. This module has no exchange, paper
account, wallet, schedule, or order-path imports.
"""
import math

from cusum_triple_barrier_lab import cusum_event_indices, trailing_volatility

INITIAL_EQUITY = 1000.0
CUSUM_LOOKBACK = 24
CUSUM_THRESHOLD_MULTIPLIER = 1.0
BARRIER_HORIZON = 24
PROFIT_TAKE_VOL_MULTIPLIER = 1.5
STOP_LOSS_VOL_MULTIPLIER = 1.0
PURGE_EMBARGO_BARS = 24
MIN_TRAINING_LABELS = 50
PROBABILITY_THRESHOLD = 0.55
ALLOCATION_FRACTION = 0.25
FEATURE_NAMES = ("ret_1", "ret_3", "ret_6", "ret_12", "ret_24", "sigma_24", "ema200_distance")


def _validate_bars(bars):
    if not isinstance(bars, (list, tuple)) or len(bars) < 300:
        raise ValueError("At least 300 OHLCV bars are required")
    clean = []
    previous_timestamp = None
    for i, row in enumerate(bars):
        if not isinstance(row, dict):
            raise ValueError("Each bar must be a mapping")
        values = [row.get(k) for k in ("open", "high", "low", "close")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("OHLC values must be finite positive numbers")
        o, h, l, c = map(float, values)
        if h < max(o, l, c) or l > min(o, h, c):
            raise ValueError("Invalid OHLC candle at index %d" % i)
        timestamp = row.get("timestamp")
        if timestamp is not None:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
                raise ValueError("timestamps must be finite numeric values")
            if previous_timestamp is not None and timestamp - previous_timestamp != 3600000:
                raise ValueError("Candles must be contiguous hourly bars")
            previous_timestamp = timestamp
        clean.append({"open": o, "high": h, "low": l, "close": c})
    return clean


def _log_returns(closes):
    values = [0.0]
    for a, b in zip(closes, closes[1:]):
        values.append(math.log(b / a))
    return values


def _features_by_index(closes, sigma):
    returns = _log_returns(closes)
    ema = [None] * len(closes)
    period = 200
    current = sum(closes[:period]) / period
    ema[period - 1] = current
    alpha = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        current = alpha * closes[i] + (1.0 - alpha) * current
        ema[i] = current
    features = [None] * len(closes)
    for i in range(period, len(closes)):
        if sigma[i] is None:
            continue
        features[i] = [
            returns[i],
            math.log(closes[i] / closes[i - 3]),
            math.log(closes[i] / closes[i - 6]),
            math.log(closes[i] / closes[i - 12]),
            math.log(closes[i] / closes[i - 24]),
            sigma[i],
            closes[i] / ema[i] - 1.0,
        ]
    return features


def _resolve_barrier_exit(bars, event_index, sigma):
    """Resolve a long event from next-open entry; adverse stop wins collisions."""
    entry_index = event_index + 1
    if entry_index + BARRIER_HORIZON >= len(bars):
        return None
    entry = bars[entry_index]["open"]
    scale = sigma * math.sqrt(BARRIER_HORIZON)
    target = entry * math.exp(PROFIT_TAKE_VOL_MULTIPLIER * scale)
    stop = entry * math.exp(-STOP_LOSS_VOL_MULTIPLIER * scale)
    last_bar = entry_index + BARRIER_HORIZON - 1
    for i in range(entry_index, last_bar + 1):
        bar = bars[i]
        if bar["open"] <= stop:
            return {"label": -1, "exit_index": i, "exit_price": bar["open"], "reason": "stop_gap",
                    "entry_index": entry_index, "entry_price": entry}
        if bar["open"] >= target:
            return {"label": 1, "exit_index": i, "exit_price": bar["open"], "reason": "target_gap",
                    "entry_index": entry_index, "entry_price": entry}
        stop_hit = bar["low"] <= stop
        target_hit = bar["high"] >= target
        if stop_hit:
            return {"label": -1, "exit_index": i, "exit_price": stop,
                    "reason": "stop_first_collision" if target_hit else "stop",
                    "entry_index": entry_index, "entry_price": entry}
        if target_hit:
            return {"label": 1, "exit_index": i, "exit_price": target, "reason": "target",
                    "entry_index": entry_index, "entry_price": entry}
    exit_index = last_bar + 1
    exit_price = bars[exit_index]["open"]
    move = exit_price / entry - 1.0
    return {"label": 1 if move > 0 else (-1 if move < 0 else 0),
            "exit_index": exit_index, "exit_price": exit_price, "reason": "time_exit_next_open",
            "entry_index": entry_index, "entry_price": entry}


def _sigmoid(value):
    if value >= 0:
        z = math.exp(-min(value, 700.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -700.0))
    return z / (1.0 + z)


def _fit_logistic(rows, labels, epochs=160, learning_rate=0.08, l2=0.01):
    """Deterministic balanced logistic regression; normalization is train-only."""
    if len(rows) != len(labels) or len(rows) < MIN_TRAINING_LABELS:
        raise ValueError("Insufficient purged training labels")
    positives = sum(1 for y in labels if y == 1)
    negatives = sum(1 for y in labels if y == -1)
    if not positives or not negatives:
        raise ValueError("Training labels must contain both classes")
    width = len(FEATURE_NAMES)
    means = [sum(row[j] for row in rows) / len(rows) for j in range(width)]
    scales = []
    for j in range(width):
        variance = sum((row[j] - means[j]) ** 2 for row in rows) / len(rows)
        scales.append(math.sqrt(variance) or 1.0)
    x = [[(row[j] - means[j]) / scales[j] for j in range(width)] for row in rows]
    weights = [0.0] * (width + 1)
    positive_weight = len(labels) / (2.0 * positives)
    negative_weight = len(labels) / (2.0 * negatives)
    for _ in range(epochs):
        gradient = [0.0] * (width + 1)
        for row, label in zip(x, labels):
            score = weights[0] + sum(weights[j + 1] * row[j] for j in range(width))
            probability = _sigmoid(score)
            target = 1.0 if label == 1 else 0.0
            sample_weight = positive_weight if label == 1 else negative_weight
            error = (probability - target) * sample_weight
            gradient[0] += error
            for j in range(width):
                gradient[j + 1] += error * row[j]
        factor = 1.0 / len(x)
        weights[0] -= learning_rate * gradient[0] * factor
        for j in range(width):
            weights[j + 1] -= learning_rate * (gradient[j + 1] * factor + l2 * weights[j + 1])
    return {"weights": weights, "means": means, "scales": scales,
            "training_labels": len(labels), "positive_labels": positives,
            "negative_labels": negatives}


def _predict_probability(model, row):
    z = model["weights"][0] + sum(
        model["weights"][j + 1] * ((row[j] - model["means"][j]) / model["scales"][j])
        for j in range(len(FEATURE_NAMES))
    )
    return _sigmoid(z)


def _evaluate_trades(bars, selected_events, sigma, fee, slippage):
    cash = INITIAL_EQUITY
    trades = []
    equity_peak = INITIAL_EQUITY
    max_drawdown = 0.0
    next_available_entry = 0
    for event in selected_events:
        entry_index = event["index"] + 1
        if entry_index <= next_available_entry:
            continue
        exit_plan = _resolve_barrier_exit(bars, event["index"], sigma[event["index"]])
        if exit_plan is None:
            continue
        allocation = cash * ALLOCATION_FRACTION
        entry_fill = exit_plan["entry_price"] * (1.0 + slippage)
        units = allocation * (1.0 - fee) / entry_fill
        entry_equity = cash
        cash -= allocation
        for i in range(exit_plan["entry_index"], exit_plan["exit_index"] + 1):
            high_value = cash + units * bars[i]["high"] * (1.0 - slippage) * (1.0 - fee)
            low_value = cash + units * bars[i]["low"] * (1.0 - slippage) * (1.0 - fee)
            equity_peak = max(equity_peak, high_value)
            if equity_peak > 0:
                max_drawdown = max(max_drawdown, (equity_peak - low_value) / equity_peak * 100.0)
        exit_fill = exit_plan["exit_price"] * (1.0 - slippage)
        proceeds = units * exit_fill * (1.0 - fee)
        pnl = proceeds - allocation
        cash += proceeds
        trades.append({
            "event_index": event["index"], "entry_index": exit_plan["entry_index"],
            "exit_index": exit_plan["exit_index"], "probability": round(event["probability"], 6),
            "label": exit_plan["label"], "reason": exit_plan["reason"],
            "net_pnl_usd": round(pnl, 6),
        })
        equity_peak = max(equity_peak, cash)
        if equity_peak > 0:
            max_drawdown = max(max_drawdown, (equity_peak - cash) / equity_peak * 100.0)
        next_available_entry = exit_plan["exit_index"]
    gross_profit = sum(t["net_pnl_usd"] for t in trades if t["net_pnl_usd"] > 0)
    gross_loss = -sum(t["net_pnl_usd"] for t in trades if t["net_pnl_usd"] < 0)
    return {
        "initial_equity_usd": INITIAL_EQUITY,
        "final_equity_usd": round(cash, 6),
        "return_pct": round((cash / INITIAL_EQUITY - 1.0) * 100.0, 4),
        "closed_trades": len(trades),
        "closed_trade_profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if gross_profit else 0.0),
        "max_intrabar_ohlc_envelope_drawdown_pct": round(max_drawdown, 4),
        "trades": trades,
        "execution_enabled": False,
        "research_only": True,
    }


def _purged_training_labels(labeled, oos_start):
    cutoff = oos_start - PURGE_EMBARGO_BARS
    return [
        item for item in labeled
        if item["index"] < oos_start and item["end_index"] < cutoff
        and item["label"] in (-1, 1)
    ]


def _matched_buy_hold(bars, oos_start, oos_end, fee, slippage):
    entry = bars[oos_start + 1]["open"] * (1.0 + slippage)
    exit_price = bars[oos_end - 1]["close"] * (1.0 - slippage)
    allocation = INITIAL_EQUITY * ALLOCATION_FRACTION
    units = allocation * (1.0 - fee) / entry
    final = INITIAL_EQUITY - allocation + units * exit_price * (1.0 - fee)
    return {
        "return_pct": round((final / INITIAL_EQUITY - 1.0) * 100.0, 4),
        "final_equity_usd": round(final, 6),
        "allocation_fraction": ALLOCATION_FRACTION,
        "uninvested_cash_usd": round(INITIAL_EQUITY - allocation, 6),
    }


def evaluate_cusum_fold(bars, oos_start, oos_end, fee=0.001, slippage=0.0005):
    """Fit only on purged pre-fold labels; test events are strictly later."""
    rows = _validate_bars(bars)
    closes = [bar["close"] for bar in rows]
    sigma = trailing_volatility(closes, lookback=CUSUM_LOOKBACK)
    features = _features_by_index(closes, sigma)
    events = cusum_event_indices(
        closes, volatility_lookback=CUSUM_LOOKBACK,
        threshold_multiplier=CUSUM_THRESHOLD_MULTIPLIER,
    )
    if not (300 <= oos_start < oos_end <= len(rows)):
        raise ValueError("Invalid OOS fold boundaries")
    labeled = []
    for event in events:
        if features[event] is None:
            continue
        outcome = _resolve_barrier_exit(rows, event, sigma[event])
        if outcome is not None:
            labeled.append({"index": event, "label": outcome["label"],
                            "end_index": outcome["exit_index"], "features": features[event]})
    training = _purged_training_labels(labeled, oos_start)
    if len(training) < MIN_TRAINING_LABELS:
        return {
            "status": "INSUFFICIENT_EVIDENCE", "training_labels": len(training),
            "oos_events": 0, "trades": 0, "return_pct": 0.0,
            "reason": "Fewer than 50 purged labeled events",
        }
    model = _fit_logistic([x["features"] for x in training], [x["label"] for x in training])
    test_events = []
    for item in labeled:
        if oos_start <= item["index"] < oos_end - BARRIER_HORIZON - 1:
            probability = _predict_probability(model, item["features"])
            if probability >= PROBABILITY_THRESHOLD:
                test_events.append({"index": item["index"], "probability": probability})
    result = _evaluate_trades(rows, test_events, sigma, fee, slippage)
    result["buy_and_hold"] = _matched_buy_hold(rows, oos_start, oos_end, fee, slippage)
    result["cash"] = {"return_pct": 0.0, "final_equity_usd": INITIAL_EQUITY}
    result.update({
        "status": "EVALUATED",
        "training_labels": model["training_labels"],
        "training_positive_labels": model["positive_labels"],
        "training_negative_labels": model["negative_labels"],
        "oos_cusum_events": sum(1 for e in events if oos_start <= e < oos_end),
        "oos_selected_events": len(test_events),
        "probability_threshold": PROBABILITY_THRESHOLD,
        "feature_names": list(FEATURE_NAMES),
        "purge_embargo_bars": PURGE_EMBARGO_BARS,
        "barrier_horizon": BARRIER_HORIZON,
        "profit_take_vol_multiplier": PROFIT_TAKE_VOL_MULTIPLIER,
        "stop_loss_vol_multiplier": STOP_LOSS_VOL_MULTIPLIER,
        "execution": "next_bar_open; gap-aware; same-bar stop-first; time exit next open",
        "allocation_fraction": ALLOCATION_FRACTION,
        "fee_per_side": fee,
        "slippage_per_side": slippage,
    })
    return result
