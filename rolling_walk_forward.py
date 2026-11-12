"""Expanding-window rolling walk-forward selection for isolated research.

At each fold, candidates are ranked only on the history available before the
test block. The selected signal is frozen for the next contiguous block.
Signals must be causal completed-bar booleans; fills use the common evaluator.
This module has no account, ledger, exchange, order, or promotion integration.
"""
import math

from strategy_family_evaluator import evaluate_candidate


def _path_summary(returns):
    equity = [1.0]
    for value in returns:
        equity.append(equity[-1] * (1.0 + value))
    peak = equity[0]
    drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1.0)
    return {
        "net_return": equity[-1] - 1.0,
        "max_close_to_close_drawdown": drawdown,
        "bars": len(returns),
    }


def evaluate_rolling_walk_forward(
    candles,
    signals_by_candidate,
    initial_train_bars,
    test_bars,
    fee_rate=0.001,
    slippage_rate=0.0005,
    bars_per_year=24 * 365,
    allocation_fraction=0.25,
):
    """Run expanding training windows followed by contiguous, frozen OOS blocks.

    Candidate selection maximizes training excess return versus matched
    buy-and-hold. Ties are resolved alphabetically. No parameter tuning occurs
    here; the candidate definitions and signal streams must be predeclared.
    """
    if not isinstance(candles, (list, tuple)) or len(candles) < 7:
        raise ValueError("at least seven candles are required")
    if not isinstance(signals_by_candidate, dict) or not signals_by_candidate:
        raise ValueError("signals_by_candidate must be a non-empty mapping")
    if isinstance(initial_train_bars, bool) or not isinstance(initial_train_bars, int):
        raise ValueError("initial_train_bars must be an integer")
    if isinstance(test_bars, bool) or not isinstance(test_bars, int):
        raise ValueError("test_bars must be an integer")
    if initial_train_bars < 4 or test_bars < 3:
        raise ValueError("training requires >=4 bars and each test block >=3 bars")
    if initial_train_bars >= len(candles):
        raise ValueError("initial training window must leave test data")
    if (isinstance(allocation_fraction, bool)
            or not isinstance(allocation_fraction, (int, float))
            or not math.isfinite(allocation_fraction)
            or not 0 < allocation_fraction <= 0.25):
        raise ValueError("allocation_fraction must be finite and in (0, 0.25]")
    if any(not isinstance(name, str) or not name for name in signals_by_candidate):
        raise ValueError("candidate names must be non-empty strings")
    names = sorted(signals_by_candidate)
    for name in names:
        series = signals_by_candidate[name]
        if not isinstance(series, (list, tuple)) or len(series) != len(candles):
            raise ValueError("every candidate signal stream must align with candles")
        if any(type(signal) is not bool for signal in series):
            raise ValueError("candidate signals must contain only bool values")

    folds = []
    aggregate_returns = {1: [], 2: [], 3: []}
    aggregate_benchmark_returns = {1: [], 2: [], 3: []}
    train_end = initial_train_bars
    while train_end + 2 < len(candles):
        test_end = min(train_end + test_bars, len(candles))
        if test_end - train_end < 3:
            break
        training_rows = candles[:train_end]
        training_scores = {}
        for name in names:
            training = evaluate_candidate(
                training_rows, signals_by_candidate[name][:train_end],
                fee_rate, slippage_rate, bars_per_year,
                allocation_fraction=allocation_fraction,
            )
            training_scores[name] = training["excess_return"]

        selected = max(names, key=lambda name: (training_scores[name], name))
        # Keep two pre-test candles: the final completed training signal fills
        # at open[train_end - 1], making OOS returns contiguous across folds.
        # The training score itself ends at open[train_end - 1].
        test_rows = candles[train_end - 2:test_end]
        test_signals = signals_by_candidate[selected][train_end - 2:test_end]
        cost_scenarios = {}
        for multiplier in (1, 2, 3):
            scenario = evaluate_candidate(
                test_rows, test_signals, fee_rate * multiplier,
                slippage_rate * multiplier, bars_per_year,
                allocation_fraction=allocation_fraction,
            )
            aggregate_returns[multiplier].extend(scenario["net_returns"])
            aggregate_benchmark_returns[multiplier].extend(scenario["benchmark_net_returns"])
            cost_scenarios[f"{multiplier}x"] = {
                "strategy": scenario["strategy"],
                "buy_and_hold": scenario["buy_and_hold"],
                "excess_return": scenario["excess_return"],
                "strategy_net_returns": scenario["net_returns"],
                "benchmark_net_returns": scenario["benchmark_net_returns"],
            }
        baseline = cost_scenarios["1x"]
        folds.append({
            "fold": len(folds) + 1,
            "training_start_index": 0,
            "training_end_index_exclusive": train_end,
            "test_start_index": train_end,
            "test_end_index_exclusive": test_end,
            "selected_candidate": selected,
            "training_excess_returns": training_scores,
            "test_strategy": baseline["strategy"],
            "test_buy_and_hold": baseline["buy_and_hold"],
            "test_excess_return": baseline["excess_return"],
            "cost_scenarios": cost_scenarios,
            "selection_rule": "max_training_excess_return_vs_matched_buy_and_hold_at_1x_cost",
            "drawdown_measurement": "close_to_close_open_to_open_equity",
        })
        train_end = test_end

    if not folds:
        raise ValueError("data does not contain a complete test fold")
    return {
        "protocol": "expanding_window_rolling_walk_forward_frozen_candidate",
        "fold_count": len(folds),
        "initial_train_bars": initial_train_bars,
        "test_bars": test_bars,
        "allocation_fraction": allocation_fraction,
        "candidate_count": len(names),
        "candidate_names": names,
        "folds": folds,
        "aggregate_oos_cost_scenarios": {
            f"{multiplier}x": {
                "strategy": _path_summary(aggregate_returns[multiplier]),
                "buy_and_hold": _path_summary(aggregate_benchmark_returns[multiplier]),
                "excess_return": (
                    _path_summary(aggregate_returns[multiplier])["net_return"]
                    - _path_summary(aggregate_benchmark_returns[multiplier])["net_return"]
                ),
            }
            for multiplier in (1, 2, 3)
        },
        "tested_through_index_exclusive": folds[-1]["test_end_index_exclusive"],
        "unused_tail_bars": len(candles) - folds[-1]["test_end_index_exclusive"],
        "promotion_status": "NO_CANDIDATE_PROMOTED",
        "limitations": [
            "Candidate definitions and parameters must be frozen before this run.",
            "Signals must be causal; this routine cannot prove signal-builder causality.",
            "Selection uses prior training data only; no independent final holdout is reserved.",
            "Fixed fee/slippage omits spread, depth, impact, latency and intrabar execution.",
            "Small fold trade counts are descriptive and do not establish statistical power.",
        ],
    }
