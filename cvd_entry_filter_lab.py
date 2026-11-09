"""Causal research comparison for EMA50/200 with a Kraken CVD entry filter.

Research only. Inputs must be aligned completed candles and independently
continuity-verified CVD bars from cvd_candle_research. No exchange orders.
"""
import math

from strategy_lab import _signals, _simulate


def build_cvd_gated_signals(baseline_signals, cvd_bars, mode="flow_confirmation"):
    """Gate new baseline entries with same-bar completed CVD; preserve baseline exits.

    A position remains open while the baseline remains active, even if later CVD
    bars are unavailable or bearish. CVD is consulted only when entering from flat.
    The simulator consumes signal[i-1] and fills at close[i], avoiding same-close
    execution and preventing future CVD events from influencing earlier decisions.
    """
    if mode not in ("flow_confirmation", "flow_or_absorption"):
        raise ValueError("unsupported CVD filter mode")
    if not isinstance(baseline_signals, list) or not isinstance(cvd_bars, list):
        raise ValueError("baseline_signals and cvd_bars must be lists")
    if len(baseline_signals) != len(cvd_bars) or not baseline_signals:
        raise ValueError("baseline signals and CVD bars must have equal non-zero lengths")
    if not all(isinstance(value, bool) for value in baseline_signals):
        raise ValueError("baseline signals must be boolean")
    output = []
    in_position = False
    for baseline, flow in zip(baseline_signals, cvd_bars):
        if not isinstance(flow, dict):
            raise ValueError("each CVD bar must be an object")
        available = flow.get("available") is True
        bullish = flow.get("bullish_flow_confirmation") is True
        if mode == "flow_or_absorption":
            bullish = bullish or flow.get("bullish_absorption_divergence") is True
        if not baseline:
            in_position = False
        elif not in_position and available and bullish:
            in_position = True
        output.append(bool(in_position))
    return output


def _benchmark_25pct(prices, start, end, fee, slippage):
    allocation = 250.0
    cash = 1000.0 - allocation
    fill = float(prices[start]) * (1.0 + slippage)
    units = allocation * (1.0 - fee) / fill
    peak = 1000.0
    max_drawdown = 0.0
    for price in prices[start:end]:
        liquidation = units * float(price) * (1.0 - slippage)
        liquidation *= 1.0 - fee
        equity = cash + liquidation
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    final_exit = units * float(prices[end - 1]) * (1.0 - slippage)
    final_exit *= 1.0 - fee
    final_equity = cash + final_exit
    return {
        "return_pct": round((final_equity / 1000.0 - 1.0) * 100.0, 2),
        "final_equity_usd": round(final_equity, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "allocation_fraction": 0.25,
        "fees_and_slippage_included": True,
    }


def run_cvd_entry_filter_lab(prices, cvd_bars, fee=0.001, slippage=0.0005):
    """Compare EMA50/200 baseline with two predeclared CVD entry gates.

    Uses the same 70/30 chronological split, three non-overlapping OOS windows,
    25% allocation, next-close fills, fees, slippage and simulator as strategy_lab.
    This is a diagnostic comparison, not an automatic promotion decision.
    """
    if not isinstance(prices, list) or len(prices) < 500:
        raise ValueError("At least 500 hourly prices are required")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0 for value in prices):
        raise ValueError("prices must be finite positive numbers")
    if not isinstance(cvd_bars, list) or len(cvd_bars) != len(prices):
        raise ValueError("one aligned CVD bar is required for every price candle")
    if (isinstance(fee, bool) or isinstance(slippage, bool)
            or not isinstance(fee, (int, float)) or not isinstance(slippage, (int, float))
            or not math.isfinite(fee) or not math.isfinite(slippage)
            or not 0 <= fee < 1 or not 0 <= slippage < 1):
        raise ValueError("fee and slippage must be finite values in [0, 1)")

    split = int(len(prices) * 0.7)
    edges = [split + ((len(prices) - split) * k) // 3 for k in range(4)]
    baseline = _signals(prices)["ema50_200_regime"]
    signal_sets = {
        "ema50_200_baseline": baseline,
        "cvd_flow_entry_filter": build_cvd_gated_signals(
            baseline, cvd_bars, "flow_confirmation"
        ),
        "cvd_flow_or_absorption_entry_filter": build_cvd_gated_signals(
            baseline, cvd_bars, "flow_or_absorption"
        ),
    }
    strategies = {}
    for name, signals in signal_sets.items():
        windows = [
            {
                "window": fold + 1,
                "start_index": edges[fold],
                "end_index_exclusive": edges[fold + 1],
                "metrics": _simulate(prices, signals, edges[fold], edges[fold + 1], fee, slippage),
            }
            for fold in range(3) if edges[fold + 1] > edges[fold]
        ]
        strategies[name] = {
            "in_sample": _simulate(prices, signals, 50, split, fee, slippage),
            "out_of_sample": _simulate(prices, signals, split, len(prices), fee, slippage),
            "walk_forward_windows": windows,
            "worst_window_return_pct": min(
                item["metrics"]["return_pct"] for item in windows
            ) if windows else None,
        }

    benchmark = _benchmark_25pct(prices, split, len(prices), fee, slippage)
    available = sum(1 for item in cvd_bars if item.get("available") is True)
    return {
        "mode": "CVD_ENTRY_FILTER_CAUSAL_RESEARCH_ONLY",
        "baseline": "ema50_200_regime",
        "sample_count": len(prices),
        "split_index": split,
        "cvd_data_quality": {
            "available_bars": available,
            "total_bars": len(cvd_bars),
            "availability_pct": round(available / len(cvd_bars) * 100.0, 2),
            "unavailable_bars_fail_closed_for_new_entries": True,
        },
        "execution": "Completed candle signal; next candle close fill; 25% allocation; fees and slippage included.",
        "benchmark_25pct_buy_and_hold": benchmark,
        "strategies": strategies,
        "research_only": True,
        "execution_enabled": False,
        "promotion_status": "NOT_EVALUATED",
        "limitations": [
            "CVD is venue-specific aggressor-side volume, not order-book depth or consolidated market flow.",
            "Continuity must be independently verified before a CVD bar is marked available.",
            "CVD gates entries only; exits remain governed by the EMA50/200 baseline.",
            "Unavailable CVD bars block new entries but do not force exits from existing positions.",
            "The comparison requires aligned completed candles and does not infer missing trades.",
            "A positive comparison is not proof of a durable edge; fixed qualification gates and forward paper evidence remain mandatory.",
        ],
    }
