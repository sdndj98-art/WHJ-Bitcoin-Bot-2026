"""Isolated forward-only ADX paper shadow ledgers; never touches existing accounts."""
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from historical_research import aggregate_candles
from ema_adx_lab import _build_sleeve_signals

TIMEFRAMES = (4, 6)
THRESHOLDS = (15.0, 20.0)
INITIAL_CASH_PER_SLEEVE = 500.0
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005
ALLOCATION_FRACTION = 0.10
MAX_DRAWDOWN = 0.10
DAILY_LOSS = 0.03
MAX_LOSS_STREAK = 5


def _finite(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + " must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(name + " is below its allowed minimum")
    return float(value)


def validate_hourly_candles(candles):
    if not isinstance(candles, list) or len(candles) < 24 * 14:
        raise ValueError("At least 14 days of hourly OHLCV warm-up data are required")
    previous = None
    for row in candles:
        if not isinstance(row, dict):
            raise ValueError("Hourly candle must be an object")
        ts = _finite(row.get("timestamp"), "timestamp", 0)
        if not ts.is_integer() or int(ts) % 3_600_000:
            raise ValueError("Hourly timestamp must align to UTC hour")
        if previous is not None and int(ts) - previous != 3_600_000:
            raise ValueError("Hourly feed contains a gap or duplicate")
        previous = int(ts)
        values = {k: _finite(row.get(k), k, 0 if k == "volume" else 1e-12)
                  for k in ("open", "high", "low", "close", "volume")}
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError("Inconsistent hourly high")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError("Inconsistent hourly low")
    # EMA200 on 6h needs 1,200 hourly observations; reject synthetic data in
    # the indicator warm-up horizon.
    if any(row.get("imputed", False) for row in candles[-1300:]):
        raise ValueError("Imputed candles inside the ADX indicator warm-up horizon are not accepted")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    latest_close_ms = int(candles[-1]["timestamp"]) + 3_600_000
    age_minutes = (now_ms - latest_close_ms) / 60_000
    if not -5 <= age_minutes <= 120:
        raise ValueError("Latest closed hourly candle is stale or in the future")
    return True


def _new_state(threshold, timeframe, first_timestamp):
    return {
        "schema_version": 1,
        "mode": "FORWARD_ONLY_PAPER",
        "strategy": "EMA50_200_ADX14_ENTRY_ONLY",
        "threshold": float(threshold),
        "timeframe_hours": int(timeframe),
        "initial_cash": INITIAL_CASH_PER_SLEEVE,
        "cash": INITIAL_CASH_PER_SLEEVE,
        "btc": 0.0,
        "entry_cost": 0.0,
        "fees_paid": 0.0,
        "last_timestamp": int(first_timestamp),
        "peak_equity": INITIAL_CASH_PER_SLEEVE,
        "max_drawdown_pct": 0.0,
        "daily_date": None,
        "daily_start_equity": INITIAL_CASH_PER_SLEEVE,
        "daily_paused": False,
        "drawdown_paused": False,
        "loss_streak_paused": False,
        "trades": [],
        "seeded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _validate_state(state, threshold, timeframe):
    if not isinstance(state, dict):
        raise ValueError("ADX paper ledger is invalid; refusing to reset it")
    identity = (
        state.get("schema_version"),
        state.get("mode"),
        state.get("strategy"),
        state.get("threshold"),
        state.get("timeframe_hours"),
        state.get("initial_cash"),
    )
    expected = (
        1,
        "FORWARD_ONLY_PAPER",
        "EMA50_200_ADX14_ENTRY_ONLY",
        float(threshold),
        int(timeframe),
        INITIAL_CASH_PER_SLEEVE,
    )
    if identity != expected:
        raise ValueError("ADX paper ledger identity mismatch; manual review required")

    for key in ("cash", "btc", "entry_cost", "fees_paid", "peak_equity",
                "max_drawdown_pct", "daily_start_equity"):
        _finite(state.get(key), "saved " + key, 0)
    if state["peak_equity"] <= 0 or state["daily_start_equity"] <= 0:
        raise ValueError("ADX paper equity reference is invalid")
    if state["max_drawdown_pct"] > 100:
        raise ValueError("ADX paper drawdown is invalid")
    if state["btc"] == 0 and state["entry_cost"] != 0:
        raise ValueError("ADX paper position is inconsistent")
    if state["btc"] > 0 and state["entry_cost"] <= 0:
        raise ValueError("ADX paper position is inconsistent")
    if state["cash"] > INITIAL_CASH_PER_SLEEVE + 1e-8 and state["btc"] == 0:
        raise ValueError("ADX paper cash exceeds its initial capital")
    last = state.get("last_timestamp")
    if isinstance(last, bool) or not isinstance(last, int) or last < 0:
        raise ValueError("ADX paper watermark is invalid")
    if last % (int(timeframe) * 3_600_000):
        raise ValueError("ADX paper watermark is not timeframe-aligned")
    flags = ("daily_paused", "drawdown_paused", "loss_streak_paused")
    if any(not isinstance(state.get(key), bool) for key in flags):
        raise ValueError("ADX paper risk flags are invalid")
    daily_date = state.get("daily_date")
    if daily_date is not None:
        try:
            if datetime.fromisoformat(daily_date).date().isoformat() != daily_date:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("ADX paper daily date is invalid")
    trades = state.get("trades")
    if not isinstance(trades, list):
        raise ValueError("ADX paper trade history is invalid")
    for trade in trades:
        if not isinstance(trade, dict) or trade.get("side") != "SELL":
            raise ValueError("ADX paper trade record is invalid")
        ts = trade.get("timestamp")
        if isinstance(ts, bool) or not isinstance(ts, int) or ts < 0:
            raise ValueError("ADX paper trade timestamp is invalid")
        _finite(trade.get("price"), "saved trade price", 1e-12)
        _finite(trade.get("pnl_usd"), "saved trade PnL")
        if trade.get("result") not in ("WIN", "LOSS"):
            raise ValueError("ADX paper trade result is invalid")
    if state["btc"] == 0 and state["entry_cost"] != 0:
        raise ValueError("ADX paper position is inconsistent")
    if state["btc"] > 0 and state["entry_cost"] <= 0:
        raise ValueError("ADX paper position is inconsistent")


def _load_state(path, threshold, timeframe, first_timestamp):
    target = Path(path)
    if not target.exists():
        return _new_state(threshold, timeframe, first_timestamp), True
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("ADX paper ledger unreadable; refusing to reset it") from exc
    _validate_state(state, threshold, timeframe)
    return state, False


def _save_atomic(path, state):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(target.parent),
                                         prefix="." + target.name + ".", suffix=".tmp",
                                         delete=False) as handle:
            temp_name = handle.name
            json.dump(state, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
        raise


def _equity(state, price):
    marked = state["btc"] * price * (1 - SLIPPAGE_RATE)
    marked -= marked * FEE_RATE
    return state["cash"] + marked


def _close_position(state, timestamp, price):
    fill = price * (1 - SLIPPAGE_RATE)
    gross = state["btc"] * fill
    fee = gross * FEE_RATE
    proceeds = gross - fee
    pnl = proceeds - state["entry_cost"]
    state["cash"] += proceeds
    state["fees_paid"] += fee
    state["trades"].append({
        "timestamp": int(timestamp), "side": "SELL", "price": round(fill, 8),
        "pnl_usd": round(pnl, 6), "result": "WIN" if pnl > 0 else "LOSS",
    })
    state["btc"] = 0.0
    state["entry_cost"] = 0.0


def process_native_bars(bars, threshold, timeframe, state_path):
    if threshold not in THRESHOLDS or timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported ADX paper configuration")
    if not isinstance(bars, list) or len(bars) < 250:
        raise ValueError("At least 250 native timeframe bars are required")
    timestamps = [int(row["timestamp"]) for row in bars]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Native bars must be strictly increasing and unique")
    if any(timestamps[i] - timestamps[i-1] != timeframe * 3_600_000
           for i in range(1, len(timestamps))):
        raise ValueError("Native timeframe bars contain a gap")
    baseline, confirmed = _build_sleeve_signals(bars, float(threshold))
    state, seeded = _load_state(state_path, threshold, timeframe, timestamps[0])
    processed = 0
    if seeded:
        # First run establishes a forward watermark only. Historical warm-up is never traded.
        state["last_timestamp"] = timestamps[-1]
        _save_atomic(state_path, state)
        return summarize(state, bars[-1]["close"], seeded=True, processed=0)

    last = state["last_timestamp"]
    if last < timestamps[0]:
        raise ValueError("ADX ledger is older than the available feed; refusing to skip unseen bars")
    if last not in set(timestamps):
        raise ValueError(
            "ADX ledger watermark is absent from the current feed; "
            "refusing to skip unseen or future bars"
        )
    new_indices = [i for i, ts in enumerate(timestamps) if ts > last]
    for i in new_indices:
        if i == 0:
            continue
        ts = timestamps[i]
        price = _finite(bars[i]["close"], "close", 1e-12)
        previous_signal = bool(confirmed[i - 1])
        current_baseline = bool(baseline[i - 1])
        date_key = datetime.fromtimestamp((ts + timeframe * 3_600_000) / 1000,
                                           timezone.utc).date().isoformat()
        if state["daily_date"] != date_key:
            state["daily_date"] = date_key
            state["daily_start_equity"] = _equity(state, float(bars[i-1]["close"]))
            state["daily_paused"] = False
        equity = _equity(state, price)
        state["peak_equity"] = max(state["peak_equity"], equity)
        dd = ((state["peak_equity"] - equity) / state["peak_equity"]
              if state["peak_equity"] else 0.0)
        state["max_drawdown_pct"] = max(state["max_drawdown_pct"], dd * 100)
        if dd >= MAX_DRAWDOWN:
            state["drawdown_paused"] = True
        if equity <= state["daily_start_equity"] * (1 - DAILY_LOSS):
            state["daily_paused"] = True
        streak = 0
        for trade in reversed(state["trades"]):
            if trade["pnl_usd"] < 0:
                streak += 1
            else:
                break
        if streak >= MAX_LOSS_STREAK:
            state["loss_streak_paused"] = True
        paused = state["daily_paused"] or state["drawdown_paused"] or state["loss_streak_paused"]
        # Exit when the baseline regime turns off; entry confirmation is ADX/+DI only.
        if state["btc"] > 0 and (not current_baseline or paused):
            _close_position(state, ts, price)
        elif state["btc"] == 0 and previous_signal and not paused:
            allocation = min(state["cash"], state["cash"] * ALLOCATION_FRACTION)
            if allocation > 0:
                fee = allocation * FEE_RATE
                fill = price * (1 + SLIPPAGE_RATE)
                units = (allocation - fee) / fill
                state["cash"] -= allocation
                state["btc"] = units
                state["entry_cost"] = allocation
                state["fees_paid"] += fee
        state["last_timestamp"] = ts
        processed += 1
    _save_atomic(state_path, state)
    return summarize(state, bars[-1]["close"], seeded=False, processed=processed)


def summarize(state, last_price, seeded, processed):
    equity = _equity(state, float(last_price))
    wins = sum(t["pnl_usd"] > 0 for t in state["trades"])
    gross_profit = sum(t["pnl_usd"] for t in state["trades"] if t["pnl_usd"] > 0)
    gross_loss = -sum(t["pnl_usd"] for t in state["trades"] if t["pnl_usd"] < 0)
    return {
        "mode": "FORWARD_ONLY_PAPER_NO_LIVE_ORDERS",
        "strategy": state["strategy"],
        "threshold": state["threshold"],
        "timeframe_hours": state["timeframe_hours"],
        "seeded_without_historical_trades": bool(seeded),
        "processed_new_bars": int(processed),
        "last_processed_timestamp": state["last_timestamp"],
        "initial_cash_usd": state["initial_cash"],
        "equity_usd": round(equity, 6),
        "return_pct": round((equity / state["initial_cash"] - 1) * 100, 6),
        "closed_trades": len(state["trades"]),
        "win_rate_pct": round(wins / len(state["trades"]) * 100, 4) if state["trades"] else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if gross_profit else 0.0),
        "max_drawdown_pct": round(state["max_drawdown_pct"], 4),
        "fees_paid_usd": round(state["fees_paid"], 6),
        "open_position": state["btc"] > 0,
        "risk_paused": state["daily_paused"] or state["drawdown_paused"] or state["loss_streak_paused"],
        "risk_pause_reasons": [name for name, flag in (
            ("DAILY_LOSS", state["daily_paused"]), ("MAX_DRAWDOWN", state["drawdown_paused"]),
            ("LOSS_STREAK", state["loss_streak_paused"])) if flag],
        "minimum_trades_for_review": 30,
        "assessment": "INSUFFICIENT_FORWARD_SAMPLE" if len(state["trades"]) < 30 else "REVIEW_REQUIRED",
    }


def run_forward_adx_paper(hourly_candles, state_dir="paper_adx_forward"):
    validate_hourly_candles(hourly_candles)
    output = {}
    directory = Path(state_dir)
    for timeframe in TIMEFRAMES:
        bars = aggregate_candles(hourly_candles, timeframe)
        for threshold in THRESHOLDS:
            key = f"adx{int(threshold)}_{timeframe}h"
            path = directory / f"{key}.json"
            output[key] = process_native_bars(bars, threshold, timeframe, path)
    return {
        "schema_version": 1,
        "mode": "ISOLATED_ADX_FORWARD_PAPER_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "live_orders_enabled": False,
        "existing_paper_ledgers_touched": False,
        "allocation": "Separate 500 USD virtual sleeve per timeframe/threshold; not combined with existing accounts",
        "data_quality": "VALIDATED_NO_GAPS_NO_IMPUTED_CANDLES",
        "results": output,
    }


if __name__ == "__main__":
    from historical_research import load_two_year_candles
    report = run_forward_adx_paper(load_two_year_candles(days=90))
    Path("paper_adx_forward_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, allow_nan=False))
