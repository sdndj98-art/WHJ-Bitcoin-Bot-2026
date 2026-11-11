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
        eligible = row.get("execution_eligible", True)
        if not isinstance(eligible, bool):
            raise ValueError("execution_eligible must be boolean")
        bar = {"timestamp": int(timestamp), "execution_eligible": eligible}
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
    if not isinstance(state, dict):
        raise ValueError("ATR paper state must be a JSON object")
    if state.get("strategy") != "ema20_50_daily_sma200_atr3_trailing":
        raise ValueError("ATR paper state strategy mismatch")

    required = (
        "initial_cash", "cash", "quantity", "equity", "peak_equity",
        "max_drawdown_pct", "ema20", "ema50", "atr14", "previous_close",
        "position_peak", "pending_action", "last_timestamp",
        "forward_seed_timestamp", "daily_bucket", "daily_start_equity",
        "completed_trades", "wins", "losses", "consecutive_losses",
        "fees_paid", "trades", "paused", "pause_reason",
        "processed_new_candles", "last_signal", "last_daily_regime",
        "last_setup",
    )
    if any(key not in state for key in required):
        raise ValueError("ATR paper state is missing required fields")

    try:
        expected_cash = _finite(initial_cash, "initial_cash", 0)
        stored_initial = _finite(state["initial_cash"], "state initial_cash", 0)
        if stored_initial != expected_cash or expected_cash <= 0:
            raise ValueError("ATR paper initial cash mismatch")

        for key in ("cash", "quantity", "equity", "peak_equity",
                    "max_drawdown_pct", "daily_start_equity", "fees_paid"):
            _finite(state[key], f"state {key}", 0)
        for key in ("ema20", "ema50", "atr14", "previous_close"):
            _finite(state[key], f"state {key}", 0.000000001)
        if state["daily_start_equity"] <= 0 or state["peak_equity"] <= 0:
            raise ValueError("invalid positive equity checkpoint")
        if state["max_drawdown_pct"] > 100:
            raise ValueError("invalid maximum drawdown")
        for key in ("last_timestamp", "forward_seed_timestamp"):
            number = _finite(state[key], f"state {key}", 0)
            if not number.is_integer():
                raise ValueError(f"state {key} must be whole seconds")
        for key in ("completed_trades", "wins", "losses",
                    "consecutive_losses", "processed_new_candles"):
            value = state[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"state {key} must be a non-negative integer")
        if state["wins"] + state["losses"] != state["completed_trades"]:
            raise ValueError("inconsistent completed trade counters")
        if state["forward_seed_timestamp"] > state["last_timestamp"]:
            raise ValueError("forward seed timestamp is after last timestamp")
        if not isinstance(state["daily_bucket"], str) or not state["daily_bucket"]:
            raise ValueError("invalid daily bucket")
        datetime.fromisoformat(state["daily_bucket"])
        if state["pending_action"] not in (None, "buy", "sell"):
            raise ValueError("invalid pending action")
        if not isinstance(state["paused"], bool):
            raise ValueError("invalid paused flag")
        if state["pause_reason"] is not None and not isinstance(state["pause_reason"], str):
            raise ValueError("invalid pause reason")
        if not isinstance(state["last_signal"], str):
            raise ValueError("invalid last signal")
        for key in ("last_daily_regime", "last_setup"):
            if state[key] is not None and not isinstance(state[key], bool):
                raise ValueError(f"invalid {key} flag")
        if state["position_peak"] is not None:
            _finite(state["position_peak"], "state position_peak", 0.000000001)
        if not isinstance(state["trades"], list):
            raise ValueError("state trades must be a list")
        for trade in state["trades"]:
            if not isinstance(trade, dict):
                raise ValueError("invalid trade record")
            for key in ("entry_timestamp", "entry_price", "quantity", "entry_fee"):
                if key not in trade:
                    raise ValueError("incomplete trade record")
            for key in ("entry_price", "quantity", "entry_fee"):
                _finite(trade[key], f"trade {key}", 0)
            entry_time = _finite(trade["entry_timestamp"], "trade entry_timestamp", 0)
            if not entry_time.is_integer() or trade["entry_price"] <= 0 or trade["quantity"] <= 0:
                raise ValueError("invalid trade entry")
            exit_fields = ("exit_timestamp", "exit_price", "exit_fee", "pnl_usd")
            if any(key in trade for key in exit_fields) and not all(key in trade for key in exit_fields):
                raise ValueError("incomplete trade exit")
            if all(key in trade for key in exit_fields):
                exit_time = _finite(trade["exit_timestamp"], "trade exit_timestamp", 0)
                _finite(trade["exit_price"], "trade exit_price", 0.000000001)
                _finite(trade["exit_fee"], "trade exit_fee", 0)
                _finite(trade["pnl_usd"], "trade pnl_usd")
                if not exit_time.is_integer() or exit_time < entry_time:
                    raise ValueError("invalid trade exit timestamp")
        open_trades = [trade for trade in state["trades"] if "exit_timestamp" not in trade]
        if len(open_trades) > 1:
            raise ValueError("multiple open trades in single-position account")
        if state["quantity"] > 0:
            if len(open_trades) != 1 or not math.isclose(
                state["quantity"], float(open_trades[0]["quantity"]), rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError("open position does not match trade ledger")
        elif open_trades:
            raise ValueError("open trade exists without account quantity")
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("ATR paper"):
            raise
        raise ValueError("ATR paper state validation failed") from exc
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
    if any(b["timestamp"] - a["timestamp"] != 4 * 3600 for a, b in zip(four_hour, four_hour[1:])):
        raise ValueError("Historical 4h candles must be contiguous")
    if any(b["timestamp"] - a["timestamp"] != 86400 for a, b in zip(daily, daily[1:])):
        raise ValueError("Historical daily candles must be contiguous")
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
        "pending_action_reason": None,
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
        "last_daily_regime": None,
        "last_setup": None,
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
    if new_bars[0]["timestamp"] - state["last_timestamp"] != 4 * 3600:
        raise ValueError("New 4h candles must continue exactly from the saved timestamp")
    for previous, current in zip(new_bars, new_bars[1:]):
        if current["timestamp"] - previous["timestamp"] != 4 * 3600:
            raise ValueError("New 4h candles must be contiguous")
    for bar in new_bars:
        close = bar["close"]
        old_close = state["previous_close"]
        true_range = max(bar["high"] - bar["low"], abs(bar["high"] - old_close), abs(bar["low"] - old_close))
        state["atr14"] = (state["atr14"] * 13.0 + true_range) / 14.0
        state["ema20"] = (2.0 / 21.0) * close + (19.0 / 21.0) * state["ema20"]
        state["ema50"] = (2.0 / 51.0) * close + (49.0 / 51.0) * state["ema50"]
        bucket = datetime.fromtimestamp(bar["timestamp"], timezone.utc).date().isoformat()
        if bucket != state["daily_bucket"]:
            state["daily_bucket"] = bucket
            state["daily_start_equity"] = state["equity"]

        # Synthetic aggregate bars may update indicators/mark-to-market but
        # cannot execute. Cancel any queued action so a stale signal cannot fill
        # later on an unrelated executable candle.
        if not bar["execution_eligible"]:
            # Synthetic bars cannot fill orders, but their mark-to-market value
            # must still trigger risk guards. Otherwise a loss breach that
            # recovers before the next executable bar could go unnoticed.
            state["equity"] = state["cash"] + state["quantity"] * close
            state["peak_equity"] = max(state["peak_equity"], state["equity"])
            drawdown = (
                (state["peak_equity"] - state["equity"]) / state["peak_equity"]
                if state["peak_equity"] > 0 else 0.0
            )
            state["max_drawdown_pct"] = max(
                state["max_drawdown_pct"], drawdown * 100.0
            )
            daily_loss = (
                (state["daily_start_equity"] - state["equity"])
                / state["daily_start_equity"]
                if state["daily_start_equity"] > 0 else 0.0
            )
            if drawdown >= max_drawdown_fraction:
                state["paused"], state["pause_reason"] = True, "maximum_drawdown"
            elif daily_loss >= daily_loss_fraction:
                state["paused"], state["pause_reason"] = True, "daily_loss_limit"
            elif state["consecutive_losses"] >= max_consecutive_losses:
                state["paused"], state["pause_reason"] = True, "consecutive_loss_limit"
            # A queued entry or ordinary regime exit can become stale. Keep only
            # forced risk exits pending; synthetic bars never execute them.
            if state["paused"] and state["quantity"] > 0:
                state["pending_action"] = "sell"
                state["pending_action_reason"] = "risk_pause"
            elif state.get("pending_action") == "buy" or state.get("pending_action_reason") not in (
                "atr_trailing_stop", "risk_pause"
            ):
                state["pending_action"] = None
                state["pending_action_reason"] = None
            state["previous_close"] = close
            state["last_timestamp"] = bar["timestamp"]
            state["processed_new_candles"] += 1
            state["last_signal"] = "blocked_synthetic_bar"
            continue

        # Apply risk guards to the current mark before allowing a queued entry.
        pre_equity = state["cash"] + state["quantity"] * close
        state["peak_equity"] = max(state["peak_equity"], pre_equity)
        pre_drawdown = (
            (state["peak_equity"] - pre_equity) / state["peak_equity"]
            if state["peak_equity"] > 0 else 0.0
        )
        pre_daily_loss = (
            (state["daily_start_equity"] - pre_equity) / state["daily_start_equity"]
            if state["daily_start_equity"] > 0 else 0.0
        )
        if pre_drawdown >= max_drawdown_fraction:
            state["paused"], state["pause_reason"] = True, "maximum_drawdown"
        elif pre_daily_loss >= daily_loss_fraction:
            state["paused"], state["pause_reason"] = True, "daily_loss_limit"
        elif state["consecutive_losses"] >= max_consecutive_losses:
            state["paused"], state["pause_reason"] = True, "consecutive_loss_limit"

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
        state["pending_action_reason"] = None
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
        state["last_daily_regime"] = regime
        state["last_setup"] = setup
        if state["quantity"] > 0:
            state["position_peak"] = max(state["position_peak"] or close, close)
            trailing_stop = state["position_peak"] - 3.0 * state["atr14"]
            if state["paused"] or not regime or close < trailing_stop:
                state["pending_action"] = "sell"
                state["pending_action_reason"] = (
                    "risk_pause" if state["paused"]
                    else "atr_trailing_stop" if close < trailing_stop
                    else "daily_regime_exit"
                )
                state["last_signal"] = "exit_queued"
            else:
                state["last_signal"] = "hold"
        elif setup and not state["paused"]:
            state["pending_action"] = "buy"
            state["pending_action_reason"] = "entry_setup"
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
        "last_daily_regime": state.get("last_daily_regime"),
        "last_setup": state.get("last_setup"),
        "ema20": round(state["ema20"], 6),
        "ema50": round(state["ema50"], 6),
        "atr14": round(state["atr14"], 6),
    }
