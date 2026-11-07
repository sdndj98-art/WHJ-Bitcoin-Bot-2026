"""Persistent historical paper account. Never connects to an exchange or places orders."""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

STATE_VERSION = 1


def _number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} is below its allowed minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} is above its allowed maximum")
    return float(value)


def _new_state(initial_cash):
    return {
        "version": STATE_VERSION,
        "initial_cash": float(initial_cash),
        "cash": float(initial_cash),
        "btc": 0.0,
        "entry_cost": 0.0,
        "last_timestamp": None,
        "recent_closes": [],
        "peak_equity": float(initial_cash),
        "max_drawdown_pct": 0.0,
        "daily_bucket": None,
        "daily_loss_paused": False,
        "daily_start_equity": float(initial_cash),
        "paused_for_drawdown": False,
        "trades": [],
        "fees_paid": 0.0,
    }


def _load_state(path, initial_cash):
    file_path = Path(path)
    if not file_path.exists():
        return _new_state(initial_cash)
    try:
        state = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Paper account state is unreadable; refusing to reset funds silently") from exc
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise ValueError("Unknown paper account state version; manual review is required")
    required = ("cash", "btc", "entry_cost", "recent_closes", "peak_equity", "trades", "fees_paid")
    if any(key not in state for key in required):
        raise ValueError("Paper account state is incomplete; refusing to reset it")
    _number(state["cash"], "state cash", 0)
    _number(state["btc"], "state BTC", 0)
    _number(state["entry_cost"], "state entry cost", 0)
    _number(state["peak_equity"], "state peak equity", 0)
    _number(state["fees_paid"], "state fees", 0)
    if not isinstance(state["recent_closes"], list) or not isinstance(state["trades"], list):
        raise ValueError("Paper account state collections are invalid")
    return state


