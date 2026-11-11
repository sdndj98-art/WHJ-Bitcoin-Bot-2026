"""Slow Bitcoin time-series momentum research lab (daily close-only).

Signals are formed at a completed daily close and executed at the next close.
This module is isolated research code: it does not connect to exchanges,
modify paper ledgers, or place orders.
"""
import math

DEFAULT_LOOKBACKS = (56, 84, 112)  # 8, 12 and 16 weeks in daily bars
INITIAL_EQUITY = 1000.0
ALLOCATION_FRACTION = 0.25


def momentum_signals(closes, lookback):
    """Long/cash signal: current close exceeds close N daily bars earlier."""
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    if not isinstance(closes, (list, tuple)) or len(closes) <= lookback:
        raise ValueError("closes must contain more observations than lookback")
    signals = [False] * len(closes)
    for i in range(lookback, len(closes)):
        signals[i] = float(closes[i]) > float(closes[i - lookback])
    return signals


def _validate(closes, fee, slippage, lookbacks):
    if not isinstance(closes, (list, tuple)) or len(closes) < 160:
        raise ValueError("At least 160 daily closes are required")
    for price in closes:
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise ValueError("Prices must be numeric")
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Prices must be finite and positive")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")
    if not lookbacks or len(set(lookbacks)) != len(lookbacks):
        raise ValueError("lookbacks must be non-empty and unique")
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 1 for x in lookbacks):
        raise ValueError("lookbacks must be positive integers")
    if max(lookbacks) >= int(len(closes) * 0.7):
        raise ValueError("lookback leaves too little in-sample history")


def _simulate(closes, signals, start, end, fee, slippage):
    cash = INITIAL_EQUITY
    units = 0.0
    entry_cost = 0.0
    closed = []
    peak = INITIAL_EQUITY
    max_drawdown = 0.0

    for i in range(max(start, 1), end):
        # Only yesterday's completed signal is actionable at today's close.
        if signals[i - 1] and units == 0:
            allocation = cash * ALLOCATION_FRACTION
            fill = float(closes[i]) * (1.0 + slippage)
            fee_paid = allocation * fee
            units = (allocation - fee_paid) / fill
            cash -= allocation
            entry_cost = allocation
        elif not signals[i - 1] and units > 0:
            fill = float(closes[i]) * (1.0 - slippage)
            proceeds = units * fill
            proceeds -= proceeds * fee
            closed.append(proceeds - entry_cost)
            cash += proceeds
            units = 0.0
            entry_cost = 0.0

        if units:
            liquidation = units * float(closes[i]) * (1.0 - slippage)
            liquidation -= liquidation * fee
            equity = cash + liquidation
        else:
            equity = cash
        peak = max(peak, equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)

    if units:
        liquidation = units * float(closes[end - 1]) * (1.0 - slippage)
        liquidation -= liquidation * fee
        final_equity = cash + liquidation
    else:
        final_equity = cash

    wins = sum(pnl > 0 for pnl in closed)
    gross_profit = sum(pnl for pnl in closed if pnl > 0)
    gross_loss = -sum(pnl for pnl in closed if pnl < 0)
    realized_pnl = sum(closed)
    if units:
        unrealized_net_liquidation_pnl = liquidation - entry_cost
    else:
        unrealized_net_liquidation_pnl = 0.0
    closed_trade_profit_factor = (
        round(gross_profit / gross_loss, 4)
        if gross_loss else (None if gross_profit else 0.0)
    )
    close_to_close_drawdown = round(max_drawdown, 4)
    return {
        "return_pct": round((final_equity / INITIAL_EQUITY - 1.0) * 100.0, 4),
        "final_equity_usd": round(final_equity, 4),
        "final_net_liquidation_equity_usd": round(final_equity, 4),
        "max_close_to_close_drawdown_pct": close_to_close_drawdown,
        # Compatibility alias; this remains close-to-close, never intraday OHLC drawdown.
        "max_drawdown_pct": close_to_close_drawdown,
        "drawdown_measurement": "close_to_close_net_liquidation",
        "closed_trades": len(closed),
        "closed_trade_pnls_usd": [round(pnl, 8) for pnl in closed],
        "win_rate_pct": round(wins / len(closed) * 100.0, 4) if closed else 0.0,
        "closed_trade_profit_factor": closed_trade_profit_factor,
        # Compatibility alias; PF intentionally describes completed trades only.
        "profit_factor": closed_trade_profit_factor,
        "realized_pnl_usd": round(realized_pnl, 4),
        "open_position_count": int(bool(units)),
        "unrealized_net_liquidation_pnl_usd": round(unrealized_net_liquidation_pnl, 4),
        "open_position_at_window_end": bool(units),
    }


