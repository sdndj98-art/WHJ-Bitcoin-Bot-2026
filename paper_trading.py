"""Historical paper-trading simulation. This module never sends exchange orders."""


def run_backtest(prices, initial_cash=1000.0, fee_rate=0.001, slippage_rate=0.0005):
    if len(prices) < 51:
        raise ValueError("At least 51 prices are required for a next-candle backtest")
    if initial_cash <= 0 or not 0 <= fee_rate < 1 or not 0 <= slippage_rate < 1:
        raise ValueError("Invalid cash, fee, or slippage configuration")
    if any(not isinstance(p, (int, float)) or p <= 0 for p in prices):
        raise ValueError("Prices must be positive numbers")

    cash = float(initial_cash)
    btc = 0.0
    entry_cost = 0.0
    fees_paid = 0.0
    trades = []
    position_open = False

    # Signal uses completed candles before i; execution occurs at candle i.
    for i in range(50, len(prices)):
        history = prices[i - 50:i]
        sma20 = sum(history[-20:]) / 20
        sma50 = sum(history) / 50
        reference_price = float(prices[i])

        if reference_price > sma20 > sma50 and not position_open:
            fill = reference_price * (1 + slippage_rate)
            fee = cash * fee_rate
            spendable = cash - fee
            btc = spendable / fill
            fees_paid += fee
            entry_cost = cash
            cash = 0.0
            position_open = True
        elif reference_price < sma20 < sma50 and position_open:
            fill = reference_price * (1 - slippage_rate)
            gross = btc * fill
            fee = gross * fee_rate
            cash = gross - fee
            fees_paid += fee
            pnl = cash - entry_cost
            trades.append({"pnl": round(pnl, 2), "result": "WIN" if pnl > 0 else "LOSS"})
            btc = 0.0
            entry_cost = 0.0
            position_open = False

    last_price = float(prices[-1])
    final_equity = cash + btc * last_price
    wins = sum(1 for trade in trades if trade["result"] == "WIN")
    return {
        "mode": "HISTORICAL_PAPER_BACKTEST",
        "initial_cash_usd": round(initial_cash, 2),
        "final_equity_usd": round(final_equity, 2),
        "return_pct": round((final_equity / initial_cash - 1) * 100, 2),
        "completed_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 2) if trades else 0.0,
        "fees_paid_usd": round(fees_paid, 2),
        "open_position": position_open,
        "unrealized_pnl_usd": round(final_equity - entry_cost, 2) if position_open else 0.0,
        "trade_log": trades,
        "execution_assumption": "Next-candle close with modeled fee and slippage; no real orders."
    }
