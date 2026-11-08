"""Research-only exit-policy comparison for the EMA50/200 + ADX20 4h/6h portfolio.

Compares the existing EMA-regime exit with close-confirmed ATR trailing exits.
Signals use completed native bars; the shared simulator fills at the next close.
No paper state or live orders are accessed.
"""
import json
import math
from pathlib import Path

from historical_research import (
    FEE_RATE, SLIPPAGE_RATE, _adx_di_series, _atr_series, _simulate_equal_weight_multitimeframe,
    aggregate_candles, load_two_year_candles,
)
from ema_adx_lab import _build_sleeve_signals


ATR_MULTIPLIERS = (2.5, 3.0, 4.0)


def _adx_entry_ema_exit_signals(bars, threshold=20.0):
    """Enter only on ADX confirmation; hold until the EMA regime turns off."""
    baseline, confirmed = _build_sleeve_signals(bars, threshold)
    signals = []
    active = False
    for regime_on, entry_confirmed in zip(baseline, confirmed):
        if not regime_on:
            active = False
        elif not active and entry_confirmed:
            active = True
        signals.append(active)
    return signals


def _adx_atr_exit_signals(bars, threshold=20.0, atr_multiple=3.0):
    if (isinstance(atr_multiple, bool) or not isinstance(atr_multiple, (int, float))
            or not math.isfinite(atr_multiple) or atr_multiple <= 0):
        raise ValueError("ATR multiple must be a finite positive number")
    baseline, _ = _build_sleeve_signals(bars, threshold)
    adx, plus_di, minus_di = _adx_di_series(bars, 14)
    atr = _atr_series(bars, 14)
    signals = []
    active = False
    high_water = None
    # After an ATR stop, require the raw ADX/DI confirmation to reset before
    # another entry. This prevents immediate same-signal re-entry and churn.
    rearm_required = False
    for i, bar in enumerate(bars):
        close = float(bar["close"])
        confirmed = bool(
            adx[i] is not None and plus_di[i] is not None and minus_di[i] is not None
            and adx[i] >= threshold and plus_di[i] > minus_di[i]
        )
        if not baseline[i]:
            active = False
            high_water = None
            rearm_required = False
        elif active:
            # The current bar is completed. Its high updates the trailing
            # watermark; a close below the resulting stop schedules exit
            # at the next native bar close via the shared simulator.
            high_water = max(high_water, float(bar["high"]))
            if atr[i] is not None and close <= high_water - atr_multiple * atr[i]:
                active = False
                high_water = None
                rearm_required = True
        elif rearm_required:
            # A reset bar only rearms the strategy; it cannot also enter.
            if not confirmed:
                rearm_required = False
        elif confirmed:
            active = True
            high_water = float(bar["high"])
        signals.append(active)
    return signals


