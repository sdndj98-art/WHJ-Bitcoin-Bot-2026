"""Expanding-window walk-forward research for adaptive ER20 entry confirmation.

The ER threshold is selected only from earlier completed 4h/6h bars.
Each subsequent fold is untouched until selection is frozen. Research-only:
no paper state, credentials, exchange orders, or execution integration.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from historical_research import (
    FEE_RATE,
    SLIPPAGE_RATE,
    _simulate_equal_weight_multitimeframe,
    aggregate_candles,
    load_two_year_candles,
)
from ema_efficiency_lab import _build_sleeve_signals

THRESHOLDS = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)
TIMEFRAMES = (4, 6)
MIN_TRAIN_TRADES = 15


def _score(metrics):
    if not isinstance(metrics, dict):
        raise ValueError("Training metrics must be an object")
    result = metrics.get("return_pct")
    drawdown = metrics.get("max_drawdown_pct")
    trades = metrics.get("closed_trades")
    pf = metrics.get("profit_factor")
    for value, label in ((result, "return"), (drawdown, "drawdown")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Invalid training " + label)
    if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
        raise ValueError("Invalid training trade count")
    if pf is not None and (
        isinstance(pf, bool) or not isinstance(pf, (int, float)) or not math.isfinite(pf) or pf < 0
    ):
        raise ValueError("Invalid training profit factor")
    return float(result) - 0.5 * float(drawdown)


def _eligible(metrics, minimum_trades):
    pf = metrics.get("profit_factor")
    # None represents a zero-gross-loss sample; accept it only when net return is positive.
    pf_ok = (pf is None and metrics["return_pct"] > 0) or (
        isinstance(pf, (int, float)) and not isinstance(pf, bool) and pf >= 1.0
    )
    return metrics["closed_trades"] >= minimum_trades and pf_ok


def _select_threshold(training_by_threshold, baseline_training, minimum_trades=MIN_TRAIN_TRADES):
    if not isinstance(training_by_threshold, dict) or set(training_by_threshold) != {
        str(value) for value in THRESHOLDS
    }:
        raise ValueError("Training results must contain the complete fixed ER threshold grid")
    if isinstance(minimum_trades, bool) or not isinstance(minimum_trades, int) or minimum_trades < 1:
        raise ValueError("Minimum training trades must be a positive integer")

    baseline_score = _score(baseline_training)
    eligible = []
    for key in sorted(training_by_threshold, key=float):
        metrics = training_by_threshold[key]
        score = _score(metrics)
        if _eligible(metrics, minimum_trades):
            threshold = float(key)
            eligible.append((
                score,
                -float(metrics["max_drawdown_pct"]),
                float(threshold == 0.35),
                -threshold,
                threshold,
            ))
    if not eligible:
        return None, "TRAINING_ONLY_BASELINE_NO_ELIGIBLE_ER_SAMPLE"
    best = max(eligible)
    if best[0] <= baseline_score:
        return None, "TRAINING_ONLY_BASELINE_OUTSCORES_ER"
    return best[4], "TRAINING_ONLY_ER_SCORE_BEATS_BASELINE"


def _utc_iso(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat()


def run_er_expanding_walk_forward(
    hourly_candles,
    fee=FEE_RATE,
    slippage=SLIPPAGE_RATE,
    folds=3,
    min_train_trades=MIN_TRAIN_TRADES,
):
    """Select ER20 entry threshold on each expanding training window, then test once."""
    if not isinstance(hourly_candles, list):
        raise ValueError("Hourly candles must be a list")
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < 2:
        raise ValueError("At least two walk-forward folds are required")
    if (isinstance(fee, bool) or isinstance(slippage, bool)
            or not isinstance(fee, (int, float)) or not isinstance(slippage, (int, float))
            or not math.isfinite(fee) or not math.isfinite(slippage)
            or not 0 <= fee < 1 or not 0 <= slippage < 1):
        raise ValueError("Fee and slippage must be finite values between 0 and 1")
    if isinstance(min_train_trades, bool) or not isinstance(min_train_trades, int) or min_train_trades < 1:
        raise ValueError("Minimum training trades must be a positive integer")

    bars4 = aggregate_candles(hourly_candles, 4)
    bars6 = aggregate_candles(hourly_candles, 6)
    if len(bars4) < 500 or len(bars6) < 300:
        raise ValueError("Insufficient 4h/6h history for expanding walk-forward evaluation")

    bar_sets = [bars4, bars6]
    close_times = [
        [int(row["timestamp"]) + hours * 3_600_000 for row in bars]
        for bars, hours in zip(bar_sets, TIMEFRAMES)
    ]
    common_start = max(close_times[0][199], close_times[1][199])
    common_boundaries = sorted(set(close_times[0]).intersection(close_times[1]))
    oos_target = close_times[0][int(len(bars4) * 0.70)]
    oos_index = next(
        (index for index, timestamp in enumerate(common_boundaries) if timestamp >= oos_target),
        None,
    )
    if oos_index is None or len(common_boundaries) - oos_index < folds + 1:
        raise ValueError("Insufficient shared UTC 12-hour boundaries for walk-forward folds")

    usable = common_boundaries[oos_index:]
    boundary_indices = [(len(usable) - 1) * index // folds for index in range(folds + 1)]
    edges = [usable[index] for index in boundary_indices[:-1]] + [usable[-1] + 1]
    if any(edges[index + 1] <= edges[index] for index in range(folds)):
        raise ValueError("Walk-forward test folds are too small")

    baseline_signals = []
    candidate_signals = {str(value): [] for value in THRESHOLDS}
    fixed_signals = []
    for bars in bar_sets:
        baseline, _, fixed_entry = _build_sleeve_signals(bars, 0.35)
        baseline_signals.append(baseline)
        fixed_signals.append(fixed_entry)
    for threshold in THRESHOLDS:
        candidate_signals[str(threshold)] = [
            _build_sleeve_signals(bars, threshold)[2] for bars in bar_sets
        ]
    benchmark_signals = [[True] * len(bars4), [True] * len(bars6)]

    def simulate(signals, start, end, use_fee=fee, use_slippage=slippage):
        return _simulate_equal_weight_multitimeframe(
            bar_sets, signals, list(TIMEFRAMES), start, end, use_fee, use_slippage
        )

    reports = []
    for fold in range(folds):
        test_start, test_end = edges[fold], edges[fold + 1]
        training = {
            key: simulate(signals, common_start, test_start)
            for key, signals in candidate_signals.items()
        }
        baseline_training = simulate(baseline_signals, common_start, test_start)
        selected, rule = _select_threshold(training, baseline_training, min_train_trades)
        selected_signals = baseline_signals if selected is None else candidate_signals[str(selected)]
        selected_name = "baseline_ema50_200" if selected is None else "er20_entry_only_" + str(selected)
        selected_test = simulate(selected_signals, test_start, test_end)
        baseline_test = simulate(baseline_signals, test_start, test_end)
        fixed_test = simulate(fixed_signals, test_start, test_end)
        benchmark_test = simulate(benchmark_signals, test_start, test_end)
        selected_stress = simulate(
            selected_signals, test_start, test_end, fee * 2, slippage * 2
        )
        baseline_stress = simulate(
            baseline_signals, test_start, test_end, fee * 2, slippage * 2
        )
        reports.append({
            "fold": fold + 1,
            "training_start_utc": _utc_iso(common_start),
            "training_end_exclusive_utc": _utc_iso(test_start),
            "test_start_utc": _utc_iso(test_start),
            "test_end_exclusive_utc": _utc_iso(test_end),
            "training_metrics_by_threshold": training,
            "training_baseline_ema50_200": baseline_training,
            "selected_threshold": selected,
            "selected_strategy_name": selected_name,
            "selection_rule": rule,
            "test": {
                "selected_strategy": selected_test,
                "baseline_ema50_200": baseline_test,
                "fixed_er20_035_entry_only": fixed_test,
                "matched_buy_and_hold_50_50": benchmark_test,
                "selected_strategy_2x_cost": selected_stress,
                "baseline_2x_cost": baseline_stress,
            },
        })

    return {
        "mode": "EXPANDING_WINDOW_ER20_ENTRY_ONLY_WALK_FORWARD",
        "research_only": True,
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "threshold_grid": list(THRESHOLDS),
        "timeframes_hours": list(TIMEFRAMES),
        "fold_count": folds,
        "minimum_training_trades": min_train_trades,
        "fold_boundary_alignment": "UTC 12-hour shared completed-bar closes for native 4h and 6h sleeves",
        "training_policy": "Expanding window; each fold selects only from completed bars strictly before its test start.",
        "selection_rule": "Require minimum training trades and PF >= 1.0 (or positive return with no gross losses); maximize training return_pct - 0.5 * max_drawdown_pct; select ER only if its best score strictly beats the EMA baseline, otherwise retain baseline.",
        "test_capital_policy": "Each test fold starts from the same $1,000 50/50 portfolio; fold returns are reported independently and are not compounded.",
        "costs": {
            "fee_each_side": fee,
            "slippage_each_side": slippage,
            "stress_multiplier": 2,
        },
        "oos_start_utc": _utc_iso(edges[0]),
        "oos_end_exclusive_utc": _utc_iso(edges[-1]),
        "folds": reports,
        "no_same_fold_test_feedback": True,
        "interpretation": (
            "This is a stricter sequential test of ER20 entry-only thresholds. "
            "The EMA50/200 control remains the default whenever ER fails its training eligibility "
            "or does not beat the control on prior data. No test-fold data selects its own threshold. "
            "Historical results are research only, not forward-paper or live performance."
        ),
    }



def main():
    candles = load_two_year_candles()
    report = run_er_expanding_walk_forward(candles)
    Path("ema_er_walk_forward_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
