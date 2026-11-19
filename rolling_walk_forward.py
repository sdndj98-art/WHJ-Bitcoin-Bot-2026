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
        "max_open_to_open_drawdown": drawdown,
        "bars": len(returns),
    }



def _market_regime_labels(candles):
    """Classify each completed close using only its own and prior closes."""
    closes = []
    for row in candles:
        value = row.get("close") if isinstance(row, dict) else row[4]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("close prices must be positive finite numbers")
        try:
            close = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("close prices must be positive finite numbers") from exc
        if not math.isfinite(close) or close <= 0:
            raise ValueError("close prices must be positive finite numbers")
        closes.append(close)
    prefix = [0.0]
    for close in closes:
        prefix.append(prefix[-1] + close)
    def sma_at(index):
        start = index - 199
        if start < 0:
            return None
        return (prefix[index + 1] - prefix[start]) / 200.0
    labels = []
    for index, close in enumerate(closes):
        current_sma = sma_at(index)
        prior_sma = sma_at(index - 20) if index >= 219 else None
        if current_sma is None or prior_sma is None:
            labels.append("sideways_transition")
        elif close > current_sma and current_sma > prior_sma:
            labels.append("bullish")
        elif close < current_sma and current_sma < prior_sma:
            labels.append("bearish")
        else:
            labels.append("sideways_transition")
    return labels


def _regime_attribution(net_returns, signals, regime_labels, minimum_active_bars=30):
    """Attribute fixed-candidate net log growth to the regime known at signal close.

    Grouped contributions reconcile to total OOS log growth, but are not
    independently executable regime portfolios.
    """
    if not (len(net_returns) == len(signals) == len(regime_labels)):
        raise ValueError("regime attribution inputs must have identical lengths")
    output = {}
    for regime in ("bullish", "bearish", "sideways_transition"):
        indices = [i for i, label in enumerate(regime_labels) if label == regime]
        values = [net_returns[i] for i in indices]
        active_values = [net_returns[i] for i in indices if signals[i]]
        if any(value <= -1.0 for value in values):
            raise ValueError("net returns must be greater than -100% for log attribution")
        log_growth = sum(math.log1p(value) for value in values)
        active_count = len(active_values)
        output[regime] = {
            "bars": len(indices),
            "active_signal_bars": active_count,
            "net_log_contribution_pct": log_growth * 100.0,
            "conditional_compounded_return_pct": math.expm1(log_growth) * 100.0,
            "positive_active_net_return_bars": sum(value > 0 for value in active_values),
            "positive_active_net_return_pct": (
                sum(value > 0 for value in active_values) / active_count * 100.0
                if active_count else None
            ),
            "evidence_status": (
                "INSUFFICIENT_SAMPLE" if active_count < minimum_active_bars
                else "DESCRIPTIVE_ONLY"
            ),
        }
    return output