def run_exit_policy_lab(hourly_candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE):
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")
    bars4, bars6 = aggregate_candles(hourly_candles, 4), aggregate_candles(hourly_candles, 6)
    if len(bars4) < 500 or len(bars6) < 300:
        raise ValueError("Insufficient history for exit-policy research")
    bar_sets, hours = [bars4, bars6], [4, 6]
    ema_exit_sets = [
        _adx_entry_ema_exit_signals(bars, 20.0) for bars in bar_sets
    ]
    exit_signals = {"ema_regime_exit": ema_exit_sets}
    for multiple in ATR_MULTIPLIERS:
        exit_signals[f"atr_trailing_{multiple:g}x"] = [
            _adx_atr_exit_signals(bars, 20.0, multiple) for bars in bar_sets
        ]
    close4 = [int(row["timestamp"]) + 4 * 3600000 for row in bars4]
    close6 = [int(row["timestamp"]) + 6 * 3600000 for row in bars6]
    # Use only shared UTC 12-hour close boundaries so 4h and 6h sleeves
    # begin/end every comparison window on the same completed-bar boundary.
    shared_closes = sorted(set(close4).intersection(close6))
    if len(shared_closes) < 12:
        raise ValueError("Insufficient shared 12-hour boundaries for exit-policy validation")
    oos_offset = int(len(shared_closes) * 0.70)
    oos_closes = shared_closes[oos_offset:]
    start, end = oos_closes[0], oos_closes[-1] + 1
    benchmark = [[True] * len(bars4), [True] * len(bars6)]

    def simulate(signals, cost=1.0):
        return _simulate_equal_weight_multitimeframe(
            bar_sets, signals, hours, start, end, fee * cost, slippage * cost
        )

    base_results = {
        name: simulate(signals) for name, signals in exit_signals.items()
    }
    benchmark_base = simulate(benchmark)
    cost_sensitivity = {}
    for multiplier in (1.0, 2.0, 3.0):
        scenario = {
            name: _simulate_equal_weight_multitimeframe(
                bar_sets, signals, hours, start, end,
                fee * multiplier, slippage * multiplier
            )
            for name, signals in exit_signals.items()
        }
        scenario_benchmark = _simulate_equal_weight_multitimeframe(
            bar_sets, benchmark, hours, start, end,
            fee * multiplier, slippage * multiplier
        )
        cost_sensitivity[f"{multiplier:g}x"] = {
            "fee_rate_each_side": fee * multiplier,
            "slippage_rate_each_side": slippage * multiplier,
            "matched_50_50_buy_and_hold": scenario_benchmark,
            "policies": scenario,
            "edge_vs_benchmark_pp": {
                name: round(metrics["return_pct"] - scenario_benchmark["return_pct"], 2)
                for name, metrics in scenario.items()
            },
        }

    # Descriptive fixed-rule OOS slices: no parameter tuning or re-selection.
    fold_edges = [
        oos_closes[(len(oos_closes) * k) // 3]
        for k in range(3)
    ] + [oos_closes[-1] + 1]
    subperiods = []
    for fold in range(3):
        fold_start, fold_end = fold_edges[fold], fold_edges[fold + 1]
        if fold_end <= fold_start:
            continue
        fold_metrics = {
            name: _simulate_equal_weight_multitimeframe(
                bar_sets, signals, hours, fold_start, fold_end, fee, slippage
            )
            for name, signals in exit_signals.items()
        }
        fold_benchmark = _simulate_equal_weight_multitimeframe(
            bar_sets, benchmark, hours, fold_start, fold_end, fee, slippage
        )
        subperiods.append({
            "window": fold + 1,
            "start_time_ms": fold_start,
            "end_time_ms_exclusive": fold_end,
            "matched_50_50_buy_and_hold": fold_benchmark,
            "policies": fold_metrics,
            "edge_vs_benchmark_pp": {
                name: round(metrics["return_pct"] - fold_benchmark["return_pct"], 2)
                for name, metrics in fold_metrics.items()
            },
        })

    subperiods_double_cost = []
    for fold in range(3):
        fold_start, fold_end = fold_edges[fold], fold_edges[fold + 1]
        if fold_end <= fold_start:
            continue
        subperiods_double_cost.append({
            name: _simulate_equal_weight_multitimeframe(
                bar_sets, signals, hours, fold_start, fold_end,
                fee * 2, slippage * 2
            )
            for name, signals in exit_signals.items()
        })

    robustness = {}
    for name in exit_signals:
        baseline_folds = [item["policies"]["ema_regime_exit"] for item in subperiods]
        candidate_folds = [item["policies"][name] for item in subperiods]
        double_cost_folds = [item[name] for item in subperiods_double_cost]
        robustness[name] = {
            "fold_count": len(candidate_folds),
            "positive_return_folds": sum(x["return_pct"] > 0 for x in candidate_folds),
            "outperformed_ema_exit_folds": sum(
                x["return_pct"] > b["return_pct"]
                for x, b in zip(candidate_folds, baseline_folds)
            ),
            "lower_drawdown_than_ema_exit_folds": sum(
                x["max_drawdown_pct"] < b["max_drawdown_pct"]
                for x, b in zip(candidate_folds, baseline_folds)
            ),
            "outperformed_benchmark_folds": sum(
                x["return_pct"] > item["matched_50_50_buy_and_hold"]["return_pct"]
                for x, item in zip(candidate_folds, subperiods)
            ),
            "positive_return_2x_cost_folds": sum(
                x["return_pct"] > 0 for x in double_cost_folds
            ),
        }

    return {
        "mode": "EMA50_200_ADX20_EXIT_POLICY_RESEARCH_4H_6H_50_50",
        "research_only": True,
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "data_bar_counts": {"4h": len(bars4), "6h": len(bars6)},
        "shared_12h_boundary_count": len(shared_closes),
        "oos_start_ms": start,
        "oos_end_exclusive_ms": end,
        "entry_policy": "ADX14 >= 20 and +DI > -DI on completed native bar; baseline EMA regime must be active.",
        "exit_policies": {
            "ema_regime_exit": "Existing baseline EMA50/EMA200 regime-off exit.",
            "atr_trailing": "Close-confirmed trailing stop from highest completed-bar high minus ATR14 multiple; exit fill at next native-bar close.",
        },
        "costs": {"fee_each_side": fee, "slippage_each_side": slippage},
        "results": {
            **{
                name: {
                    "base_cost": metrics,
                    "double_cost": cost_sensitivity["2x"]["policies"][name],
                    "triple_cost": cost_sensitivity["3x"]["policies"][name],
                    "edge_vs_benchmark_pp": round(
                        metrics["return_pct"] - benchmark_base["return_pct"], 2
                    ),
                }
                for name, metrics in base_results.items()
            },
            "matched_50_50_buy_and_hold": {"base_cost": benchmark_base},
        },
        "cost_sensitivity": cost_sensitivity,
        "temporal_subperiods": subperiods,
        "temporal_subperiod_robustness": robustness,
        "subperiod_semantics": "Three descriptive fixed-rule OOS slices aligned to shared UTC 12-hour closes; no retraining or parameter selection.",
        "interpretation": "Historical OOS comparison only. Each policy uses identical ADX20 entry criteria and 50/50 timeframe sleeves. The benchmark uses the same 50/50 sleeve structure. ATR stops are evaluated on completed bars and simulated at the next native close; no intrabar fill assumption. Temporal slices are descriptive, not retrained walk-forward evidence. Historical results do not establish forward or live profitability.",
    }


def main():
    report = run_exit_policy_lab(load_two_year_candles())
    Path("adx_exit_policy_research.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
