"""Research-only ADX entry confirmation for the 50/50 4h + 6h EMA50/200 portfolio.

Uses completed native-timeframe OHLC bars only. Never touches paper state or orders.
"""
import json
from pathlib import Path

from historical_research import (
    FEE_RATE,
    SLIPPAGE_RATE,
    _adx_di_series,
    _ema_series,
    _simulate_equal_weight_multitimeframe,
    aggregate_candles,
    load_two_year_candles,
)


def _adx_entry_only_filter(baseline, adx, plus_di, minus_di, threshold):
    if not (len(baseline) == len(adx) == len(plus_di) == len(minus_di)):
        raise ValueError("Baseline and ADX series must have equal length")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 100:
        raise ValueError("ADX threshold must be in (0, 100]")
    output = []
    in_position = False
    for base, strength, positive, negative in zip(baseline, adx, plus_di, minus_di):
        if not base:
            in_position = False
        elif not in_position and strength is not None and positive is not None and negative is not None:
            if strength >= threshold and positive > negative:
                in_position = True
        output.append(bool(in_position))
    return output


def _build_sleeve_signals(bars, threshold):
    closes = [float(row["close"]) for row in bars]
    ema50 = _ema_series(closes, 50)
    ema200 = _ema_series(closes, 200)
    adx, plus_di, minus_di = _adx_di_series(bars, 14)
    baseline = [
        bool(i >= 199 and ema50[i] > ema200[i] and closes[i] > ema200[i])
        for i in range(len(bars))
    ]
    confirmed = _adx_entry_only_filter(baseline, adx, plus_di, minus_di, threshold)
    return baseline, confirmed


def run_ema_adx_filter_lab(hourly_candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE):
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")
    four_hour = aggregate_candles(hourly_candles, 4)
    six_hour = aggregate_candles(hourly_candles, 6)
    if len(four_hour) < 500 or len(six_hour) < 200:
        raise ValueError("Insufficient 4h/6h bars for EMA ADX research")

    baseline_4h, adx20_4h = _build_sleeve_signals(four_hour, 20.0)
    baseline_6h, adx20_6h = _build_sleeve_signals(six_hour, 20.0)
    _, adx15_4h = _build_sleeve_signals(four_hour, 15.0)
    _, adx15_6h = _build_sleeve_signals(six_hour, 15.0)
    _, adx25_4h = _build_sleeve_signals(four_hour, 25.0)
    _, adx25_6h = _build_sleeve_signals(six_hour, 25.0)

    close_times_4h = [int(row["timestamp"]) + 4 * 3600000 for row in four_hour]
    oos_start = close_times_4h[int(len(four_hour) * 0.70)]
    oos_end = close_times_4h[-1] + 1
    train_start = max(
        close_times_4h[199],
        int(six_hour[199]["timestamp"]) + 6 * 3600000,
    )
    bar_sets = [four_hour, six_hour]
    hours = [4, 6]
    baseline = [baseline_4h, baseline_6h]
    variants = {
        "adx_15_entry_only": [adx15_4h, adx15_6h],
        "adx_20_entry_only": [adx20_4h, adx20_6h],
        "adx_25_entry_only": [adx25_4h, adx25_6h],
    }
    benchmark = [[True] * len(four_hour), [True] * len(six_hour)]

    def simulate(signals, start, end, use_fee=fee, use_slippage=slippage):
        return _simulate_equal_weight_multitimeframe(
            bar_sets, signals, hours, start, end, use_fee, use_slippage
        )

    baseline_oos = simulate(baseline, oos_start, oos_end)
    benchmark_oos = simulate(benchmark, oos_start, oos_end)
    results = {}
    for name, signals in variants.items():
        results[name] = {
            "out_of_sample": simulate(signals, oos_start, oos_end),
            "training": simulate(signals, train_start, oos_start),
            "walk_forward_windows": [],
        }

    # Include baseline and matched benchmark in every identical time window.
    # This prevents candidate-only fold reporting from overstating robustness.
    walk_forward = {"baseline": [], "matched_benchmark": []}
    walk_forward.update({name: [] for name in variants})
    walk_forward_costs = {
        multiplier: {"baseline": [], **{name: [] for name in variants}}
        for multiplier in ("1x", "2x")
    }
    for fold in range(3):
        start = oos_start + ((oos_end - oos_start) * fold) // 3
        end = oos_start + ((oos_end - oos_start) * (fold + 1)) // 3
        if end <= start:
            continue
        window = {
            "window": fold + 1,
            "start_time_ms": start,
            "end_time_ms_exclusive": end,
        }
        for name, signals in (("baseline", baseline), ("matched_benchmark", benchmark), *variants.items()):
            walk_forward[name].append({
                **window,
                "metrics": simulate(signals, start, end),
            })
        for multiplier in ("1x", "2x"):
            factor = float(multiplier[:-1])
            scenario_fee = fee * factor
            scenario_slippage = slippage * factor
            for name, signals in (("baseline", baseline), *variants.items()):
                walk_forward_costs[multiplier][name].append({
                    **window,
                    "metrics": simulate(
                        signals, start, end, scenario_fee, scenario_slippage
                    ),
                })

    stress = {}
    for multiplier in (1.0, 2.0):
        scenario_fee = fee * multiplier
        scenario_slippage = slippage * multiplier
        stress[f"{multiplier:g}x"] = {
            "fee_rate_each_side": scenario_fee,
            "slippage_rate_each_side": scenario_slippage,
            "baseline": simulate(baseline, oos_start, oos_end, scenario_fee, scenario_slippage),
            "matched_benchmark": simulate(benchmark, oos_start, oos_end, scenario_fee, scenario_slippage),
            **{
                name: simulate(signals, oos_start, oos_end, scenario_fee, scenario_slippage)
                for name, signals in variants.items()
            },
        }

    return {
        "mode": "EMA50_200_4H_6H_50_50_ADX_ENTRY_CONFIRMATION_RESEARCH",
        "research_only": True,
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "adx_period": 14,
        "primary_threshold": 20.0,
        "thresholds_tested": [15.0, 20.0, 25.0],
        "threshold_policy": "Fixed predeclared thresholds; no OOS optimization or selection.",
        "bar_count_4h": len(four_hour),
        "bar_count_6h": len(six_hour),
        "out_of_sample_start_ms": oos_start,
        "out_of_sample_end_ms_exclusive": oos_end,
        "out_of_sample": {
            "baseline": baseline_oos,
            "matched_50_50_benchmark": benchmark_oos,
            **{name: value["out_of_sample"] for name, value in results.items()},
        },
        "training": {name: value["training"] for name, value in results.items()},
        "walk_forward_windows": walk_forward,
        "walk_forward_cost_sensitivity": walk_forward_costs,
        "cost_sensitivity": stress,
        "execution": (
            "ADX(14) and +DI/-DI are computed from each completed native 4h/6h OHLC bar. "
            "ADX >= threshold and +DI > -DI authorize a new entry only; an open position "
            "remains until the baseline EMA50/EMA200 regime turns off. Orders are simulated "
            "at the next native-timeframe close. Equal 50/50 capital sleeves and matched "
            "50/50 buy-and-hold benchmark are used."
        ),
        "interpretation": (
            "This is a fixed-rule research comparison, not an optimization. Thresholds 15, 20, "
            "and 25 are all reported; the 20 threshold is the primary candidate. Historical "
            "results do not imply forward-paper or live profitability."
        ),
    }


def main():
    report = run_ema_adx_filter_lab(load_two_year_candles())
    Path("ema_adx_research.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
