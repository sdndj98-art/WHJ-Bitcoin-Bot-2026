"""Research-only ER20 filter test for the 50/50 4h + 6h EMA50/EMA200 portfolio.

This module never reads or writes paper-account state and never places orders.
"""
import json
from pathlib import Path

from historical_research import (
    FEE_RATE,
    SLIPPAGE_RATE,
    _ema_series,
    _simulate_equal_weight_multitimeframe,
    aggregate_candles,
    load_two_year_candles,
)


def _efficiency_ratio_series(values, lookback=20):
    """Return (absolute efficiency, signed direction) using closes through each bar."""
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
        raise ValueError("Efficiency lookback must be an integer >= 2")
    if len(values) <= lookback:
        raise ValueError("Not enough values for efficiency ratio")
    ratios = [None] * len(values)
    directions = [None] * len(values)
    for index in range(lookback, len(values)):
        window = [float(value) for value in values[index - lookback:index + 1]]
        path = sum(abs(current - previous)
                   for previous, current in zip(window, window[1:]))
        net = window[-1] - window[0]
        if path <= 0:
            ratios[index] = 0.0
            directions[index] = 0.0
        else:
            ratios[index] = abs(net) / path
            directions[index] = net / path
    return ratios, directions


def _entry_only_filter(baseline, efficiency, direction, threshold):
    """Use ER only to authorize a new entry; never force an existing EMA position out."""
    if not (len(baseline) == len(efficiency) == len(direction)):
        raise ValueError("Baseline and efficiency arrays must have equal length")
    output = []
    in_position = False
    for base, er, signed_direction in zip(baseline, efficiency, direction):
        if not base:
            in_position = False
        elif not in_position and er is not None and er >= threshold and signed_direction > 0:
            in_position = True
        output.append(bool(in_position))
    return output


def _build_sleeve_signals(bars, threshold):
    closes = [float(row["close"]) for row in bars]
    ema50 = _ema_series(closes, 50)
    ema200 = _ema_series(closes, 200)
    efficiency, direction = _efficiency_ratio_series(closes, 20)
    baseline = [
        bool(i >= 199 and ema50[i] > ema200[i] and closes[i] > ema200[i])
        for i in range(len(bars))
    ]
    gated = [
        bool(baseline[i] and efficiency[i] is not None
             and efficiency[i] >= threshold and direction[i] > 0)
        for i in range(len(bars))
    ]
    entry_only = _entry_only_filter(baseline, efficiency, direction, threshold)
    return baseline, gated, entry_only


