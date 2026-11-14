"""Conservative OHLC execution and adverse-excursion research simulator.

This is isolated research code. It does not connect to exchanges, paper ledgers,
wallets, schedules, or order execution pathways.

Signals are assumed to be formed after a completed bar and are actionable at
the following bar's open. Long stop/target collisions resolve stop-first.
"""
import math

INITIAL_EQUITY = 1000.0


def simulate_ohlc_risk(
    opens, highs, lows, closes, entry_signals, exit_signals,
    fee=0.001, slippage=0.0005, allocation_fraction=0.25,
    stop_loss_pct=0.02, take_profit_pct=0.04,
):
    """Simulate long/cash entries at next open with conservative OHLC stops.

    When both stop and target lie inside one candle's range, stop is assumed
    first because intrabar ordering is unavailable. A gap below the stop fills
    at the opening price (then adverse slippage), never at the more favourable
    stop price. Exit signals from the previous completed bar execute at next
    open before that bar's intraday range is considered.

    Intrabar drawdown is a conservative OHLC envelope: the bar high marks a
    possible equity peak and the bar low marks a possible liquidation trough.
    It is not a tick-level path reconstruction.
    """
    arrays = (opens, highs, lows, closes, entry_signals, exit_signals)
    if any(not isinstance(x, (list, tuple)) for x in arrays):
        raise ValueError("OHLC and signal inputs must be lists or tuples")
    n = len(closes)
    if n < 2 or any(len(x) != n for x in arrays):
        raise ValueError("OHLC and signal arrays must have equal length >= 2")
    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        vals = (o, h, l, c)
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or v <= 0 for v in vals):
            raise ValueError("OHLC prices must be finite positive numbers")
        if h < max(o, l, c) or l > min(o, h, c):
            raise ValueError("Invalid OHLC candle at index %d" % i)
    if any(type(x) is not bool for seq in (entry_signals, exit_signals) for x in seq):
        raise ValueError("Signals must contain booleans")
    if not (0 <= fee < 1 and 0 <= slippage < 1):
        raise ValueError("Fee and slippage must be in [0, 1)")
    if not (0 < allocation_fraction <= 0.25):
        raise ValueError("Allocation may not exceed the 25% research cap")
    if not (0 < stop_loss_pct < 1 and 0 < take_profit_pct < 10):
        raise ValueError("Stop and target percentages are outside valid bounds")

    cash = INITIAL_EQUITY
    units = 0.0
    entry_cash = 0.0
    stop_price = None
    target_price = None
    closed_pnls = []
    exits = []
    peak_equity = INITIAL_EQUITY
    max_intrabar_dd = 0.0
    peak_close_equity = INITIAL_EQUITY
    max_close_dd = 0.0

    def liquidation_at(price):
        if units <= 0:
            return cash
        gross = units * price * (1.0 - slippage)
        return cash + gross * (1.0 - fee)

    def close_position(raw_price, reason, index, gap=False):
        nonlocal cash, units, entry_cash, stop_price, target_price, max_intrabar_dd
        fill = raw_price * (1.0 - slippage)
        proceeds = units * fill * (1.0 - fee)
        pnl = proceeds - entry_cash
        cash += proceeds
        # A realized exit can close the position before the normal OHLC
        # high/low mark below. Record its post-exit equity against the
        # preceding intrabar peak so stopped/gap exits cannot disappear
        # from the intrabar drawdown metric.
        if peak_equity > 0:
            max_intrabar_dd = max(
                max_intrabar_dd,
                (peak_equity - cash) / peak_equity * 100.0,
            )
        closed_pnls.append(pnl)
        exits.append({
            "index": index, "reason": reason,
            "raw_reference_price": round(raw_price, 8),
            "fill_price_after_slippage": round(fill, 8),
            "gap_through_stop": bool(gap),
            "net_pnl_usd": round(pnl, 4),
        })
        units = 0.0
        entry_cash = 0.0
        stop_price = None
        target_price = None

    for i in range(1, n):
        # Only the previous completed candle's signals can act at this open.
        if units > 0 and exit_signals[i - 1]:
            close_position(opens[i], "signal_exit_at_next_open", i)
        elif units == 0 and entry_signals[i - 1]:
            allocation = cash * allocation_fraction
            entry_fill = opens[i] * (1.0 + slippage)
            fee_paid = allocation * fee
            units = (allocation - fee_paid) / entry_fill
            cash -= allocation
            entry_cash = allocation
            stop_price = entry_fill * (1.0 - stop_loss_pct)
            target_price = entry_fill * (1.0 + take_profit_pct)

        if units > 0:
            # Opening gaps are handled before intrabar touches.
            if opens[i] <= stop_price:
                close_position(opens[i], "stop_loss_gap", i, gap=True)
            elif opens[i] >= target_price:
                close_position(opens[i], "take_profit_gap", i)
            else:
                # The position survived the opening-gap checks. Mark the bar
                # high before resolving an intrabar stop/target so a same-bar
                # peak cannot disappear merely because the stop closes first.
                high_equity = liquidation_at(highs[i])
                peak_equity = max(peak_equity, high_equity)
                stop_hit = lows[i] <= stop_price
                target_hit = highs[i] >= target_price
                if stop_hit:
                    # The stop fill is the liquidation trough once triggered;
                    # do not mark a lower post-exit wick as if still exposed.
                    # If both are touched, pessimistically assume stop first.
                    close_position(stop_price, "stop_loss_adverse_order" if target_hit
                                   else "stop_loss", i)
                elif target_hit:
                    low_equity = liquidation_at(lows[i])
                    if peak_equity > 0:
                        max_intrabar_dd = max(
                            max_intrabar_dd,
                            (peak_equity - low_equity) / peak_equity * 100.0,
                        )
                    close_position(target_price, "take_profit", i)
                else:
                    low_equity = liquidation_at(lows[i])
                    if peak_equity > 0:
                        max_intrabar_dd = max(
                            max_intrabar_dd,
                            (peak_equity - low_equity) / peak_equity * 100.0,
                        )

        if units > 0:
            close_equity = liquidation_at(closes[i])
        else:
            peak_equity = max(peak_equity, cash)
            close_equity = cash

        peak_close_equity = max(peak_close_equity, close_equity)
        if peak_close_equity > 0:
            max_close_dd = max(
                max_close_dd,
                (peak_close_equity - close_equity) / peak_close_equity * 100.0,
            )

    if units > 0:
        final_equity = liquidation_at(closes[-1])
        unrealized_pnl = final_equity - cash - entry_cash
    else:
        final_equity = cash
        unrealized_pnl = 0.0

    gross_profit = sum(x for x in closed_pnls if x > 0)
    gross_loss = -sum(x for x in closed_pnls if x < 0)
    pf = round(gross_profit / gross_loss, 4) if gross_loss else (
        None if gross_profit else 0.0
    )
    return {
        "mode": "OHLC_CONSERVATIVE_NEXT_OPEN_LONG_CASH",
        "research_only": True,
        "execution_enabled": False,
        "initial_equity_usd": INITIAL_EQUITY,
        "final_net_liquidation_equity_usd": round(final_equity, 4),
        "return_pct": round((final_equity / INITIAL_EQUITY - 1) * 100, 4),
        "max_intrabar_ohlc_envelope_drawdown_pct": round(max_intrabar_dd, 4),
        "max_close_to_close_drawdown_pct": round(max_close_dd, 4),
        "intrabar_drawdown_method": "bar_high_peak_to_bar_low_liquidation_trough_conservative_envelope",
        "closed_trades": len(closed_pnls),
        "closed_trade_profit_factor": pf,
        "realized_pnl_usd": round(sum(closed_pnls), 4),
        "open_position_count": int(units > 0),
        "unrealized_net_liquidation_pnl_usd": round(unrealized_pnl, 4),
        "exit_events": exits,
        "assumptions": {
            "signal_execution": "next_bar_open",
            "same_bar_stop_target_collision": "stop_first",
            "gap_through_stop": "fill_at_open_plus_adverse_slippage",
            "fees": "fixed_fraction_per_side",
            "slippage": "fixed_fraction_per_side",
            "max_allocation_fraction": 0.25,
            "ohlc_path": "unknown; conservative high-low envelope, not tick reconstruction",
        },
    }