def periodic_net_returns(closes, signals, start, end, fee=0.001, slippage=0.0005,
                        allocation_fraction=ALLOCATION_FRACTION):
    """Return aligned net-liquidation returns under the slow lab's exact fill rules.

    Signal at close t is executed at close t+1. Returns include entry/exit
    friction and mark any open position to net liquidation at each close.
    This produces a return stream for diagnostics, not a separate strategy.
    """
    if not isinstance(closes, (list, tuple)) or len(closes) < 2:
        raise ValueError("At least two closes are required")
    if not isinstance(signals, (list, tuple)) or len(signals) != len(closes):
        raise ValueError("signals must align with closes")
    if any(type(value) is not bool for value in signals):
        raise ValueError("signals must contain booleans")
    for price in closes:
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError("closes must be finite positive prices")
    if isinstance(start, bool) or not isinstance(start, int) or start < 1:
        raise ValueError("start must be an integer >= 1")
    if isinstance(end, bool) or not isinstance(end, int) or end > len(closes) or end <= start:
        raise ValueError("end must be an integer greater than start and <= data length")
    if not (0 <= fee < 1 and 0 <= slippage < 1):
        raise ValueError("fee and slippage must be between 0 and 1")
    if not (0 < allocation_fraction <= ALLOCATION_FRACTION):
        raise ValueError("allocation may not exceed the incumbent research cap")

    cash = INITIAL_EQUITY
    units = 0.0
    previous_equity = INITIAL_EQUITY
    returns = []
    for index in range(start, end):
        if signals[index - 1] and units == 0:
            allocation = cash * allocation_fraction
            fill = float(closes[index]) * (1.0 + slippage)
            units = allocation * (1.0 - fee) / fill
            cash -= allocation
        elif not signals[index - 1] and units > 0:
            fill = float(closes[index]) * (1.0 - slippage)
            proceeds = units * fill * (1.0 - fee)
            cash += proceeds
            units = 0.0
        if units > 0:
            liquidation = units * float(closes[index]) * (1.0 - slippage)
            liquidation *= 1.0 - fee
            equity = cash + liquidation
        else:
            equity = cash
        if equity <= 0 or previous_equity <= 0:
            raise ValueError("Net liquidation equity became non-positive")
        returns.append(equity / previous_equity - 1.0)
        previous_equity = equity
    return returns


def _attach_matched_benchmark(candidate_metrics, benchmark_metrics):
    """Attach excess returns only after verifying identical evaluation boundaries."""
    if len(candidate_metrics) != len(benchmark_metrics):
        raise ValueError("Candidate and benchmark window counts do not match")
    for candidate, benchmark in zip(candidate_metrics, benchmark_metrics):
        if (candidate.get("start_index") != benchmark.get("start_index")
                or candidate.get("end_index_exclusive") != benchmark.get("end_index_exclusive")):
            raise ValueError("Candidate and benchmark windows are not aligned")
        candidate["matched_benchmark_return_pct"] = benchmark["return_pct"]
        candidate["excess_return_pct_points"] = round(
            candidate["metrics"]["return_pct"] - benchmark["return_pct"], 4
        ) if "metrics" in candidate else round(
            candidate["return_pct"] - benchmark["return_pct"], 4
        )