def run_ema_efficiency_filter_lab(hourly_candles, fee=FEE_RATE,
                                  slippage=SLIPPAGE_RATE, threshold=0.35):
    """Compare baseline EMA sleeves with ER20-filtered sleeves on identical OOS dates."""
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise ValueError("Efficiency threshold must be in (0, 1]")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    four_hour = aggregate_candles(hourly_candles, 4)
    six_hour = aggregate_candles(hourly_candles, 6)
    if len(four_hour) < 500 or len(six_hour) < 200:
        raise ValueError("Insufficient 4h/6h bars for EMA efficiency research")

    base_4h, filtered_4h, entry_only_4h = _build_sleeve_signals(four_hour, threshold)
    base_6h, filtered_6h, entry_only_6h = _build_sleeve_signals(six_hour, threshold)
    split = int(len(four_hour) * 0.70)
    close_times_4h = [int(row["timestamp"]) + 4 * 3600000 for row in four_hour]
    oos_start = close_times_4h[split]
    oos_end = close_times_4h[-1] + 1
    windows_edges = [
        oos_start + ((oos_end - oos_start) * index) // 3
        for index in range(4)
    ]

    benchmark_signals = [[True] * len(four_hour), [True] * len(six_hour)]
    baseline_signals = [base_4h, base_6h]
    filtered_signals = [filtered_4h, filtered_6h]
    entry_only_signals = [entry_only_4h, entry_only_6h]
    bar_sets = [four_hour, six_hour]
    hours = [4, 6]

    def simulate(signals, start, end, use_fee=fee, use_slippage=slippage):
        return _simulate_equal_weight_multitimeframe(
            bar_sets, signals, hours, start, end, use_fee, use_slippage
        )

    baseline_oos = simulate(baseline_signals, oos_start, oos_end)
    filtered_oos = simulate(filtered_signals, oos_start, oos_end)
    entry_only_oos = simulate(entry_only_signals, oos_start, oos_end)
    benchmark_oos = simulate(benchmark_signals, oos_start, oos_end)

    # Threshold selection uses training data only; the chosen value is then
    # evaluated once on the untouched OOS interval below.
    train_start = close_times_4h[0]
    threshold_grid = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)
    training_candidates = []
    for candidate_threshold in threshold_grid:
        _, _, candidate_4h = _build_sleeve_signals(four_hour, candidate_threshold)
        _, _, candidate_6h = _build_sleeve_signals(six_hour, candidate_threshold)
        candidate_result = simulate(
            [candidate_4h, candidate_6h], train_start, oos_start
        )
        # A small, explicit risk penalty avoids choosing solely by raw return.
        score = (
            candidate_result["return_pct"]
            - 0.50 * candidate_result["max_drawdown_pct"]
        )
        training_candidates.append({
            "threshold": candidate_threshold,
            "metrics": candidate_result,
            "selection_score_return_minus_half_drawdown": round(score, 4),
        })

    eligible = [
        item for item in training_candidates
        if item["metrics"]["closed_trades"] >= 15
        and item["metrics"]["profit_factor"] >= 1.0
    ]
    selected_training = max(
        eligible or training_candidates,
        key=lambda item: item["selection_score_return_minus_half_drawdown"],
    )
    selected_threshold = selected_training["threshold"]
    _, _, selected_4h = _build_sleeve_signals(four_hour, selected_threshold)
    _, _, selected_6h = _build_sleeve_signals(six_hour, selected_threshold)
    selected_entry_oos = simulate([selected_4h, selected_6h], oos_start, oos_end)
    selected_entry_oos_2x = simulate(
        [selected_4h, selected_6h], oos_start, oos_end, fee * 2, slippage * 2
    )

    walk_forward = []
    for fold in range(3):
        start, end = windows_edges[fold], windows_edges[fold + 1]
        if end > start:
            walk_forward.append({
                "window": fold + 1,
                "start_time_ms": start,
                "end_time_ms_exclusive": end,
                "baseline": simulate(baseline_signals, start, end),
                "er20_filtered": simulate(filtered_signals, start, end),
                "er20_entry_only": simulate(entry_only_signals, start, end),
                "matched_benchmark": simulate(benchmark_signals, start, end),
            })

    stress = {}
    for multiplier in (1.0, 2.0):
        scenario_fee = fee * multiplier
        scenario_slippage = slippage * multiplier
        stress[f"{multiplier:g}x"] = {
            "fee_rate_each_side": scenario_fee,
            "slippage_rate_each_side": scenario_slippage,
            "baseline": simulate(baseline_signals, oos_start, oos_end,
                                 scenario_fee, scenario_slippage),
            "er20_filtered": simulate(filtered_signals, oos_start, oos_end,
                                      scenario_fee, scenario_slippage),
            "er20_entry_only": simulate(entry_only_signals, oos_start, oos_end,
                                        scenario_fee, scenario_slippage),
            "matched_benchmark": simulate(benchmark_signals, oos_start, oos_end,
                                          scenario_fee, scenario_slippage),
        }

    def active_count(series):
        return sum(1 for value in series if value)

    baseline_active = active_count(base_4h) + active_count(base_6h)
    filtered_active = active_count(filtered_4h) + active_count(filtered_6h)
    return {
        "mode": "EMA50_200_4H_6H_50_50_ER20_FILTER_RESEARCH",
        "research_only": True,
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "threshold": threshold,
        "training_only_threshold_selection": {
            "grid": list(threshold_grid),
            "selection_rule": "maximize training return_pct - 0.50 * max_drawdown_pct; prefer >=15 closed trades and PF >=1.0",
            "candidates": training_candidates,
            "selected_threshold": selected_threshold,
            "selected_entry_only_oos": selected_entry_oos,
            "selected_entry_only_oos_2x_costs": selected_entry_oos_2x,
        },
        "lookback_bars": 20,
        "bar_count_4h": len(four_hour),
        "bar_count_6h": len(six_hour),
        "out_of_sample_start_ms": oos_start,
        "out_of_sample_end_ms_exclusive": oos_end,
        "signal_activity": {
            "baseline_active_bar_count_sum": baseline_active,
            "filtered_active_bar_count_sum": filtered_active,
            "reduction_pct": round(
                (1 - filtered_active / baseline_active) * 100, 2
            ) if baseline_active else 0.0,
        },
        "out_of_sample": {
            "baseline": baseline_oos,
            "er20_filtered": filtered_oos,
            "er20_entry_only": entry_only_oos,
            "matched_50_50_benchmark": benchmark_oos,
            "baseline_edge_pp": round(
                baseline_oos["return_pct"] - benchmark_oos["return_pct"], 2
            ),
            "filtered_edge_pp": round(
                filtered_oos["return_pct"] - benchmark_oos["return_pct"], 2
            ),
        },
        "walk_forward_windows": walk_forward,
        "cost_sensitivity": stress,
        "interpretation": (
            "ER20 is calculated only from closes available at each completed native-timeframe bar. "
            "Signals are acted on at the next native bar close. The 4h/6h capital split, "
            "allocation, benchmark, fee and slippage assumptions are identical between variants. "
            "ER20 is tested as a continuous gate and entry-only authorization. A threshold grid is selected using training data only with a predeclared return-minus-drawdown score, then evaluated on the untouched OOS interval. The selected value is not retuned on OOS data. This is research, not a profitability guarantee."
        ),
    }


def main():
    candles = load_two_year_candles()
    report = run_ema_efficiency_filter_lab(candles)
    Path("ema_efficiency_research.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
