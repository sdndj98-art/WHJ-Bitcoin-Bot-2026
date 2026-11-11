"""Causal CUSUM event sampling and triple-barrier labels for research.

Labels are diagnostics for future supervised-learning experiments only. They
must not be used as trading signals or fed into existing paper accounts.
"""
import math


def _log_returns(closes):
    returns = [0.0]
    for previous, current in zip(closes, closes[1:]):
        if previous <= 0 or current <= 0:
            raise ValueError("prices must be positive")
        returns.append(math.log(float(current) / float(previous)))
    return returns


def _validate_prices(closes, minimum=3):
    if not isinstance(closes, (list, tuple)) or len(closes) < minimum:
        raise ValueError(f"at least {minimum} closes are required")
    for price in closes:
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("prices must be numeric")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("prices must be finite and positive")


def cusum_event_indices(closes, volatility_lookback=20, threshold_multiplier=1.0):
    """Return symmetric CUSUM event indices using past-only rolling volatility.

    At index t, the threshold is estimated from returns ending at t-1;
    the return at t can trigger an event but cannot change its own threshold.
    """
    _validate_prices(closes, minimum=volatility_lookback + 2)
    if isinstance(volatility_lookback, bool) or not isinstance(volatility_lookback, int) or volatility_lookback < 2:
        raise ValueError("volatility_lookback must be an integer >= 2")
    if not isinstance(threshold_multiplier, (int, float)) or isinstance(threshold_multiplier, bool):
        raise ValueError("threshold_multiplier must be numeric")
    if not math.isfinite(threshold_multiplier) or threshold_multiplier <= 0:
        raise ValueError("threshold_multiplier must be finite and positive")

    returns = _log_returns(closes)
    positive_sum = 0.0
    negative_sum = 0.0
    events = []
    for i in range(volatility_lookback + 1, len(returns)):
        history = returns[i - volatility_lookback:i]
        mean = sum(history) / len(history)
        variance = sum((value - mean) ** 2 for value in history) / len(history)
        threshold = threshold_multiplier * math.sqrt(variance)
        if threshold <= 0:
            continue
        positive_sum = max(0.0, positive_sum + returns[i])
        negative_sum = min(0.0, negative_sum + returns[i])
        if positive_sum >= threshold or negative_sum <= -threshold:
            events.append(i)
            positive_sum = 0.0
            negative_sum = 0.0
    return events


def trailing_volatility(closes, lookback=20):
    """Causal close-to-close log-return volatility aligned to each close."""
    _validate_prices(closes, minimum=lookback + 2)
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
        raise ValueError("lookback must be an integer >= 2")
    returns = _log_returns(closes)
    values = [None] * len(closes)
    for i in range(lookback + 1, len(closes)):
        history = returns[i - lookback:i]
        mean = sum(history) / len(history)
        variance = sum((value - mean) ** 2 for value in history) / len(history)
        values[i] = math.sqrt(variance)
    return values


def triple_barrier_labels(closes, event_indices, volatility,
                          profit_take=1.0, stop_loss=1.0, max_holding=10):
    """Label each event after next-close entry; return {-1, 0, +1} labels.

    Barriers are volatility-scaled simple returns from the next close after
    the event. The event's volatility must be available at event time.
    """
    _validate_prices(closes, minimum=3)
    if len(volatility) != len(closes):
        raise ValueError("volatility must align with closes")
    if not isinstance(max_holding, int) or isinstance(max_holding, bool) or max_holding < 1:
        raise ValueError("max_holding must be a positive integer")
    for value in (profit_take, stop_loss):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("barrier multipliers must be finite and positive")

    labels = []
    seen = set()
    for event in event_indices:
        if isinstance(event, bool) or not isinstance(event, int) or event < 0 or event >= len(closes) - 2:
            continue
        if event in seen:
            raise ValueError("event indices must be unique")
        seen.add(event)
        sigma = volatility[event]
        if sigma is None or isinstance(sigma, bool) or not isinstance(sigma, (int, float)) or not math.isfinite(sigma) or sigma <= 0:
            continue

        entry_index = event + 1
        entry_price = float(closes[entry_index])
        upper = profit_take * sigma
        lower = -stop_loss * sigma
        end_limit = min(len(closes) - 1, entry_index + max_holding)
        label = 0
        end_index = end_limit
        for i in range(entry_index + 1, end_limit + 1):
            move = float(closes[i]) / entry_price - 1.0
            if move >= upper:
                label, end_index = 1, i
                break
            if move <= lower:
                label, end_index = -1, i
                break
        else:
            final_move = float(closes[end_limit]) / entry_price - 1.0
            label = 1 if final_move > 0 else (-1 if final_move < 0 else 0)

        labels.append({
            "event_index": event,
            "entry_index": entry_index,
            "end_index": end_index,
            "label": label,
            "entry_price": round(entry_price, 10),
            "end_price": round(float(closes[end_index]), 10),
            "realized_return_pct": round((float(closes[end_index]) / entry_price - 1.0) * 100.0, 6),
            "profit_barrier_return": upper,
            "stop_barrier_return": lower,
        })
    return labels


def purged_past_event_indices(labels, test_start_index, embargo_bars=0):
    """Keep only past training labels ending before test start minus embargo."""
    if isinstance(test_start_index, bool) or not isinstance(test_start_index, int) or test_start_index < 0:
        raise ValueError("test_start_index must be a non-negative integer")
    if isinstance(embargo_bars, bool) or not isinstance(embargo_bars, int) or embargo_bars < 0:
        raise ValueError("embargo_bars must be a non-negative integer")
    cutoff = test_start_index - embargo_bars
    return [
        index for index, item in enumerate(labels)
        if item["event_index"] < test_start_index and item["end_index"] < cutoff
    ]
