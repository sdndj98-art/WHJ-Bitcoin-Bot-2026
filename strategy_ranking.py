"""Conservative research-only ranking for fixed-rule out-of-sample strategy results.

Scores summarize risk and robustness; they are not forecasts or deployment approval.
"""
import math


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be numeric".format(label))
    try:
        value = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("{} must be finite".format(label)) from exc
    if not math.isfinite(value):
        raise ValueError("{} must be finite".format(label))
    return value


def rank_strategy_results(strategies, min_closed_trades=10, required_windows=3):
    """Rank eligible strategy results using OOS return, drawdown and window consistency.

    Buy-and-hold is a benchmark, not a strategy candidate. Missing or weak samples
    are excluded instead of being assigned a misleading score.
    """
    if not isinstance(strategies, dict):
        raise ValueError("strategies must be a dictionary")
    for label, value in (("min_closed_trades", min_closed_trades),
                         ("required_windows", required_windows)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("{} must be a positive integer".format(label))

    ranked = []
    excluded = []
    for name, result in strategies.items():
        if name == "buy_and_hold":
            continue
        if not isinstance(name, str) or not isinstance(result, dict):
            excluded.append({"strategy": str(name), "status": "INVALID_RESULT"})
            continue
        oos = result.get("out_of_sample")
        windows = result.get("walk_forward_windows")
        if not isinstance(oos, dict) or not isinstance(windows, list):
            excluded.append({"strategy": name, "status": "MISSING_WALK_FORWARD_DATA"})
            continue
        try:
            trades = oos.get("closed_trades")
            if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
                raise ValueError("closed_trades must be a non-negative integer")
            if trades < min_closed_trades:
                excluded.append({
                    "strategy": name, "status": "INSUFFICIENT_TRADES",
                    "closed_trades": trades, "required_trades": min_closed_trades,
                })
                continue
            if len(windows) < required_windows:
                excluded.append({
                    "strategy": name, "status": "INSUFFICIENT_WINDOWS",
                    "window_count": len(windows), "required_windows": required_windows,
                })
                continue
            returns = [
                _finite_number(item["metrics"]["return_pct"], "window return")
                for item in windows
            ]
            if len(returns) != required_windows:
                raise ValueError("unexpected walk-forward window count")
            oos_return = _finite_number(oos.get("return_pct"), "out_of_sample return")
            drawdown = _finite_number(oos.get("max_drawdown_pct"), "max_drawdown_pct")
            if drawdown < 0 or drawdown > 100:
                raise ValueError("max_drawdown_pct must be between 0 and 100")
        except (KeyError, TypeError, ValueError) as exc:
            excluded.append({
                "strategy": name, "status": "INVALID_OR_INCOMPLETE_METRICS",
                "reason": str(exc),
            })
            continue

        worst_window = min(returns)
        positive_windows = sum(value > 0 for value in returns)
        # Each component is bounded 0..100. Returns are deliberately capped so
        # one unusually strong result cannot overwhelm drawdown/consistency.
        components = {
            "net_return": max(0.0, min(100.0, 50.0 + oos_return * 2.0)),
            "drawdown_control": max(0.0, min(100.0, 100.0 - drawdown * 5.0)),
            "worst_window": max(0.0, min(100.0, 50.0 + worst_window * 2.0)),
            "positive_window_consistency": positive_windows / required_windows * 100.0,
            "sample_size": min(100.0, trades / 30.0 * 100.0),
        }
        score = (
            components["net_return"] * 0.25
            + components["drawdown_control"] * 0.25
            + components["worst_window"] * 0.20
            + components["positive_window_consistency"] * 0.20
            + components["sample_size"] * 0.10
        )
        ranked.append({
            "strategy": name,
            "score": round(score, 2),
            "status": "RESEARCH_RANKED",
            "out_of_sample_return_pct": round(oos_return, 2),
            "max_drawdown_pct": round(drawdown, 2),
            "worst_window_return_pct": round(worst_window, 2),
            "positive_windows": positive_windows,
            "window_count": required_windows,
            "closed_trades": trades,
            "components": {key: round(value, 2) for key, value in components.items()},
            "live_trading_approved": False,
            "execution_enabled": False,
        })

    ranked.sort(key=lambda item: (-item["score"], item["strategy"]))
    for position, item in enumerate(ranked, 1):
        item["rank"] = position
    excluded.sort(key=lambda item: item["strategy"])
    return {
        "method": "CONSERVATIVE_OOS_ROBUSTNESS_SCORE_V1",
        "weights_pct": {
            "net_return": 25, "drawdown_control": 25, "worst_window": 20,
            "positive_window_consistency": 20, "sample_size": 10,
        },
        "minimum_closed_trades": min_closed_trades,
        "required_walk_forward_windows": required_windows,
        "ranked_strategies": ranked,
        "excluded_strategies": excluded,
        "research_only": True,
        "live_trading_approved": False,
        "execution_enabled": False,
    }


def _clamp_score(value):
    return max(0.0, min(100.0, float(value)))


def rank_fixed_candidate_walk_forward(
    candidates,
    min_closed_trades=30,
    min_regime_bars=30,
    required_folds=4,
):
    """Rank fixed candidates on OOS, per-candidate walk-forward, risk and robustness.

    This is a transparent relative research score, not a forecast or promotion.
    Every candidate must have the same fold count and 1x/2x/3x evidence.
    """
    if not isinstance(candidates, dict):
        raise ValueError("candidates must be a dictionary")
    for label, value in (
        ("min_closed_trades", min_closed_trades),
        ("min_regime_bars", min_regime_bars),
        ("required_folds", required_folds),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("{} must be a positive integer".format(label))

    weights = {
        "net_return": 20,
        "drawdown_control": 15,
        "worst_fold": 15,
        "positive_fold_consistency": 10,
        "risk_adjusted": 10,
        "cost_robustness": 10,
        "regime_robustness": 10,
        "sample_size": 10,
    }
    ranked = []
    excluded = []
    for name, result in candidates.items():
        if not isinstance(name, str) or not name or not isinstance(result, dict):
            excluded.append({"candidate": str(name), "status": "INVALID_RESULT"})
            continue
        try:
            scenarios = result.get("aggregate_oos_cost_scenarios")
            folds = result.get("folds")
            regimes = result.get("regime_attribution")
            if not isinstance(scenarios, dict) or not isinstance(folds, list):
                raise ValueError("missing aggregate cost scenarios or walk-forward folds")
            if len(folds) != required_folds:
                excluded.append({
                    "candidate": name,
                    "status": "INSUFFICIENT_WALK_FORWARD_FOLDS",
                    "fold_count": len(folds),
                    "required_folds": required_folds,
                })
                continue
            if not isinstance(regimes, dict):
                raise ValueError("missing regime attribution")
            summaries = {
                level: scenarios[level]["strategy"]
                for level in ("1x", "2x", "3x")
            }
            returns = {
                level: _finite_number(summaries[level].get("net_return"), level + " net return") * 100.0
                for level in ("1x", "2x", "3x")
            }
            strategy = summaries["1x"]
            drawdown_value = strategy.get("max_open_to_open_drawdown", strategy.get("max_drawdown"))
            drawdown = abs(_finite_number(
                drawdown_value, "max_open_to_open_drawdown"
            )) * 100.0
            sharpe_value = strategy.get("period_sharpe")
            sharpe = (
                _finite_number(sharpe_value, "period_sharpe")
                if sharpe_value is not None else None
            )
            pf_value = strategy.get("profit_factor", strategy.get("periodic_profit_factor"))
            if pf_value == "infinite" or pf_value == math.inf:
                profit_factor = math.inf
            elif pf_value is None:
                profit_factor = None
            else:
                profit_factor = _finite_number(pf_value, "periodic_profit_factor")
            trades = strategy.get("closed_trades")
            if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
                raise ValueError("closed_trades must be a non-negative integer")

            fold_returns = [
                _finite_number(fold["strategy"]["net_return"], "fold net return") * 100.0
                for fold in folds
            ]
            worst_fold = min(fold_returns)
            positive_folds = sum(value > 0 for value in fold_returns)
            required_positive_folds = math.ceil(required_folds * 0.75)

            regime_counts = {}
            positive_regimes = 0
            regime_coverage = 0
            for regime_name in ("bullish", "bearish", "sideways_transition"):
                item = regimes.get(regime_name)
                if not isinstance(item, dict):
                    raise ValueError("missing regime {}".format(regime_name))
                active_bars = item.get("active_signal_bars")
                if isinstance(active_bars, bool) or not isinstance(active_bars, int) or active_bars < 0:
                    raise ValueError("invalid active_signal_bars for {}".format(regime_name))
                contribution = _finite_number(
                    item.get("net_log_contribution_pct"),
                    regime_name + " net log contribution",
                )
                regime_counts[regime_name] = active_bars
                if active_bars >= min_regime_bars:
                    regime_coverage += 1
                    if contribution > 0:
                        positive_regimes += 1

            sharpe_score = _clamp_score(50.0 + 10.0 * (sharpe if sharpe is not None else -5.0))
            pf_score = (
                100.0 if profit_factor == math.inf
                else _clamp_score(50.0 + 25.0 * ((profit_factor if profit_factor is not None else 0.0) - 1.0))
            )
            components = {
                "net_return": _clamp_score(50.0 + 2.0 * returns["1x"]),
                "drawdown_control": _clamp_score(100.0 - 4.0 * drawdown),
                "worst_fold": _clamp_score(50.0 + 2.0 * worst_fold),
                "positive_fold_consistency": positive_folds / required_folds * 100.0,
                "risk_adjusted": (sharpe_score + pf_score) / 2.0,
                "cost_robustness": _clamp_score(50.0 + 2.0 * min(returns["2x"], returns["3x"])),
                "regime_robustness": positive_regimes / 3.0 * 100.0,
                "sample_size": min(100.0, trades / float(min_closed_trades) * 100.0),
            }
            score = sum(components[key] * weights[key] / 100.0 for key in weights)
            passes = (
                returns["1x"] > 0 and returns["2x"] > 0 and returns["3x"] > 0
                and drawdown <= 15.0
                and profit_factor is not None and profit_factor > 1.0
                and sharpe is not None and sharpe > 0
                and trades >= min_closed_trades
                and positive_folds >= required_positive_folds
                and regime_coverage == 3 and positive_regimes >= 2
            )
            if passes:
                status = "PASS_RESEARCH_SCREEN"
            elif trades < min_closed_trades:
                status = "INSUFFICIENT_TRADES"
            elif regime_coverage < 3:
                status = "INSUFFICIENT_REGIME_COVERAGE"
            else:
                status = "NO_PASS"
            ranked.append({
                "candidate": name,
                "score": round(score, 2),
                "screening_status": status,
                "eligible_for_next_stage": passes,
                "metrics": {
                    "net_return_1x_pct": round(returns["1x"], 4),
                    "net_return_2x_pct": round(returns["2x"], 4),
                    "net_return_3x_pct": round(returns["3x"], 4),
                    "max_drawdown_pct": round(drawdown, 4),
                    "profit_factor": "infinite" if profit_factor == math.inf else (
                        round(profit_factor, 4) if profit_factor is not None else None
                    ),
                    "periodic_profit_factor": "infinite" if profit_factor == math.inf else (
                        round(profit_factor, 4) if profit_factor is not None else None
                    ),
                    "period_sharpe": round(sharpe, 4) if sharpe is not None else None,
                    "closed_trades": trades,
                    "fold_returns_pct": [round(value, 4) for value in fold_returns],
                    "positive_folds": positive_folds,
                    "worst_fold_return_pct": round(worst_fold, 4),
                    "regime_active_signal_bars": regime_counts,
                    "regime_coverage_count": regime_coverage,
                    "positive_regime_count": positive_regimes,
                },
                "components": {key: round(value, 2) for key, value in components.items()},
                "live_trading_approved": False,
                "execution_enabled": False,
            })
        except (KeyError, TypeError, ValueError) as exc:
            excluded.append({
                "candidate": name,
                "status": "INVALID_OR_INCOMPLETE_METRICS",
                "reason": str(exc),
            })

    ranked.sort(key=lambda item: (
        -item["score"],
        -item["metrics"]["net_return_1x_pct"],
        item["metrics"]["max_drawdown_pct"],
        item["candidate"],
    ))
    for position, item in enumerate(ranked, 1):
        item["rank"] = position
    excluded.sort(key=lambda item: item["candidate"])
    return {
        "method": "FIXED_CANDIDATE_WALK_FORWARD_EVIDENCE_SCORE_V1",
        "weights_pct": weights,
        "minimum_closed_trades": min_closed_trades,
        "minimum_active_bars_per_regime": min_regime_bars,
        "required_walk_forward_folds": required_folds,
        "required_positive_folds": math.ceil(required_folds * 0.75),
        "required_positive_regimes": 2,
        "screening_rules": [
            "positive net return at 1x, 2x, and 3x costs",
            "maximum drawdown <= 15%",
            "periodic profit factor > 1 and period Sharpe > 0",
            "at least 30 closed trades",
            "at least 75% positive walk-forward folds",
            "at least 30 active signal bars in all three regimes and positive contribution in at least two",
        ],
        "ranked_candidates": ranked,
        "excluded_candidates": excluded,
        "candidate_count": len(ranked) + len(excluded),
        "passed_count": sum(item["eligible_for_next_stage"] for item in ranked),
        "research_only": True,
        "promotion_status": "NO_CANDIDATE_PROMOTED",
        "live_trading_approved": False,
        "execution_enabled": False,
    }
