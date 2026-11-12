"""
Research-only evaluator for completed-bar candidate signals.

Signal at close[t] changes exposure at open[t+1]. Returns are measured
open[t+1] to open[t+2], so no same-bar lookahead is possible.
No account, exchange, order, or paper-ledger integration exists here.
"""
import math

def _validate(candles, signals, fee_rate, slippage_rate, bars_per_year, allocation_fraction):
    if len(candles) != len(signals):
        raise ValueError("candles and signals must have identical lengths")
    if len(candles) < 4:
        raise ValueError("at least four candles are required")
    for name, value in (("fee_rate", fee_rate), ("slippage_rate", slippage_rate)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value >= 1:
            raise ValueError(f"{name} must be finite and in [0, 1)")
    if isinstance(bars_per_year, bool) or not isinstance(bars_per_year, (int, float)) or not math.isfinite(bars_per_year) or bars_per_year <= 0:
        raise ValueError("bars_per_year must be positive and finite")
    if isinstance(allocation_fraction, bool) or not isinstance(allocation_fraction, (int, float)) or not math.isfinite(allocation_fraction) or not 0 < allocation_fraction <= 1:
        raise ValueError("allocation_fraction must be finite and in (0, 1]")
    opens = []
    for row in candles:
        if isinstance(row, dict):
            value = row["open"]
        else:
            if len(row) < 6:
                raise ValueError("OHLCV rows must contain timestamp, open, high, low, close, volume")
            value = row[1]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("open prices must be positive finite numbers")
        opens.append(float(value))
    if any(type(signal) is not bool for signal in signals):
        raise ValueError("signals must contain only bool values")
    return opens

def _max_drawdown(equity):
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst

def _metrics(returns, exposure, turnover, closed_trades, bars_per_year, equity):
    gains = [r for r in returns if r > 0]
    losses = [-r for r in returns if r < 0]
    gross_profit, gross_loss = sum(gains), sum(losses)
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((r-mean)**2 for r in returns) / max(1, len(returns)-1)
    volatility = math.sqrt(variance)
    sharpe = (mean / volatility * math.sqrt(bars_per_year)) if volatility > 0 else None
    return {
        "net_return": equity[-1] - 1.0,
        "max_drawdown": _max_drawdown(equity),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (None if gross_profit == 0 else "infinite"),
        "period_sharpe": sharpe,
        "bars": len(returns),
        "exposure": sum(exposure) / len(exposure) if exposure else 0.0,
        "turnover": sum(turnover),
        "closed_trades": closed_trades,
        "open_position_at_end": bool(exposure and exposure[-1]),
        "mean_bar_return": mean,
        "bar_return_volatility": volatility,
    }

def evaluate_candidate(candles, signals, fee_rate=0.001, slippage_rate=0.0005, bars_per_year=24*365, allocation_fraction=1.0):
    """Evaluate a long/flat signal series with next-open-to-next-open returns.

    Each signal is observed at candle close. Its exposure begins at the next
    candle open. Turnover costs are charged at that open. The first and final
    incomplete intervals are excluded. This is a simplified OHLCV model, not
    a spread, depth, impact, latency, or tick-path simulator.
    """
    opens = _validate(candles, signals, fee_rate, slippage_rate, bars_per_year, allocation_fraction)
    cost_rate = fee_rate + slippage_rate
    strategy_returns, benchmark_returns = [], []
    exposures, turnovers = [], []
    equity, benchmark_equity = [1.0], [1.0]
    previous_position = False
    closed_trades = 0
    for signal_index in range(len(signals)-2):
        position = signals[signal_index]
        turnover = abs(int(position)-int(previous_position))
        gross = opens[signal_index+2] / opens[signal_index+1] - 1.0
        scaled_turnover = allocation_fraction * turnover
        net = (1.0 + allocation_fraction*gross) * (1.0 - cost_rate*scaled_turnover) - 1.0 if position else -cost_rate*scaled_turnover
        strategy_returns.append(net)
        exposures.append(allocation_fraction if position else 0.0)
        turnovers.append(float(scaled_turnover))
        equity.append(equity[-1] * (1.0 + net))
        benchmark_cost = cost_rate * allocation_fraction if signal_index == 0 else 0.0
        benchmark_net = (1.0 + allocation_fraction*gross) * (1.0 - benchmark_cost) - 1.0
        benchmark_returns.append(benchmark_net)
        benchmark_equity.append(benchmark_equity[-1] * (1.0 + benchmark_net))
        if previous_position and not position:
            closed_trades += 1
        previous_position = position
    return {
        "protocol": "completed_close_signal_next_open_fill_open_to_open_return",
        "allocation_fraction": allocation_fraction,
        "cost_model": {"fee_rate_per_turnover_unit": fee_rate, "slippage_rate_per_turnover_unit": slippage_rate, "allocation_scaled_turnover": True, "limitations": "No explicit spread, depth, impact, latency, or intrabar path."},
        "strategy": _metrics(strategy_returns, exposures, turnovers, closed_trades, bars_per_year, equity),
        "buy_and_hold": _metrics(benchmark_returns, [allocation_fraction]*len(benchmark_returns), [allocation_fraction if i == 0 else 0.0 for i in range(len(benchmark_returns))], 0, bars_per_year, benchmark_equity),
        "excess_return": equity[-1] - benchmark_equity[-1],
        "net_returns": strategy_returns,
        "benchmark_net_returns": benchmark_returns,
        "equity_curve": equity,
    }