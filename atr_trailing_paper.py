"""Forward-only paper adapter for the 4h EMA20/EMA50 + prior-day SMA200 + ATR3 trail.

Signals are evaluated only after a 4h candle closes. A queued action is filled at
the following completed 4h candle close, so the signal candle's close is never
used as its own execution price. This module is isolated from legacy paper ledgers.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _finite(value, name, minimum=None):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name} is outside the allowed range")
    return result


def _bars(rows, name):
    if not isinstance(rows, (list, tuple)):
        raise ValueError(f"{name} bars must be a sequence")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{name} bars must be dictionaries")
        timestamp = _finite(row.get("timestamp"), f"{name} timestamp", 0)
        if not timestamp.is_integer():
            raise ValueError("timestamps must be whole seconds")
        bar = {"timestamp": int(timestamp)}
        for field in ("open", "high", "low", "close"):
            bar[field] = _finite(row.get(field), f"{name} {field}", 0)
            if bar[field] <= 0:
                raise ValueError("OHLC prices must be positive")
        if bar["high"] < max(bar["open"], bar["close"], bar["low"]):
            raise ValueError("bar high is inconsistent with OHLC")
        if bar["low"] > min(bar["open"], bar["close"], bar["high"]):
            raise ValueError("bar low is inconsistent with OHLC")
        result.append(bar)
    stamps = [bar["timestamp"] for bar in result]
    if stamps != sorted(stamps) or len(stamps) != len(set(stamps)):
        raise ValueError(f"{name} timestamps must be strictly increasing and unique")
    return result


def _ema(values, period):
    alpha = 2.0 / (period + 1.0)
    current = float(values[0])
    for value in values[1:]:
        current = alpha * float(value) + (1.0 - alpha) * current
    return current


def _atr(bars, period=14):
    if len(bars) <= period:
        raise ValueError("ATR requires at least period + 1 OHLC bars")
    ranges = []
    for index in range(1, len(bars)):
        high, low = bars[index]["high"], bars[index]["low"]
        previous = bars[index - 1]["close"]
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    current = sum(ranges[:period]) / period
    for value in ranges[period:]:
        current = (current * (period - 1) + value) / period
    return current


def _daily_regime(daily, four_hour_timestamp):
    day = four_hour_timestamp // 86400
    target = day - 1
    # Use only the previous fully completed UTC daily candle.
    index_by_day = {bar["timestamp"] // 86400: i for i, bar in enumerate(daily)}
    index = index_by_day.get(target)
    if index is None or index < 199:
        return False
    average = sum(bar["close"] for bar in daily[index - 199:index + 1]) / 200.0
    return daily[index]["close"] > average


def _load(path, initial_cash):
    target = Path(path)
    if not target.exists():
        return None
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("ATR paper state is unreadable; refusing to reset it") from exc
    if state.get("strategy") != "ema20_50_daily_sma200_atr3_trailing":
        raise ValueError("ATR paper state strategy mismatch")
    if float(state.get("initial_cash", -1)) != float(initial_cash):
        raise ValueError("ATR paper initial cash mismatch")
    return state


def _save(path, state):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def seed_atr_trailing_account(four_hour_bars, daily_bars, state_path, initial_cash=250.0):
    """Warm indicators on history without creating historical positions, trades or PnL."""
    initial_cash = _finite(initial_cash, "initial_cash", 0)
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    four_hour = _bars(four_hour_bars, "4h")
    daily = _bars(daily_bars, "daily")
    if len(four_hour) < 201 or len(daily) < 200:
        raise ValueError("Need at least 201 four-hour and 200 daily bars to seed")
    existing = _load(state_path, initial_cash)
    if existing is not None:
        return {"created": False, "last_timestamp": existing["last_timestamp"]}
    closes = [bar["close"] for bar in four_hour]
    last = four_hour[-1]
    state = {
        "strategy": "ema20_50_daily_sma200_atr3_trailing",
        "initial_cash": initial_cash,
        "cash": initial_cash,
        "quantity": 0.0,
        "equity": initial_cash,
        "peak_equity": initial_cash,
        "max_drawdown_pct": 0.0,
        "ema20": _ema(closes, 20),
        "ema50": _ema(closes, 50),
        "atr14": _atr(four_hour, 14),
        "previous_close": last["close"],
        "position_peak": None,
        "pending_action": None,
        "last_timestamp": last["timestamp"],
        "forward_seed_timestamp": last["timestamp"],
        "daily_bucket": datetime.fromtimestamp(last["timestamp"], timezone.utc).date().isoformat(),
        "daily_start_equity": initial_cash,
        "completed_trades": 0,
        "wins": 0,
        "losses": 0,
        "consecutive_losses": 0,
        "fees_paid": 0.0,
        "trades": [],
        "paused": False,
        "pause_reason": None,
        "processed_new_candles": 0,
        "last_signal": "seeded_no_trade",
    }
    _save(state_path, state)
    return {"created": True, "last_timestamp": last["timestamp"]}


def update_atr_trailing_account(four_hour_bars, daily_bars, state_path,
                                initial_cash=250.0, allocation_fraction=0.10,
                                fee_rate=0.001, slippage_rate=0.0005,
                                max_drawdown_fraction=0.10,
                                daily_loss_fraction=0.03,
                                max_consecutive_losses=5):
    """Process new completed 4h bars exactly once and persist a paper-only ledger."""
    initial_cash = _finite(initial_cash, "initial_cash", 0)
    allocation_fraction = _finite(allocation_fraction, "allocation_fraction", 0.01)
    fee_rate = _finite(fee_rate, "fee_rate", 0)
    slippage_rate = _finite(slippage_rate, "slippage_rate", 0)
    max_drawdown_fraction = _finite(max_drawdown_fraction, "max_drawdown_fraction", 0.001)
    daily_loss_fraction = _finite(daily_loss_fraction, "daily_loss_fraction", 0.001)
    if initial_cash <= 0 or allocation_fraction > 1 or fee_rate >= 1 or slippage_rate >= 1:
        raise ValueError("Invalid paper account configuration")
    if max_drawdown_fraction > 1 or daily_loss_fraction > 1:
        raise ValueError("Risk limits must not exceed 1")
    if isinstance(max_consecutive_losses, bool) or not isinstance(max_consecutive_losses, int) or max_consecutive_losses < 1:
        raise ValueError("max_consecutive_losses must be a positive integer")
    four_hour = _bars(four_hour_bars, "4h")
    daily = _bars(daily_bars, "daily")
    state = _load(state_path, initial_cash)
    if state is None:
        raise ValueError("Seed the ATR paper account before updating it")
    if len(four_hour) < 1 or len(daily) < 200:
        raise ValueError("Insufficient OHLC data for ATR strategy update")
    if four_hour[-1]["timestamp"] <= state["last_timestamp"]:
        return _summary(state)
    new_bars = [bar for bar in four_hour if bar["timestamp"] > state["last_timestamp"]]
    if not new_bars:
        return _summary(state)
    if new_bars[0]["timestamp"] <= state["last_timestamp"]:
        raise ValueError("New candles must follow the saved timestamp")
    for previous, current in zip(new_bars, new_bars[1:]):
        if current["timestamp"] - previous["timestamp"] != 4 * 3600:
            raise ValueError("New 4h candles must be contiguous")
    for bar in new_bars:
        close = bar["close"]
        old_close = state["previous_close"]
        true_range = max(bar["high"] - bar["low"], abs(bar["high"] - old_close), abs(bar["low"] - old_close))
        state["atr14"] = (state["atr14"] * 13.0 + true_range) / 14.0
        state["ema20"] = (2.0 / 21.0) * close + (19.0 / 21.0) * state["ema20"]
        state["ema50"] = (2.0 / 51.0) * close + (50.0 / 51.0) * state["ema50"]
        bucket = datetime.fromtimestamp(bar["timestamp"], timezone.utc).date().isoformat()
        if bucket != state["daily_bucket"]:
            state["daily_bucket"] = bucket
            state["daily_start_equity"] = state["equity"]

        # Execute only the prior bar's signal at this bar's close.
        action = state["pending_action"]
        fill = close * (1.0 + slippage_rate) if action == "buy" else close * (1.0 - slippage_rate)
        if action == "buy" and not state["paused"] and state["quantity"] == 0:
            equity_before = state["cash"]
            budget = min(state["cash"], equity_before * allocation_fraction)
            quantity = budget / (fill * (1.0 + fee_rate))
            cost = quantity * fill
            fee = cost * fee_rate
            state["cash"] -= cost + fee
            state["quantity"] = quantity
            state["fees_paid"] += fee
            state["position_peak"] = fill
            state["trades"].append({"entry_timestamp": bar["timestamp"], "entry_price": fill, "quantity": quantity, "entry_fee": fee})
        elif action == "sell" and state["quantity"] > 0:
            proceeds = state["quantity"] * fill
            fee = proceeds * fee_rate
            state["cash"] += proceeds - fee
            state["fees_paid"] += fee
            trade = state["trades"][-1]
            pnl = (fill - trade["entry_price"]) * state["quantity"] - trade["entry_fee"] - fee
            trade.update({"exit_timestamp": bar["timestamp"], "exit_price": fill, "exit_fee": fee, "pnl_usd": pnl})
            state["completed_trades"] += 1
            if pnl >= 0:
                state["wins"] += 1
                state["consecutive_losses"] = 0
            else:
                state["losses"] += 1
                state["consecutive_losses"] += 1
            state["quantity"] = 0.0
            state["position_peak"] = None

        state["pending_action"] = None
        state["equity"] = state["cash"] + state["quantity"] * close
        state["peak_equity"] = max(state["peak_equity"], state["equity"])
        drawdown = (state["peak_equity"] - state["equity"]) / state["peak_equity"]
        state["max_drawdown_pct"] = max(state["max_drawdown_pct"], drawdown * 100.0)
        daily_loss = (state["daily_start_equity"] - state["equity"]) / state["daily_start_equity"]
        if drawdown >= max_drawdown_fraction:
            state["paused"], state["pause_reason"] = True, "maximum_drawdown"
        elif daily_loss >= daily_loss_fraction:
            state["paused"], state["pause_reason"] = True, "daily_loss_limit"
        elif state["consecutive_losses"] >= max_consecutive_losses:
            state["paused"], state["pause_reason"] = True, "consecutive_loss_limit"

        regime = _daily_regime(daily, bar["timestamp"])
        setup = regime and state["ema20"] > state["ema50"] and close > state["ema50"]
        if state["quantity"] > 0:
            state["position_peak"] = max(state["position_peak"] or close, close)
            trailing_stop = state["position_peak"] - 3.0 * state["atr14"]
            if state["paused"] or not regime or close < trailing_stop:
                state["pending_action"] = "sell"
                state["last_signal"] = "exit_queued"
            else:
                state["last_signal"] = "hold"
        elif setup and not state["paused"]:
            state["pending_action"] = "buy"
            state["last_signal"] = "entry_queued"
        else:
            state["last_signal"] = "paused" if state["paused"] else "flat"
        state["previous_close"] = close
        state["last_timestamp"] = bar["timestamp"]
        state["processed_new_candles"] += 1
    _save(state_path, state)
    return _summary(state)


def _summary(state):
    equity = float(state["cash"]) + float(state["quantity"]) * float(state["previous_close"])
    return {
        "strategy": state["strategy"],
        "mode": "FORWARD_ONLY_PAPER",
        "initial_cash_usd": state["initial_cash"],
        "cash_usd": round(state["cash"], 4),
        "equity_usd": round(equity, 4),
        "return_pct": round((equity / state["initial_cash"] - 1.0) * 100.0, 4),
        "completed_trades": state["completed_trades"],
        "wins": state["wins"],
        "losses": state["losses"],
        "max_drawdown_pct": round(state["max_drawdown_pct"], 4),
        "fees_paid_usd": round(state["fees_paid"], 4),
        "open_position": state["quantity"] > 0,
        "pending_action": state["pending_action"],
        "paused": state["paused"],
        "pause_reason": state["pause_reason"],
        "processed_new_candles": state["processed_new_candles"],
        "last_timestamp": state["last_timestamp"],
        "last_signal": state["last_signal"],
    }
