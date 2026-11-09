"""Research-only health diagnostics for completed paper-strategy trades.

This module classifies observed historical/paper performance for review. It
never places orders, changes strategy parameters, or approves live trading.
"""
import math


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be numeric".format(label))
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("{} must be finite".format(label))
    return value


def _trade_pnl(trade, index):
    if isinstance(trade, dict):
        if "pnl" not in trade:
            raise ValueError("trade {} is missing pnl".format(index))
        value = trade["pnl"]
    else:
        value = trade
    return _number(value, "trade {} pnl".format(index))


def _max_drawdown_pct(equity_curve):
    if equity_curve is None:
        return None
    if not isinstance(equity_curve, (list, tuple)):
        raise ValueError("equity_curve must be a list or tuple")
    if not equity_curve:
        return None
    peak = 0.0
    worst = 0.0
    for index, raw in enumerate(equity_curve):
        equity = _number(raw, "equity_curve[{}]".format(index))
        if equity <= 0:
            raise ValueError("equity values must be positive")
        peak = max(peak, equity)
        if peak:
            worst = max(worst, (peak - equity) / peak * 100.0)
    return round(worst, 4)


def evaluate_strategy_health(
    trades,
    equity_curve=None,
    min_trades=20,
    recent_window=20,
    drawdown_warning_pct=8.0,
    drawdown_critical_pct=12.0,
    recent_profit_factor_floor=1.0,
):
    """Return transparent diagnostics; never treat a label as deployment approval.

    Trades must be completed, realized PnL values (numbers or {'pnl': value}).
    Equity points must be chronological, positive account-equity observations.
    """
    if not isinstance(trades, (list, tuple)):
        raise ValueError("trades must be a list or tuple")
    for name, value in (("min_trades", min_trades), ("recent_window", recent_window)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("{} must be a positive integer".format(name))
    warning = _number(drawdown_warning_pct, "drawdown_warning_pct")
    critical = _number(drawdown_critical_pct, "drawdown_critical_pct")
    pf_floor = _number(recent_profit_factor_floor, "recent_profit_factor_floor")
    if warning < 0 or critical <= warning or pf_floor < 0:
        raise ValueError("invalid health thresholds")

    pnls = [_trade_pnl(trade, i) for i, trade in enumerate(trades)]
    recent = pnls[-recent_window:]
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    recent_profit = sum(value for value in recent if value > 0)
    recent_loss = -sum(value for value in recent if value < 0)
    drawdown = _max_drawdown_pct(equity_curve)

    profit_factor = gross_profit / gross_loss if gross_loss else None
    recent_pf = recent_profit / recent_loss if recent_loss else None
    win_count = sum(value > 0 for value in pnls)
    loss_count = sum(value < 0 for value in pnls)

    # Critical risk conditions take precedence over a small sample warning.
    if drawdown is not None and drawdown >= critical:
        status = "STOP_REVIEW"
        reason = "Observed drawdown reached the critical review threshold"
    elif len(recent) >= min_trades and recent_pf is not None and recent_pf < 0.7:
        status = "STOP_REVIEW"
        reason = "Recent realized profit factor is severely weak"
    elif len(pnls) < min_trades:
        status = "INSUFFICIENT_DATA"
        reason = "Not enough completed trades for a reliable health label"
    elif ((drawdown is not None and drawdown >= warning)
          or (recent_pf is not None and recent_pf < pf_floor)):
        status = "WATCH"
        reason = "Drawdown or recent trade quality requires review"
    else:
        status = "OBSERVATION_OK"
        reason = "No configured review trigger was reached in the supplied sample"

    return {
        "status": status,
        "reason": reason,
        "completed_trades": len(pnls),
        "recent_trades": len(recent),
        "wins": win_count,
        "losses": loss_count,
        "win_rate_pct": round(win_count / len(pnls) * 100.0, 2) if pnls else None,
        "net_realized_pnl": round(sum(pnls), 8),
        "gross_profit": round(gross_profit, 8),
        "gross_loss": round(gross_loss, 8),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "profit_factor_unbounded": bool(gross_profit > 0 and gross_loss == 0),
        "recent_profit_factor": round(recent_pf, 4) if recent_pf is not None else None,
        "recent_profit_factor_unbounded": bool(recent_profit > 0 and recent_loss == 0),
        "max_drawdown_pct": drawdown,
        "thresholds": {
            "minimum_completed_trades": min_trades,
            "recent_window": recent_window,
            "drawdown_warning_pct": warning,
            "drawdown_critical_pct": critical,
            "recent_profit_factor_floor": pf_floor,
        },
        "live_trading_approved": False,
        "execution_enabled": False,
    }
