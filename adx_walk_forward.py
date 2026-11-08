"""Expanding-window walk-forward selection for EMA50/200 + ADX entry filters.

Each fold selects an ADX threshold using only bars strictly before that fold's
test interval. Test metrics are computed only after selection and never feed
back into the same fold's choice. Research-only; no paper state or orders.
"""
from datetime import datetime, timezone
import math

from historical_research import (
    FEE_RATE,
    SLIPPAGE_RATE,
    _simulate_equal_weight_multitimeframe,
    aggregate_candles,
)
from ema_adx_lab import _build_sleeve_signals

THRESHOLDS = (15.0, 20.0, 25.0)
TIMEFRAMES = (4, 6)


def _select_threshold(training_metrics, min_closed_trades=5):
    """Select only from training metrics; default to predeclared ADX20 if sparse."""
    if not isinstance(training_metrics, dict) or set(training_metrics) != {
        "15", "20", "25"
    }:
        raise ValueError("Training metrics must contain exactly ADX15, ADX20 and ADX25")
    if (isinstance(min_closed_trades, bool) or not isinstance(min_closed_trades, int)
            or min_closed_trades < 1):
        raise ValueError("Minimum training trades must be a positive integer")
    eligible = []
    for key, metrics in training_metrics.items():
        if not isinstance(metrics, dict):
            raise ValueError("Malformed training metrics")
        ret = metrics.get("return_pct")
        dd = metrics.get("max_drawdown_pct")
        trades = metrics.get("closed_trades")
        pf = metrics.get("profit_factor")
        for value, label in ((ret, "return"), (dd, "drawdown")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Invalid training " + label)
        if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
            raise ValueError("Invalid training trade count")
        if pf is not None and (
            isinstance(pf, bool) or not isinstance(pf, (int, float)) or not math.isfinite(pf)
        ):
            raise ValueError("Invalid training profit factor")
        if trades >= min_closed_trades:
            # Fixed selection rule, predeclared and independent of test results.
            score = float(ret) - 0.5 * float(dd)
            eligible.append((score, -float(dd), float(key == "20"), key))
    if not eligible:
        return 20.0, "DEFAULT_PRIMARY_INSUFFICIENT_TRAINING_TRADES"
    selected = max(eligible)[3]
    return float(selected), "TRAINING_ONLY_RETURN_MINUS_HALF_DRAWDOWN"


def _utc_iso(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat()


def run_expanding_walk_forward(hourly_candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE,
                               folds=3, min_train_trades=5):
    """Run chronological expanding-window selection and untouched next-fold tests."""
    if not isinstance(hourly_candles, list):
        raise ValueError("Hourly candles must be a list")
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < 2:
        raise ValueError("At least two walk-forward folds are required")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    bars4 = aggregate_candles(hourly_candles, 4)
    bars6 = aggregate_candles(hourly_candles, 6)
    if len(bars4) < 500 or len(bars6) < 300:
        raise ValueError("Insufficient history for expanding walk-forward evaluation")

    sets = [bars4, bars6]
    hours = list(TIMEFRAMES)
    close_times = [
        [int(row["timestamp"]) + h * 3_600_000 for row in bars]
        for bars, h in zip(sets, hours)
    ]
    common_start = max(times[199] for times in close_times)
    oos_start = close_times[0][int(len(bars4) * 0.70)]
    oos_end = min(times[-1] + 1 for times in close_times)
    if oos_end <= oos_start:
        raise ValueError("Insufficient common out-of-sample interval")
    edges = [
        oos_start + ((oos_end - oos_start) * index) // folds
        for index in range(folds + 1)
    ]
    if any(edges[index + 1] <= edges[index] for index in range(folds)):
        raise ValueError("Walk-forward test folds are too small")

    baseline_sets = []
    candidate_sets = {str(int(t)): [] for t in THRESHOLDS}
    for bars in sets:
        closes = [float(row["close"]) for row in bars]
        ema50, ema200, adx, plus_di, minus_di = None, None, None, None, None
        # Reuse the canonical signal builder to keep indicator math identical.
        base, _ = _build_sleeve_signals(bars, 20.0)
        baseline_sets.append(base)
    for threshold in THRESHOLDS:
        candidate_sets[str(int(threshold))] = [
            _build_sleeve_signals(bars, threshold)[1] for bars in sets
        ]
    benchmark_sets = [[True] * len(bars4), [True] * len(bars6)]

    def simulate(signals, start, end, fee_rate=fee, slip_rate=slippage):
        return _simulate_equal_weight_multitimeframe(
            sets, signals, hours, start, end, fee_rate, slip_rate
        )

    reports = []
    for fold in range(folds):
        test_start, test_end = edges[fold], edges[fold + 1]
        # The training interval ends strictly before the test interval starts.
        training = {
            key: simulate(signals, common_start, test_start)
            for key, signals in candidate_sets.items()
        }
        selected, selection_rule = _select_threshold(training, min_train_trades)
        selected_key = str(int(selected))
        test_metrics = simulate(candidate_sets[selected_key], test_start, test_end)
        baseline_metrics = simulate(baseline_sets, test_start, test_end)
        benchmark_metrics = simulate(benchmark_sets, test_start, test_end)
        stress = simulate(
            candidate_sets[selected_key], test_start, test_end,
            fee * 2, slippage * 2,
        )
        baseline_stress = simulate(
            baseline_sets, test_start, test_end, fee * 2, slippage * 2
        )
        reports.append({
            "fold": fold + 1,
            "training_start_utc": _utc_iso(common_start),
            "training_end_exclusive_utc": _utc_iso(test_start),
            "test_start_utc": _utc_iso(test_start),
            "test_end_exclusive_utc": _utc_iso(test_end),
            "training_metrics_by_threshold": training,
            "selected_threshold": selected,
            "selection_rule": selection_rule,
            "test": {
                "selected_strategy": test_metrics,
                "baseline_ema50_200": baseline_metrics,
                "matched_buy_and_hold_50_50": benchmark_metrics,
                "selected_strategy_2x_cost": stress,
                "baseline_2x_cost": baseline_stress,
            },
        })

    return {
        "mode": "EXPANDING_WINDOW_ADX_THRESHOLD_WALK_FORWARD",
        "research_only": True,
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "thresholds": list(THRESHOLDS),
        "timeframes_hours": list(TIMEFRAMES),
        "fold_count": folds,
        "test_fold_capital_policy": (
            "Each test fold is independently simulated from $1,000 portfolio capital; "
            "fold returns are reported separately and are not compounded into one continuous equity curve."
        ),
        "training_policy": "Expanding window; each fold trains only on completed bars before its test start.",
        "selection_rule": "Among thresholds with at least min_train_trades closed training trades, maximize training return_pct - 0.5 * max_drawdown_pct; tie-break by lower drawdown then prefer ADX20. If none qualify, use predeclared ADX20.",
        "min_train_trades": min_train_trades,
        "costs": {
            "fee_each_side": fee,
            "slippage_each_side": slippage,
            "stress_multiplier": 2,
        },
        "oos_start_utc": _utc_iso(oos_start),
        "oos_end_exclusive_utc": _utc_iso(oos_end),
        "folds": reports,
        "no_same_fold_test_feedback": True,
        "interpretation": (
            "Each fold's threshold is selected only from its earlier expanding training window. "
            "Earlier test folds may become training data for later folds, as in sequential walk-forward "
            "evaluation; no fold's own test data is used to select its threshold. Results are historical "
            "research, not forward-paper or live performance."
        ),
    }


if __name__ == "__main__":
    import json
    from historical_research import load_two_year_candles
    result = run_expanding_walk_forward(load_two_year_candles())
    with open("adx_walk_forward_report.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(result, indent=2, allow_nan=False))
