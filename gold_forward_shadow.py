"""Independent forward-only COMEX gold shadow-paper ledger.

Research utility only. It never connects to a broker or places orders.
Historical bars are used only for indicator warm-up; no historical trades are booked.
"""
import json
import math
import os
import tempfile
from pathlib import Path

STRATEGIES = ("ema50_200", "ema50_200_atr90_past180")
INITIAL_CASH = 1000.0
ALLOCATION = 0.25
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0005
STOP_LOSS = 0.02
TAKE_PROFIT = 0.04
MAX_DRAWDOWN_PAUSE = 8.0


def _validate_bars(bars):
    if not isinstance(bars, (list, tuple)) or len(bars) < 280:
        raise ValueError("At least 280 daily OHLCV bars are required")
    clean = []
    previous = None
    for row in bars:
        if not isinstance(row, dict):
            raise ValueError("Each daily bar must be an object")
        stamp = row.get("timestamp")
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
            raise ValueError("Daily timestamp must be a positive integer")
        if previous is not None and stamp <= previous:
            raise ValueError("Daily timestamps must be strictly increasing")
        previous = stamp
        values = {}
        for key in ("open", "high", "low", "close"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Daily OHLC values must be finite and positive")
            values[key] = float(value)
        if values["high"] < max(values["open"], values["low"], values["close"]) or values["low"] > min(values["open"], values["high"], values["close"]):
            raise ValueError("Impossible daily OHLC relationship")
        clean.append({"timestamp": stamp, **values})
    return clean


def _ema(values, period):
    result = [None] * len(values)
    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        result[i] = current
    return result


def _atr_pct(bars, period=14):
    true_ranges = []
    for i, bar in enumerate(bars):
        previous_close = bars[i - 1]["close"] if i else bar["close"]
        true_ranges.append(max(
            bar["high"] - bar["low"],
            abs(bar["high"] - previous_close),
            abs(bar["low"] - previous_close),
        ))
    out = [None] * len(bars)
    value = sum(true_ranges[:period]) / period
    out[period - 1] = value / bars[period - 1]["close"]
    for i in range(period, len(bars)):
        value = (value * (period - 1) + true_ranges[i]) / period
        out[i] = value / bars[i]["close"]
    return out


def build_signals(bars):
    rows = _validate_bars(bars)
    closes = [x["close"] for x in rows]
    fast, slow = _ema(closes, 50), _ema(closes, 200)
    atr = _atr_pct(rows)
    baseline = [False] * len(rows)
    filtered = [False] * len(rows)
    for i in range(200, len(rows)):
        trend = fast[i] > slow[i] and closes[i] > slow[i]
        baseline[i] = bool(trend)
        history = [x for x in atr[max(0, i - 180):i] if x is not None]
        if trend and len(history) == 180 and atr[i] is not None:
            ordered = sorted(history)
            # Conservative nearest-rank 90th percentile, using only prior bars.
            cutoff = ordered[math.ceil(0.90 * len(ordered)) - 1]
            filtered[i] = atr[i] <= cutoff
    return {"ema50_200": baseline, "ema50_200_atr90_past180": filtered}


def seed_gold_shadow_state(bars, strategy, initial_cash=INITIAL_CASH):
    """Seed from history without creating trades or changing equity."""
    rows = _validate_bars(bars)
    if strategy not in STRATEGIES:
        raise ValueError("Unknown gold shadow strategy")
    if isinstance(initial_cash, bool) or not isinstance(initial_cash, (int, float)) or not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("Initial cash must be finite and positive")
    signals = build_signals(rows)[strategy]
    return {
        "schema_version": 1,
        "asset": "GC=F",
        "strategy": strategy,
        "mode": "FORWARD_ONLY_SHADOW_PAPER",
        "initial_cash_usd": float(initial_cash),
        "cash_usd": float(initial_cash),
        "units": 0.0,
        "entry_fill_price": None,
        "entry_cost_usd": 0.0,
        "stop_price": None,
        "target_price": None,
        "last_processed_timestamp": rows[-1]["timestamp"],
        "last_completed_signal": bool(signals[-1]),
        "equity_usd": float(initial_cash),
        "peak_equity_usd": float(initial_cash),
        "max_drawdown_pct": 0.0,
        "fees_paid_usd": 0.0,
        "completed_trades": 0,
        "wins": 0,
        "losses": 0,
        "realized_pnl_usd": 0.0,
        "risk_pause_reasons": [],
        "trade_log": [],
        "live_trading_eligible": False,
        "historical_trades_booked": 0,
    }


def _close_position(state, raw_price, reason, timestamp, gap=False):
    fill = raw_price * (1.0 - SLIPPAGE_PER_SIDE)
    gross = state["units"] * fill
    fee = gross * FEE_PER_SIDE
    proceeds = gross - fee
    pnl = proceeds - state["entry_cost_usd"]
    state["cash_usd"] += proceeds
    state["fees_paid_usd"] += fee
    state["realized_pnl_usd"] += pnl
    state["completed_trades"] += 1
    if pnl > 0:
        state["wins"] += 1
    else:
        state["losses"] += 1
    state["trade_log"].append({
        "timestamp": timestamp,
        "reason": reason,
        "net_pnl_usd": round(pnl, 4),
        "gap_through_stop": bool(gap),
    })
    state["units"] = 0.0
    state["entry_fill_price"] = None
    state["entry_cost_usd"] = 0.0
    state["stop_price"] = None
    state["target_price"] = None


def _validate_shadow_state(state):
    """Reject corrupt or incompatible ledgers before any candle is processed."""
    if not isinstance(state, dict):
        raise ValueError("Invalid gold shadow state")
    if state.get("schema_version") != 1 or state.get("mode") != "FORWARD_ONLY_SHADOW_PAPER":
        raise ValueError("Invalid gold shadow state")
    if state.get("asset") != "GC=F":
        raise ValueError("Gold shadow ledger asset mismatch")
    if state.get("strategy") not in STRATEGIES:
        raise ValueError("Unknown strategy in gold shadow state")

    required_numbers = (
        "initial_cash_usd", "cash_usd", "units", "entry_cost_usd",
        "equity_usd", "peak_equity_usd", "max_drawdown_pct",
        "fees_paid_usd", "realized_pnl_usd",
    )
    for key in required_numbers:
        value = state.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Invalid numeric field in gold shadow state: " + key)
    if state["initial_cash_usd"] <= 0 or state["cash_usd"] < 0 or state["units"] < 0:
        raise ValueError("Invalid cash or position size in gold shadow state")
    if state["entry_cost_usd"] < 0 or state["fees_paid_usd"] < 0:
        raise ValueError("Invalid cost field in gold shadow state")
    if state["equity_usd"] <= 0 or state["peak_equity_usd"] < state["equity_usd"]:
        raise ValueError("Invalid equity checkpoint in gold shadow state")
    if not 0 <= state["max_drawdown_pct"] <= 100:
        raise ValueError("Invalid drawdown checkpoint in gold shadow state")

    timestamp = state.get("last_processed_timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
        raise ValueError("Gold shadow checkpoint timestamp is invalid")
    if type(state.get("last_completed_signal")) is not bool:
        raise ValueError("Invalid signal checkpoint in gold shadow state")
    if state.get("live_trading_eligible") is not False or state.get("historical_trades_booked") != 0:
        raise ValueError("Unsafe gold shadow ledger flags")
    if not isinstance(state.get("risk_pause_reasons"), list) or any(
        not isinstance(reason, str) or not reason for reason in state["risk_pause_reasons"]
    ):
        raise ValueError("Invalid risk pause reasons in gold shadow state")

    for key in ("completed_trades", "wins", "losses"):
        value = state.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Invalid trade counter in gold shadow state: " + key)
    log = state.get("trade_log")
    if not isinstance(log, list) or len(log) != state["completed_trades"]:
        raise ValueError("Trade log and completed-trade count do not match")
    if state["wins"] + state["losses"] != state["completed_trades"]:
        raise ValueError("Win/loss counters do not match completed trades")
    logged_pnl = 0.0
    for trade in log:
        if not isinstance(trade, dict):
            raise ValueError("Invalid trade-log entry")
        pnl = trade.get("net_pnl_usd")
        stamp = trade.get("timestamp")
        if isinstance(pnl, bool) or not isinstance(pnl, (int, float)) or not math.isfinite(pnl):
            raise ValueError("Invalid trade-log PnL")
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
            raise ValueError("Invalid trade-log timestamp")
        if not isinstance(trade.get("reason"), str) or type(trade.get("gap_through_stop")) is not bool:
            raise ValueError("Invalid trade-log metadata")
        logged_pnl += pnl
    tolerance = max(0.01, len(log) * 0.00006)
    if abs(logged_pnl - state["realized_pnl_usd"]) > tolerance:
        raise ValueError("Realized PnL does not reconcile with trade log")

    if state["units"] > 0:
        for key in ("entry_fill_price", "stop_price", "target_price"):
            value = state.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid open-position field in gold shadow state: " + key)
        if state["entry_cost_usd"] <= 0:
            raise ValueError("Open position is missing its entry cost")
    elif (state.get("entry_fill_price") is not None or state.get("stop_price") is not None
          or state.get("target_price") is not None or state["entry_cost_usd"] != 0):
        raise ValueError("Flat gold shadow ledger contains stale position fields")


def advance_gold_shadow_state(bars, state):
    """Process each unseen daily candle once, using prior-close signals at next open."""
    rows = _validate_bars(bars)
    _validate_shadow_state(state)
    signals = build_signals(rows)[state["strategy"]]
    by_timestamp = {row["timestamp"]: i for i, row in enumerate(rows)}
    checkpoint = state["last_processed_timestamp"]
    if checkpoint not in by_timestamp:
        raise ValueError("Checkpoint candle is absent; refusing unsafe reseed")
    start = by_timestamp[checkpoint]
    if start == len(rows) - 1:
        return state
    for i in range(start + 1, len(rows)):
        bar = rows[i]
        prior_signal = bool(signals[i - 1])
        if state["risk_pause_reasons"]:
            prior_signal = False
        if state["units"] > 0 and not prior_signal:
            _close_position(state, bar["open"], "ema_signal_exit_next_open", bar["timestamp"])
        elif state["units"] <= 0 and prior_signal and not state["risk_pause_reasons"]:
            allocation = state["cash_usd"] * ALLOCATION
            entry_fill = bar["open"] * (1.0 + SLIPPAGE_PER_SIDE)
            fee = allocation * FEE_PER_SIDE
            state["units"] = (allocation - fee) / entry_fill
            state["cash_usd"] -= allocation
            state["fees_paid_usd"] += fee
            state["entry_fill_price"] = entry_fill
            state["entry_cost_usd"] = allocation
            state["stop_price"] = entry_fill * (1.0 - STOP_LOSS)
            state["target_price"] = entry_fill * (1.0 + TAKE_PROFIT)

        if state["units"] > 0:
            if bar["open"] <= state["stop_price"]:
                _close_position(state, bar["open"], "stop_loss_gap", bar["timestamp"], True)
            elif bar["open"] >= state["target_price"]:
                _close_position(state, bar["open"], "take_profit_gap", bar["timestamp"])
            else:
                stop_hit = bar["low"] <= state["stop_price"]
                target_hit = bar["high"] >= state["target_price"]
                if stop_hit:
                    _close_position(state, state["stop_price"], "stop_first_same_bar" if target_hit else "stop_loss", bar["timestamp"])
                elif target_hit:
                    _close_position(state, state["target_price"], "take_profit", bar["timestamp"])

        if state["units"] > 0:
            gross_exit = state["units"] * bar["close"] * (1 - SLIPPAGE_PER_SIDE)
            estimated_equity = state["cash_usd"] + gross_exit * (1 - FEE_PER_SIDE)
        else:
            estimated_equity = state["cash_usd"]
        state["equity_usd"] = estimated_equity
        state["peak_equity_usd"] = max(state["peak_equity_usd"], estimated_equity)
        drawdown = (state["peak_equity_usd"] - estimated_equity) / state["peak_equity_usd"] * 100
        state["max_drawdown_pct"] = max(state["max_drawdown_pct"], drawdown)
        if drawdown >= MAX_DRAWDOWN_PAUSE and "max_drawdown_8pct" not in state["risk_pause_reasons"]:
            state["risk_pause_reasons"].append("max_drawdown_8pct")
        state["last_processed_timestamp"] = bar["timestamp"]
        state["last_completed_signal"] = bool(signals[i])
    state["return_pct"] = round((state["equity_usd"] / state["initial_cash_usd"] - 1) * 100, 4)
    state["profit_factor"] = (
        round(sum(x["net_pnl_usd"] for x in state["trade_log"] if x["net_pnl_usd"] > 0) /
              -sum(x["net_pnl_usd"] for x in state["trade_log"] if x["net_pnl_usd"] < 0), 4)
        if any(x["net_pnl_usd"] < 0 for x in state["trade_log"])
        else (None if state["wins"] else 0.0)
    )
    state["live_trading_eligible"] = False
    return state


def write_state_atomically(state, path):
    """Persist a JSON checkpoint without truncating a previous valid ledger."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix="." + target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target
