"""Historical paper-trading simulation. This module never sends exchange orders."""
import math


def run_backtest(prices, initial_cash=1000.0, fee_rate=0.001, slippage_rate=0.0005):
    if len(prices) < 51:
        raise ValueError("At least 51 prices are required for a next-candle backtest")
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("Initial cash must be a finite positive number")
    if (not math.isfinite(fee_rate) or not math.isfinite(slippage_rate)
            or not 0 <= fee_rate < 1 or not 0 <= slippage_rate < 1):
        raise ValueError("Invalid fee or slippage configuration")
    if any(not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0
           for p in prices):
        raise ValueError("Prices must be finite positive numbers")

    cash = float(initial_cash)
    btc = 0.0
    entry_cost = 0.0
    fees_paid = 0.0
    trades = []
    position_open = False
    equity_peak = float(initial_cash)
    max_drawdown_pct = 0.0
    current_loss_streak = 0
    max_loss_streak = 0

    # Signal uses the 50 completed candles before i; execution is at candle i.
    for i in range(50, len(prices)):
        history = prices[i - 50:i]
        sma20 = sum(history[-20:]) / 20
        sma50 = sum(history) / 50
        signal_price = float(history[-1])
        reference_price = float(prices[i])

        if signal_price > sma20 > sma50 and not position_open:
            fill = reference_price * (1 + slippage_rate)
            fee = cash * fee_rate
            spendable = cash - fee
            btc = spendable / fill
            fees_paid += fee
            entry_cost = cash
            cash = 0.0
            position_open = True
        elif signal_price < sma20 < sma50 and position_open:
            fill = reference_price * (1 - slippage_rate)
            gross = btc * fill
            fee = gross * fee_rate
            cash = gross - fee
            fees_paid += fee
            pnl = cash - entry_cost
            result = "WIN" if pnl > 0 else "LOSS"
            trades.append({"pnl": round(pnl, 2), "result": result})
            if result == "LOSS":
                current_loss_streak += 1
                max_loss_streak = max(max_loss_streak, current_loss_streak)
            else:
                current_loss_streak = 0
            btc = 0.0
            entry_cost = 0.0
            position_open = False

        equity = cash + btc * reference_price
        equity_peak = max(equity_peak, equity)
        if equity_peak > 0:
            drawdown = (equity_peak - equity) / equity_peak * 100
            max_drawdown_pct = max(max_drawdown_pct, drawdown)

    last_price = float(prices[-1])
    if position_open:
        estimated_exit_value = btc * last_price * (1 - slippage_rate)
        estimated_exit_value -= estimated_exit_value * fee_rate
        final_equity = cash + estimated_exit_value
    else:
        final_equity = cash
    wins = [trade["pnl"] for trade in trades if trade["pnl"] > 0]
    losses = [-trade["pnl"] for trade in trades if trade["pnl"] < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    profit_factor = gross_profit / gross_loss if gross_loss else (
        float("inf") if gross_profit else 0.0
    )

    return {
        "mode": "HISTORICAL_PAPER_BACKTEST",
        "initial_cash_usd": round(initial_cash, 2),
        "final_equity_usd": round(final_equity, 2),
        "return_pct": round((final_equity / initial_cash - 1) * 100, 2),
        "completed_trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "average_trade_pnl_usd": round(
            sum(trade["pnl"] for trade in trades) / len(trades), 2
        ) if trades else 0.0,
        "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else None,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "max_consecutive_losses": max_loss_streak,
        "gross_profit_usd": round(gross_profit, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "fees_paid_usd": round(fees_paid, 2),
        "open_position": position_open,
        "estimated_liquidation_value": position_open,
        "unrealized_pnl_usd": round(final_equity - entry_cost, 2) if position_open else 0.0,
        "trade_log": trades,
        "execution_assumption": "Signal uses only prior completed candles; execution is modeled at the next candle close with fee and slippage; no real orders."
    }