def update_paper_account(candles, state_path="paper_account_state.json",
                         initial_cash=1000.0, fee_rate=0.001,
                         slippage_rate=0.0005, allocation_fraction=0.25,
                         max_drawdown_fraction=0.10, daily_loss_fraction=0.03):
    """Process each newly closed hourly candle once and persist the simulated account."""
    initial_cash = _number(initial_cash, "initial_cash", 0)
    fee_rate = _number(fee_rate, "fee_rate", 0, 0.999999)
    slippage_rate = _number(slippage_rate, "slippage_rate", 0, 0.999999)
    allocation_fraction = _number(allocation_fraction, "allocation_fraction", 0.01, 1)
    max_drawdown_fraction = _number(max_drawdown_fraction, "max_drawdown_fraction", 0.001, 1)
    daily_loss_fraction = _number(daily_loss_fraction, "daily_loss_fraction", 0.001, 1)

    normalized = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            raise ValueError("Each candle must include timestamp and close")
        if isinstance(row[0], bool) or isinstance(row[4], bool):
            raise ValueError("Candle timestamp and close cannot be boolean values")
        try:
            timestamp = _number(float(row[0]), "candle timestamp", 0)
            close = _number(float(row[4]), "candle close", 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Candle timestamp and close must be numeric") from exc
        normalized.append((int(timestamp), close))
    if not normalized:
        raise ValueError("No closed candles were supplied")
    timestamps = [row[0] for row in normalized]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Candle timestamps must be strictly increasing and unique")

    state = _load_state(state_path, initial_cash)
    new_trades = []
    processed = 0
    for timestamp, close in normalized:
        last = state.get("last_timestamp")
        if last is not None and timestamp <= int(last):
            continue

        history = [float(x) for x in state["recent_closes"]]
        if len(history) >= 50:
            sma20 = sum(history[-20:]) / 20
            sma50 = sum(history[-50:]) / 50
            prior_close = history[-1]
            want_long = prior_close > sma20 > sma50
            want_flat = prior_close < sma20 < sma50

            if state.get("daily_bucket") != datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat():
                state["daily_bucket"] = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
                state["daily_start_equity"] = state["cash"] + state["btc"] * close
                state["daily_loss_paused"] = False

            marked_equity = state["cash"] + state["btc"] * close
            daily_start = max(float(state.get("daily_start_equity", initial_cash)), 1e-12)
            daily_loss_hit = marked_equity <= daily_start * (1 - daily_loss_fraction)
            peak = max(float(state.get("peak_equity", initial_cash)), marked_equity)
            drawdown_pct = (peak - marked_equity) / peak * 100 if peak > 0 else 0.0
            state["max_drawdown_pct"] = max(float(state.get("max_drawdown_pct", 0.0)), drawdown_pct)
            drawdown_hit = drawdown_pct >= max_drawdown_fraction * 100
            state["peak_equity"] = peak
            if drawdown_hit:
                state["paused_for_drawdown"] = True
            if daily_loss_hit:
                state["daily_loss_paused"] = True
            paused = state.get("paused_for_drawdown", False) or state.get("daily_loss_paused", False)

            if want_long and state["btc"] == 0 and not paused:
                equity = state["cash"]
                allocation = min(state["cash"], equity * allocation_fraction)
                if allocation > 0:
                    fee = allocation * fee_rate
                    fill = close * (1 + slippage_rate)
                    units = (allocation - fee) / fill
                    state["cash"] -= allocation
                    state["btc"] = units
                    state["entry_cost"] = allocation
                    state["fees_paid"] += fee
            elif (want_flat or daily_loss_hit or state.get("paused_for_drawdown", False)) and state["btc"] > 0:
                fill = close * (1 - slippage_rate)
                gross = state["btc"] * fill
                fee = gross * fee_rate
                proceeds = gross - fee
                pnl = proceeds - state["entry_cost"]
                trade = {
                    "timestamp": timestamp,
                    "side": "SELL",
                    "price": round(fill, 2),
                    "pnl_usd": round(pnl, 4),
                    "result": "WIN" if pnl > 0 else "LOSS",
                }
                state["cash"] += proceeds
                state["fees_paid"] += fee
                state["btc"] = 0.0
                state["entry_cost"] = 0.0
                state["trades"].append(trade)
                new_trades.append(trade)

        state["recent_closes"] = (history + [close])[-50:]
        state["last_timestamp"] = timestamp
        processed += 1

    last_price = normalized[-1][1]
    if state["btc"] > 0:
        liquidation = state["btc"] * last_price * (1 - slippage_rate)
        liquidation -= liquidation * fee_rate
        equity = state["cash"] + liquidation
    else:
        equity = state["cash"]

    if processed:
        target = Path(state_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(state, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, target)

    initial = float(state.get("initial_cash", initial_cash))
    completed = state["trades"]
    winning = [float(t.get("pnl_usd", 0)) for t in completed if float(t.get("pnl_usd", 0)) > 0]
    losing = [-float(t.get("pnl_usd", 0)) for t in completed if float(t.get("pnl_usd", 0)) < 0]
    gross_profit = sum(winning)
    gross_loss = sum(losing)
    loss_streak = 0
    max_loss_streak = 0
    for trade in completed:
        if float(trade.get("pnl_usd", 0)) < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0
    return {
        "mode": "PERSISTENT_PAPER_ONLY",
        "processed_new_candles": processed,
        "last_processed_timestamp": state.get("last_timestamp"),
        "initial_cash_usd": round(initial, 2),
        "cash_usd": round(state["cash"], 2),
        "btc_units": round(state["btc"], 8),
        "equity_after_estimated_exit_costs_usd": round(equity, 2),
        "return_pct": round((equity / initial - 1) * 100, 2),
        "open_position": state["btc"] > 0,
        "completed_trades": len(completed),
        "win_rate_pct": round(len(winning) / len(completed) * 100, 2) if completed else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if gross_profit else 0.0),
        "gross_profit_usd": round(gross_profit, 4),
        "gross_loss_usd": round(gross_loss, 4),
        "max_drawdown_pct": round(float(state.get("max_drawdown_pct", 0.0)), 2),
        "max_consecutive_losses": max_loss_streak,
        "recent_trades": completed[-20:],
        "new_trades": new_trades,
        "fees_paid_usd": round(state["fees_paid"], 4),
        "paused_for_drawdown": bool(state.get("paused_for_drawdown", False)),
        "daily_loss_paused": bool(state.get("daily_loss_paused", False)),
        "risk_limits": {
            "max_drawdown_pct": round(max_drawdown_fraction * 100, 2),
            "daily_loss_pause_pct": round(daily_loss_fraction * 100, 2),
            "allocation_pct": round(allocation_fraction * 100, 2),
        },
        "state_persisted": Path(state_path).exists(),
        "warning": "Paper simulation only. Daily loss pauses new entries; max drawdown pause is persistent and requires manual review/reset.",
    }
