"""Conservative, close-only strategy comparison with a chronological holdout.

Signals use only completed candles. Orders are simulated at the following close.
This module is research-only and never connects to an exchange.
"""
import math


def _ema(values, period):
    alpha = 2.0 / (period + 1)
    out = []
    current = float(values[0])
    for value in values:
        current = alpha * float(value) + (1 - alpha) * current
        out.append(current)
    return out


def _rsi(values, period=14):
    result = [None] * len(values)
    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    if avg_loss == 0:
        result[period] = 100.0 if avg_gain else 50.0
    else:
        result[period] = 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def _signals(prices):
    ema_fast = _ema(prices, 12)
    ema_slow = _ema(prices, 26)
    rsi = _rsi(prices, 14)
    sma20 = [None] * len(prices)
    sma50 = [None] * len(prices)
    for i in range(19, len(prices)):
        sma20[i] = sum(prices[i - 19:i + 1]) / 20
    for i in range(49, len(prices)):
        sma50[i] = sum(prices[i - 49:i + 1]) / 50

    result = {"sma_trend": [], "ema_trend": [], "rsi_momentum": []}
    for i, price in enumerate(prices):
        result["sma_trend"].append(
            bool(sma20[i] is not None and sma50[i] is not None
                 and price > sma20[i] > sma50[i])
        )
        result["ema_trend"].append(bool(ema_fast[i] > ema_slow[i] and price > ema_slow[i]))
        result["rsi_momentum"].append(
            bool(rsi[i] is not None and 50 < rsi[i] < 70 and price > ema_slow[i])
        )
    return result


def _simulate(prices, signals, start, end, fee=0.001, slippage=0.0005):
    cash = 1000.0
    units = 0.0
    entry_value = 0.0
    trades = []
    peak = cash
    max_dd = 0.0
    for i in range(max(start, 1), end):
        # signal[i-1] only; fill at current close, with 25% of available equity.
        want_long = signals[i - 1]
        if want_long and units == 0:
            allocation = cash * 0.25
            fill = prices[i] * (1 + slippage)
            fee_paid = allocation * fee
            units = (allocation - fee_paid) / fill
            cash -= allocation
            entry_value = allocation
        elif not want_long and units > 0:
            fill = prices[i] * (1 - slippage)
            proceeds = units * fill
            proceeds -= proceeds * fee
            pnl = proceeds - entry_value
            cash += proceeds
            trades.append(pnl)
            units = 0.0
            entry_value = 0.0
        equity = cash + units * prices[i]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)
    # Report net liquidation value, including estimated exit fee and slippage
    # for any position still open at the end of this evaluation window.
    if units > 0:
        estimated_exit = units * prices[end - 1] * (1 - slippage)
        estimated_exit -= estimated_exit * fee
        final_equity = cash + estimated_exit
    else:
        final_equity = cash
    wins = sum(1 for x in trades if x > 0)
    gp = sum(x for x in trades if x > 0)
    gl = -sum(x for x in trades if x < 0)
    return {
        "return_pct": round((final_equity / 1000 - 1) * 100, 2),
        "final_equity_usd": round(final_equity, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "closed_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(gp / gl, 2) if gl else (None if gp else 0.0),
        "open_position": units > 0,
    }


def run_strategy_lab(prices, fee=0.001, slippage=0.0005):
    if len(prices) < 120:
        raise ValueError("At least 120 prices are required for strategy holdout testing")
    if any(isinstance(p, bool) or not isinstance(p, (int, float))
           or not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError("Prices must be finite positive numbers")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    split = int(len(prices) * 0.7)
    signals = _signals(prices)
    results = {}
    # Three chronological evaluation windows after the initial warm-up.
    # These are fixed-rule rolling windows, not parameter re-optimization.
    walk_start = max(50, len(prices) // 2)
    window_edges = [
        walk_start + ((len(prices) - walk_start) * k) // 3
        for k in range(4)
    ]
    for name, values in signals.items():
        windows = []
        for fold in range(3):
            start = window_edges[fold]
            end = window_edges[fold + 1]
            if end > start:
                windows.append({
                    "window": fold + 1,
                    "start_index": start,
                    "end_index_exclusive": end,
                    "metrics": _simulate(prices, values, start, end, fee, slippage),
                })
        returns = [item["metrics"]["return_pct"] for item in windows]
        results[name] = {
            "in_sample": _simulate(prices, values, 50, split, fee, slippage),
            "out_of_sample": _simulate(prices, values, split, len(prices), fee, slippage),
            "walk_forward_windows": windows,
            "worst_window_return_pct": min(returns) if returns else None,
        }

    # Buy-and-hold benchmark over exactly the same out-of-sample window.
    # Mark-to-market drawdown uses spot value; final return includes exit costs.
    start_price = float(prices[split]) * (1 + slippage)
    entry_fee = 1000.0 * fee
    benchmark_units = (1000.0 - entry_fee) / start_price
    benchmark_peak = 1000.0
    benchmark_max_dd = 0.0
    for price in prices[split:]:
        marked_equity = benchmark_units * float(price)
        benchmark_peak = max(benchmark_peak, marked_equity)
        if benchmark_peak > 0:
            benchmark_max_dd = max(
                benchmark_max_dd,
                (benchmark_peak - marked_equity) / benchmark_peak * 100,
            )
    benchmark_exit = benchmark_units * float(prices[-1]) * (1 - slippage)
    benchmark_equity = benchmark_exit - benchmark_exit * fee
    benchmark_pnl = benchmark_equity - 1000.0
    results["buy_and_hold"] = {
        "out_of_sample": {
            "return_pct": round((benchmark_equity / 1000.0 - 1) * 100, 2),
            "final_equity_usd": round(benchmark_equity, 2),
            "max_drawdown_pct": round(benchmark_max_dd, 2),
            "closed_trades": 1,
            "win_rate_pct": 100.0 if benchmark_pnl > 0 else 0.0,
            "profit_factor": None,
            "open_position": False,
            "fees_and_slippage_included": True,
        }
    }
    return {
        "mode": "FIXED_RULE_CHRONOLOGICAL_HOLDOUT",
        "sample_count": len(prices),
        "split_index": split,
        "in_sample_fraction_pct": 70,
        "out_of_sample_fraction_pct": 30,
        "execution": "Previous completed close signal; next close fill; 25% equity allocation; fee and slippage applied.",
        "walk_forward_note": "Three chronological fixed-rule evaluation windows are reported independently; parameters are not retuned between windows.",
        "selection_warning": "No strategy is declared a winner from these tests alone. Require positive out-of-sample evidence across multiple market regimes and longer periods before considering deployment.",
        "strategies": results,
    }