def evaluate_slow_momentum(closes, fee=0.001, slippage=0.0005,
                           lookbacks=DEFAULT_LOOKBACKS):
    """Evaluate fixed 8/12/16-week candidates on chronological holdout windows.

    Returns normal-cost and 2x/3x cost results. The three OOS slices are
    chronological subperiods, not rolling walk-forward retraining. No parameters
    are selected or retuned using the holdout. Buy-and-hold uses the same 25%
    initial allocation.
    """
    lookbacks = tuple(lookbacks)
    _validate(closes, fee, slippage, lookbacks)
    prices = [float(x) for x in closes]
    split = int(len(prices) * 0.70)
    edges = [split + ((len(prices) - split) * k) // 3 for k in range(4)]
    results = {}

    for lookback in lookbacks:
        signals = momentum_signals(prices, lookback)
        windows = []
        for fold in range(3):
            start, end = edges[fold], edges[fold + 1]
            windows.append({
                "window": fold + 1,
                "start_index": start,
                "end_index_exclusive": end,
                "metrics": _simulate(prices, signals, start, end, fee, slippage),
            })
        results[str(lookback)] = {
            "lookback_days": lookback,
            "in_sample": _simulate(prices, signals, 1, split, fee, slippage),
            "out_of_sample": _simulate(prices, signals, split, len(prices), fee, slippage),
            "oos_subperiods": windows,
            # Deprecated compatibility alias; these are fixed OOS slices, not walk-forward retraining.
            "walk_forward_windows": windows,
        }

    benchmark = []
    for start, end in ((split, len(prices)), *[(edges[k], edges[k + 1]) for k in range(3)]):
        # Buy at the first close of the evaluation window, then hold to its end.
        allocation = INITIAL_EQUITY * ALLOCATION_FRACTION
        entry = prices[start] * (1.0 + slippage)
        units = (allocation - allocation * fee) / entry
        proceeds = units * prices[end - 1] * (1.0 - slippage)
        proceeds -= proceeds * fee
        equity = INITIAL_EQUITY - allocation + proceeds
        benchmark.append({
            "start_index": start, "end_index_exclusive": end,
            "return_pct": round((equity / INITIAL_EQUITY - 1.0) * 100.0, 4),
            "final_equity_usd": round(equity, 4),
        })

    for candidate in results.values():
        _attach_matched_benchmark(candidate["oos_subperiods"], benchmark[1:])
        candidate["matched_buy_and_hold_return_pct"] = benchmark[0]["return_pct"]
        candidate["excess_return_vs_buy_and_hold_pct_points"] = round(
            candidate["out_of_sample"]["return_pct"] - benchmark[0]["return_pct"], 4
        )

    stress = {
        "2x": evaluate_cost_stress(prices, fee, slippage, lookbacks, multiplier=2.0),
        "3x": evaluate_cost_stress(prices, fee, slippage, lookbacks, multiplier=3.0),
    }
    return {
        "mode": "DAILY_CLOSE_SLOW_TSMOM_FIXED_RULE_RESEARCH",
        "signal_rule": "Long when close[t] > close[t-lookback]; otherwise cash.",
        "execution_rule": "Signal from completed close t; simulated fill at close t+1.",
        "allocation_fraction": ALLOCATION_FRACTION,
        "split_index": split,
        "in_sample_fraction_pct": 70,
        "out_of_sample_fraction_pct": 30,
        "costs": {"fee_per_side": fee, "slippage_per_side": slippage},
        "buy_and_hold_25pct": {
            "out_of_sample": benchmark[0],
            "oos_subperiods": benchmark[1:],
            # Deprecated compatibility alias; these are fixed chronological slices.
            "walk_forward_windows": benchmark[1:],
        },
        "candidates": results,
        "cost_stress": stress,
        "research_only": True,
        "execution_enabled": False,
        "selection_warning": "No winner is selected; all lookbacks are reported and the holdout must not be used for tuning.",
    }


def evaluate_cost_stress(closes, fee, slippage, lookbacks, multiplier=2.0):
    """Re-run candidates and matched buy-and-hold at multiplied costs."""
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or multiplier < 1:
        raise ValueError("cost multiplier must be a number >= 1")
    stressed_fee = min(fee * multiplier, 0.999999)
    stressed_slippage = min(slippage * multiplier, 0.999999)
    split = int(len(closes) * 0.70)
    edges = [split + ((len(closes) - split) * k) // 3 for k in range(4)]
    result = {}
    for lookback in lookbacks:
        signals = momentum_signals(closes, lookback)
        result[str(lookback)] = {
            "out_of_sample": _simulate(
                closes, signals, split, len(closes), stressed_fee, stressed_slippage
            ),
            "walk_forward_windows": [
                {
                    "start_index": edges[k],
                    "end_index_exclusive": edges[k + 1],
                    "metrics": _simulate(
                        closes, signals, edges[k], edges[k + 1],
                        stressed_fee, stressed_slippage
                    ),
                }
                for k in range(3)
            ],
        }

    def buy_and_hold(start, end):
        allocation = INITIAL_EQUITY * ALLOCATION_FRACTION
        entry = closes[start] * (1.0 + stressed_slippage)
        units = allocation * (1.0 - stressed_fee) / entry
        proceeds = units * closes[end - 1] * (1.0 - stressed_slippage)
        proceeds *= 1.0 - stressed_fee
        equity = INITIAL_EQUITY - allocation + proceeds
        return {
            "return_pct": round((equity / INITIAL_EQUITY - 1.0) * 100.0, 4),
            "final_equity_usd": round(equity, 4),
        }

    stress_benchmark_windows = [
        buy_and_hold(edges[k], edges[k + 1]) for k in range(3)
    ]
    for candidate in result.values():
        _attach_matched_benchmark(
            candidate["walk_forward_windows"],
            [
                {"start_index": edges[k], "end_index_exclusive": edges[k + 1],
                 "return_pct": stress_benchmark_windows[k]["return_pct"]}
                for k in range(3)
            ],
        )
        candidate["oos_subperiods"] = candidate["walk_forward_windows"]
        candidate["matched_buy_and_hold_return_pct"] = buy_and_hold(
            split, len(closes)
        )["return_pct"]
        candidate["excess_return_vs_buy_and_hold_pct_points"] = round(
            candidate["out_of_sample"]["return_pct"]
            - candidate["matched_buy_and_hold_return_pct"], 4
        )

    return {
        "multiplier": multiplier,
        "fee_per_side": stressed_fee,
        "slippage_per_side": stressed_slippage,
        "matched_buy_and_hold": {
            "out_of_sample": buy_and_hold(split, len(closes)),
            "oos_subperiods": [
                buy_and_hold(edges[k], edges[k + 1]) for k in range(3)
            ],
            # Deprecated compatibility alias; these are fixed chronological slices.
            "walk_forward_windows": [
                buy_and_hold(edges[k], edges[k + 1]) for k in range(3)
            ],
        },
        "candidates": result,
    }
