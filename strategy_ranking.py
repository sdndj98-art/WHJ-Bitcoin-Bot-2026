"""Conservative research-only ranking for fixed-rule out-of-sample strategy results.

Scores summarize risk and robustness; they are not forecasts or deployment approval.
"""
import math


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be numeric".format(label))
    value = float(value)
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