def evaluate_rolling_walk_forward(
    candles,
    signals_by_candidate,
    initial_train_bars,
    test_bars,
    fee_rate=0.001,
    slippage_rate=0.0005,
    bars_per_year=24 * 365,
    allocation_fraction=0.25,
    max_folds=None,
):
    """Run expanding training windows followed by contiguous, frozen OOS blocks.

    Candidate selection maximizes training excess return versus matched
    buy-and-hold. Ties are resolved alphabetically. No parameter tuning occurs
    here; the candidate definitions and signal streams must be predeclared.
    max_folds can cap OOS folds and leave a trailing segment unused by this
    walk-forward calculation. That tail is not automatically an untouched
    holdout if another report or experiment has already exposed it.
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
    if (max_folds is not None
            and (isinstance(max_folds, bool) or not isinstance(max_folds, int) or max_folds < 1)):
        raise ValueError("max_folds must be a positive integer or None")
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
    fixed_candidate_fold_results = {name: [] for name in names}
    stitched_oos_signals = [False] * len(candles)
    train_end = initial_train_bars
    while (train_end + test_bars + 1 < len(candles)
           and (max_folds is None or len(folds) < max_folds)):
        test_end = train_end + test_bars
        training_rows = candles[:train_end]
        training_scores = {}
        training_closed_trades = {}
        for name in names:
            training = evaluate_candidate(
                training_rows, signals_by_candidate[name][:train_end],
                fee_rate, slippage_rate, bars_per_year,
                allocation_fraction=allocation_fraction,
            )
            training_scores[name] = training["excess_return"]
            training_closed_trades[name] = training["strategy"]["closed_trades"]

        selected = min(names, key=lambda name: (-training_scores[name], name))
        # The fold is selected after close[train_end - 1]; its first signal
        # therefore fills at open[train_end]. Keep one prior candle for that
        # signal and one endpoint candle so the fold has exactly test_bars returns.
        test_rows = candles[train_end - 1:test_end + 1]
        test_signals = signals_by_candidate[selected][train_end - 1:test_end + 1]
        # Stitch only signals whose returns belong to this fold. Adjacent folds
        # meet at the same open boundary with no overlap or missing return.
        stitched_oos_signals[train_end - 1:test_end - 1] = (
            signals_by_candidate[selected][train_end - 1:test_end - 1]
        )
        cost_scenarios = {}
        for multiplier in (1, 2, 3):
            scenario = evaluate_candidate(
                test_rows, test_signals, fee_rate * multiplier,
                slippage_rate * multiplier, bars_per_year,
                allocation_fraction=allocation_fraction,
            )
            cost_scenarios[f"{multiplier}x"] = {
                "strategy": scenario["strategy"],
                "buy_and_hold": scenario["buy_and_hold"],
                "excess_return": scenario["excess_return"],
                "strategy_net_returns": scenario["net_returns"],
                "benchmark_net_returns": scenario["benchmark_net_returns"],
            }

        for candidate_name in names:
            candidate_test = evaluate_candidate(
                test_rows,
                signals_by_candidate[candidate_name][train_end - 1:test_end + 1],
                fee_rate,
                slippage_rate,
                bars_per_year,
                allocation_fraction=allocation_fraction,
            )
            fixed_candidate_fold_results[candidate_name].append({
                "fold": len(folds) + 1,
                "test_start_index": train_end,
                "test_end_index_exclusive": test_end,
                "strategy": candidate_test["strategy"],
                "buy_and_hold": candidate_test["buy_and_hold"],
                "excess_return": candidate_test["excess_return"],
            })
        baseline = cost_scenarios["1x"]
        folds.append({
            "fold": len(folds) + 1,
            "training_start_index": 0,
            "training_end_index_exclusive": train_end,
            "test_start_index": train_end,
            "test_end_index_exclusive": test_end,
            "test_return_start_open_index": train_end,
            "test_return_end_open_index": test_end,
            "selected_candidate": selected,
            "training_excess_returns": training_scores,
            "training_closed_trades": training_closed_trades,
            "test_strategy": baseline["strategy"],
            "test_buy_and_hold": baseline["buy_and_hold"],
            "test_excess_return": baseline["excess_return"],
            "cost_scenarios": cost_scenarios,
            "selection_rule": "max_training_excess_return_vs_matched_buy_and_hold_at_1x_cost",
            "drawdown_measurement": "open_to_open_equity",
        })
        train_end = test_end

    if not folds:
        raise ValueError("data does not contain a complete test fold")
    final_test_end = folds[-1]["test_end_index_exclusive"]
    aggregate_rows = candles[initial_train_bars - 1:final_test_end + 1]
    aggregate_signals = stitched_oos_signals[initial_train_bars - 1:final_test_end + 1]
    aggregate_cost_scenarios = {}
    for multiplier in (1, 2, 3):
        aggregate = evaluate_candidate(
            aggregate_rows,
            aggregate_signals,
            fee_rate * multiplier,
            slippage_rate * multiplier,
            bars_per_year,
            allocation_fraction=allocation_fraction,
        )
        strategy_summary = _path_summary(aggregate["net_returns"])
        strategy_summary.update({
            "closed_trades": aggregate["strategy"]["closed_trades"],
            "exposure": aggregate["strategy"]["exposure"],
            "turnover": aggregate["strategy"]["turnover"],
            "open_position_at_end": aggregate["strategy"]["open_position_at_end"],
            "periodic_profit_factor": aggregate["strategy"]["profit_factor"],
            "period_sharpe": aggregate["strategy"]["period_sharpe"],
            "bar_return_volatility": aggregate["strategy"]["bar_return_volatility"],
        })
        benchmark_summary = _path_summary(aggregate["benchmark_net_returns"])
        aggregate_cost_scenarios[f"{multiplier}x"] = {
            "strategy": strategy_summary,
            "buy_and_hold": benchmark_summary,
            "excess_return": strategy_summary["net_return"] - benchmark_summary["net_return"],
            "benchmark_entry_cost_charged_once": True,
            "fold_boundary_exposure_is_continuous": True,
        }

    regime_labels = _market_regime_labels(candles)
    fixed_candidate_results = {}
    for name in names:
        candidate_signal_rows = signals_by_candidate[name][initial_train_bars - 1:final_test_end + 1]
        candidate_cost_scenarios = {}
        candidate_reports = {}
        for multiplier in (1, 2, 3):
            candidate_report = evaluate_candidate(
                aggregate_rows,
                candidate_signal_rows,
                fee_rate * multiplier,
                slippage_rate * multiplier,
                bars_per_year,
                allocation_fraction=allocation_fraction,
            )
            candidate_reports[f"{multiplier}x"] = candidate_report
            candidate_cost_scenarios[f"{multiplier}x"] = {
                "strategy": candidate_report["strategy"],
                "buy_and_hold": candidate_report["buy_and_hold"],
                "excess_return": candidate_report["excess_return"],
            }
        base_candidate = candidate_reports["1x"]
        return_count = len(base_candidate["net_returns"])
        signal_rows = candidate_signal_rows[:return_count]
        signal_regimes = regime_labels[
            initial_train_bars - 1:initial_train_bars - 1 + return_count
        ]
        regime_metrics = _regime_attribution(
            base_candidate["net_returns"], signal_rows, signal_regimes
        )
        fixed_candidate_results[name] = {
            "folds": fixed_candidate_fold_results[name],
            "aggregate_oos_cost_scenarios": candidate_cost_scenarios,
            "regime_attribution": regime_metrics,
        }
    fixed_candidate_walk_forward = {
        "protocol": "fixed_candidate_expanding_window_walk_forward_all_candidates",
        "candidate_count": len(names),
        "fold_count": len(folds),
        "max_folds": max_folds,
        "initial_train_bars": initial_train_bars,
        "test_bars": test_bars,
        "regime_classification": (
            "Bullish when close is above SMA200 and SMA200 is above its value 20 bars earlier; "
            "bearish when close is below SMA200 and SMA200 is below its value 20 bars earlier; "
            "otherwise sideways/transition."
        ),
        "regime_measurement": (
            "Each net open-to-open return is attributed to the regime known at its signal close. "
            "Regime log contributions reconcile to total OOS log growth; they are descriptive "
            "conditional contributions, not separately executable regime portfolios."
        ),
        "candidates": fixed_candidate_results,
        "limitations": [
            "Every fixed candidate is evaluated on the same contiguous OOS folds without per-fold candidate selection.",
            "Signal builders must remain causal; this routine evaluates but does not prove prefix causality.",
            "Fixed costs omit spread, depth, impact, latency, and intrabar tick paths.",
            "Regime contributions are attribution diagnostics, not independent regime portfolios.",
        ],
    }
    return {
        "protocol": "expanding_window_rolling_walk_forward_frozen_candidate",
        "fold_count": len(folds),
        "initial_train_bars": initial_train_bars,
        "test_bars": test_bars,
        "allocation_fraction": allocation_fraction,
        "candidate_count": len(names),
        "candidate_names": names,
        "folds": folds,
        "aggregate_oos_cost_scenarios": aggregate_cost_scenarios,
        "fixed_candidate_walk_forward": fixed_candidate_walk_forward,
        "max_folds": max_folds,
        "tested_through_index_exclusive": final_test_end + 1,
        "tested_through_open_index": final_test_end,
        "unused_tail_start_index": final_test_end + 1,
        "unused_tail_bars": len(candles) - (final_test_end + 1),
        "unused_tail_fraction": (len(candles) - (final_test_end + 1)) / len(candles),
        "unused_tail_scope": (
            "Excluded from this walk-forward calculation only; not an untouched holdout "
            "if previously exposed by other historical reports or experiments."
            if len(candles) > final_test_end + 1 else "No trailing bars were left unused."
        ),
        "promotion_status": "NO_CANDIDATE_PROMOTED",
        "limitations": [
            "Candidate definitions and parameters must be frozen before this run.",
            "Signals must be causal; this routine cannot prove signal-builder causality.",
            "Selection uses prior training data only. Any unused trailing bars are excluded from this walk-forward run only and are not an untouched holdout if prior reports or experiments exposed them.",
            "Fixed fee/slippage omits spread, depth, impact, latency and intrabar execution.",
            "Small fold trade counts are descriptive and do not establish statistical power.",
        ],
    }
