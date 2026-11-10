"""Persistent historical paper account. Never connects to an exchange or places orders."""
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from strategy_health import evaluate_strategy_health

STATE_VERSION = 1


def _number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} is below its allowed minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} is above its allowed maximum")
    return float(value)


def _save_state_atomically(path, state):
    """Persist a paper ledger with a unique same-directory temp file and atomic replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(state, temporary, indent=2, allow_nan=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _new_state(initial_cash, strategy="sma_trend"):
    return {
        "version": STATE_VERSION,
        "strategy": strategy,
        "initial_cash": float(initial_cash),
        "cash": float(initial_cash),
        "btc": 0.0,
        "entry_cost": 0.0,
        "last_timestamp": None,
        "recent_closes": [],
        "ema50_state": None,
        "ema200_state": None,
        "holding_bars": 0,
        "peak_equity": float(initial_cash),
        "max_drawdown_pct": 0.0,
        "daily_bucket": None,
        "daily_loss_paused": False,
        "paused_for_loss_streak": False,
        "daily_start_equity": float(initial_cash),
        "paused_for_drawdown": False,
        "paused_for_strategy_health": False,
        "trades": [],
        "fees_paid": 0.0,
    }


def _load_state(path, initial_cash, strategy="sma_trend"):
    file_path = Path(path)
    if not file_path.exists():
        return _new_state(initial_cash, strategy)
    try:
        state = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Paper account state is unreadable; refusing to reset funds silently") from exc
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise ValueError("Unknown paper account state version; manual review is required")
    if state.get("strategy", "sma_trend") != strategy:
        raise ValueError("Paper account strategy does not match its saved state")
    required = (
        "initial_cash", "cash", "btc", "entry_cost", "recent_closes",
        "peak_equity", "trades", "fees_paid",
    )
    if any(key not in state for key in required):
        raise ValueError("Paper account state is incomplete; refusing to reset it")
    _number(state["initial_cash"], "state initial cash", 0)
    if state["initial_cash"] <= 0:
        raise ValueError("Saved paper account initial cash must be positive")
    if not math.isclose(
        float(state["initial_cash"]), float(initial_cash),
        rel_tol=1e-9, abs_tol=1e-8,
    ):
        raise ValueError(
            "Saved paper account initial capital does not match the configured amount; "
            "manual review is required"
        )
    _number(state["cash"], "state cash", 0)
    _number(state["btc"], "state BTC", 0)
    _number(state["entry_cost"], "state entry cost", 0)
    _number(state["peak_equity"], "state peak equity", 0)
    _number(state["fees_paid"], "state fees", 0)
    _number(state.get("max_drawdown_pct", 0.0), "state max drawdown", 0, 100)
    daily_start_equity = _number(
        state.get("daily_start_equity", state["initial_cash"]),
        "state daily starting equity",
        0,
    )
    if daily_start_equity <= 0:
        raise ValueError("Saved paper account daily starting equity must be positive")
    if (state["btc"] == 0 and state["entry_cost"] != 0) or (
        state["btc"] > 0 and state["entry_cost"] <= 0
    ):
        raise ValueError("Saved paper account position units and entry cost are inconsistent")
    if isinstance(state.get("holding_bars", 0), bool) or not isinstance(state.get("holding_bars", 0), int) or state.get("holding_bars", 0) < 0:
        raise ValueError("Saved strategy holding counter is invalid")
    if (
        not isinstance(state["recent_closes"], list)
        or len(state["recent_closes"]) > 20000
        or not isinstance(state["trades"], list)
        or len(state["trades"]) > 100000
    ):
        raise ValueError("Paper account state collections are invalid")
    for close in state["recent_closes"]:
        _number(close, "saved close", 0)
        if close <= 0:
            raise ValueError("Saved close must be positive")
    for trade in state["trades"]:
        if not isinstance(trade, dict) or "pnl_usd" not in trade:
            raise ValueError("Saved trade record is invalid")
        pnl = _number(trade["pnl_usd"], "saved trade PnL")
        if trade.get("side", "SELL") != "SELL":
            raise ValueError("Saved paper trade side is invalid")
        expected_result = "WIN" if pnl > 0 else "LOSS"
        if trade.get("result", expected_result) != expected_result:
            raise ValueError("Saved paper trade result does not match its PnL")
        if "price" in trade:
            _number(trade["price"], "saved trade price", 0)
            if trade["price"] <= 0:
                raise ValueError("Saved trade price must be positive")
        if "timestamp" in trade and (
            isinstance(trade["timestamp"], bool)
            or not isinstance(trade["timestamp"], int)
            or trade["timestamp"] < 0
        ):
            raise ValueError("Saved trade timestamp is invalid")
    for key in ("ema50_state", "ema200_state"):
        if state.get(key) is not None:
            if _number(state[key], key, 0) <= 0:
                raise ValueError("Saved EMA state must be positive when initialized")
    for key in ("daily_loss_paused", "paused_for_loss_streak", "paused_for_drawdown", "paused_for_strategy_health"):
        if key in state and not isinstance(state[key], bool):
            raise ValueError("Saved paper account risk flag is invalid: " + key)
    if state.get("daily_bucket") is not None and not isinstance(state["daily_bucket"], str):
        raise ValueError("Saved paper account daily bucket is invalid")
    last_timestamp = state.get("last_timestamp")
    if last_timestamp is not None and (isinstance(last_timestamp, bool) or not isinstance(last_timestamp, int) or last_timestamp < 0):
        raise ValueError("Saved paper account timestamp is invalid")
    trade_timestamps = [
        trade["timestamp"] for trade in state["trades"] if "timestamp" in trade
    ]
    if trade_timestamps and len(trade_timestamps) != len(state["trades"]):
        raise ValueError("Saved trade ledger mixes timestamped and legacy records")
    if trade_timestamps:
        if trade_timestamps != sorted(trade_timestamps) or len(set(trade_timestamps)) != len(trade_timestamps):
            raise ValueError("Saved trade timestamps must be strictly increasing and unique")
        if last_timestamp is None or trade_timestamps[-1] > last_timestamp:
            raise ValueError("Saved trade timestamp cannot exceed the last processed candle")
    return state



def _ema_last(values, period):
    alpha = 2.0 / (period + 1)
    current = float(values[0])
    for value in values[1:]:
        current = alpha * float(value) + (1 - alpha) * current
    return current


def seed_forward_paper_account(
    candles, state_path, initial_cash=500.0, strategy="ema50_200_regime"
):
    """Warm a paper strategy on history, then start trading only on future bars.

    Historical candles initialize indicator history but never create trades,
    PnL, or risk pauses. Existing state is validated and never reset.
    """
    supported = (
        "sma_trend", "ema_trend", "rsi_momentum", "sma200_regime",
        "ema50_200_regime", "bollinger_mean_reversion", "rsi14_mean_reversion",
    )
    if strategy not in supported:
        raise ValueError("Unsupported forward paper strategy")
    initial_cash = _number(initial_cash, "initial_cash", 0)
    if initial_cash <= 0:
        raise ValueError("initial_cash must be greater than zero")
    normalized = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            raise ValueError("Each candle must include timestamp and close")
        if isinstance(row[0], bool) or isinstance(row[4], bool):
            raise ValueError("Candle timestamp and close cannot be boolean values")
        timestamp_value = _number(float(row[0]), "candle timestamp", 0)
        close = _number(float(row[4]), "candle close", 0)
        if not timestamp_value.is_integer() or close <= 0:
            raise ValueError("Candle timestamps must be whole seconds and closes positive")
        normalized.append((int(timestamp_value), close))
    if len(normalized) < 200:
        raise ValueError("At least 200 completed candles are required to warm forward strategies")
    timestamps = [row[0] for row in normalized]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Candle timestamps must be strictly increasing and unique")

    target = Path(state_path)
    if target.exists():
        existing = _load_state(target, initial_cash, strategy)
        return {
            "created": False,
            "last_seeded_timestamp": existing.get("forward_seed_timestamp"),
            "last_processed_timestamp": existing.get("last_timestamp"),
        }

    closes = [row[1] for row in normalized]
    state = _new_state(initial_cash, strategy)
    state["recent_closes"] = closes[-200:]
    if strategy == "ema50_200_regime":
        state["ema50_state"] = _ema_last(closes, 50)
        state["ema200_state"] = _ema_last(closes, 200)
    state["last_timestamp"] = timestamps[-1]
    state["forward_seed_timestamp"] = timestamps[-1]
    state["daily_bucket"] = datetime.fromtimestamp(
        timestamps[-1], timezone.utc
    ).date().isoformat()
    _save_state_atomically(target, state)
    return {
        "created": True,
        "last_seeded_timestamp": timestamps[-1],
        "last_processed_timestamp": timestamps[-1],
    }


def _rsi_last(values, period=14):
    changes = [float(values[i]) - float(values[i - 1]) for i in range(1, len(values))]
    recent = changes[-period:]
    gains = sum(max(change, 0.0) for change in recent) / period
    losses = sum(max(-change, 0.0) for change in recent) / period
    if losses == 0:
        return 100.0 if gains else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def run_paper_portfolio(candles, state_dir="."):
    """Run independent, persistent paper ledgers for five fixed strategies."""
    directory = Path(state_dir)
    strategies = ("sma_trend", "ema_trend", "rsi_momentum", "sma200_regime", "ema50_200_regime")
    accounts = {}
    for strategy in strategies:
        accounts[strategy] = update_paper_account(
            candles,
            state_path=str(directory / f"paper_account_state_{strategy}.json"),
            strategy=strategy,
            strategy_health_pause=True,
            strategy_health_drawdown_fraction=0.08,
        )
    return {
        "mode": "MULTI_STRATEGY_PERSISTENT_PAPER_ONLY",
        "accounts": accounts,
        "note": "Each strategy has an independent $1,000 simulated ledger, identical fees, slippage, sizing and risk limits. This is forward paper testing, not live trading.",
    }

def _rolling_health_triggered(trades, initial_cash, drawdown_fraction):
    """Return whether the latest closed-trade window requires a paper pause."""
    rolling_trades = trades[-20:]
    if len(rolling_trades) < 10:
        return False
    rolling_pnl = [float(trade["pnl_usd"]) for trade in rolling_trades]
    rolling_profit = sum(value for value in rolling_pnl if value > 0)
    rolling_loss = -sum(value for value in rolling_pnl if value < 0)
    rolling_peak = 0.0
    rolling_cumulative = 0.0
    rolling_drawdown = 0.0
    for trade_pnl in rolling_pnl:
        rolling_cumulative += trade_pnl
        rolling_peak = max(rolling_peak, rolling_cumulative)
        rolling_drawdown = max(rolling_drawdown, rolling_peak - rolling_cumulative)
    rolling_drawdown_pct = rolling_drawdown / float(initial_cash) * 100.0
    return (
        sum(rolling_pnl) <= 0
        or (rolling_loss > 0 and rolling_profit / rolling_loss < 1.0)
        or rolling_drawdown_pct >= drawdown_fraction * 100.0
    )


def update_paper_account(candles, state_path="paper_account_state.json",
                         initial_cash=1000.0, fee_rate=0.001,
                         slippage_rate=0.0005, allocation_fraction=0.25,
                         max_drawdown_fraction=0.10, daily_loss_fraction=0.03,
                         max_consecutive_losses=5, strategy="sma_trend", strategy_health_pause=False,
                         strategy_health_drawdown_fraction=0.08,
                         require_entry_confirmation=False,
                         entry_confirmation_timestamp=None,
                         entry_confirmation_available=False):
    """Process each newly closed hourly candle once and persist the simulated account."""
    initial_cash = _number(initial_cash, "initial_cash", 0)
    if initial_cash <= 0:
        raise ValueError("initial_cash must be greater than zero")
    fee_rate = _number(fee_rate, "fee_rate", 0, 0.999999)
    slippage_rate = _number(slippage_rate, "slippage_rate", 0, 0.999999)
    allocation_fraction = _number(allocation_fraction, "allocation_fraction", 0.01, 1)
    max_drawdown_fraction = _number(max_drawdown_fraction, "max_drawdown_fraction", 0.001, 1)
    daily_loss_fraction = _number(daily_loss_fraction, "daily_loss_fraction", 0.001, 1)
    if isinstance(max_consecutive_losses, bool) or not isinstance(max_consecutive_losses, int) or max_consecutive_losses < 1:
        raise ValueError("max_consecutive_losses must be a positive integer")
    if not isinstance(strategy_health_pause, bool):
        raise ValueError("strategy_health_pause must be boolean")
    if not isinstance(require_entry_confirmation, bool):
        raise ValueError("require_entry_confirmation must be boolean")
    if not isinstance(entry_confirmation_available, bool):
        raise ValueError("entry_confirmation_available must be boolean")
    if entry_confirmation_timestamp is not None and (
        isinstance(entry_confirmation_timestamp, bool)
        or not isinstance(entry_confirmation_timestamp, int)
        or entry_confirmation_timestamp < 0
    ):
        raise ValueError("entry_confirmation_timestamp must be a non-negative integer")
    strategy_health_drawdown_fraction = _number(
        strategy_health_drawdown_fraction, "strategy_health_drawdown_fraction", 0.001, 1
    )
    if strategy not in ("sma_trend", "ema_trend", "rsi_momentum", "sma200_regime", "ema50_200_regime", "bollinger_mean_reversion", "rsi14_mean_reversion"):
        raise ValueError("Unknown paper strategy")

    normalized = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            raise ValueError("Each candle must include timestamp and close")
        if isinstance(row[0], bool) or isinstance(row[4], bool):
            raise ValueError("Candle timestamp and close cannot be boolean values")
        try:
            timestamp_value = _number(float(row[0]), "candle timestamp", 0)
            if not timestamp_value.is_integer():
                raise ValueError("Candle timestamps must be whole seconds")
            timestamp = int(timestamp_value)
            close = _number(float(row[4]), "candle close", 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Candle timestamp and close must be numeric") from exc
        normalized.append((timestamp, close))
    if not normalized:
        raise ValueError("No closed candles were supplied")
    timestamps = [row[0] for row in normalized]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Candle timestamps must be strictly increasing and unique")

    state = _load_state(state_path, initial_cash, strategy)
    new_trades = []
    processed = 0
    state_changed = False
    # Reconcile saved ledgers immediately, even when the feed has no newer candle.
    saved_loss_streak = 0
    for prior_trade in reversed(state["trades"]):
        if float(prior_trade.get("pnl_usd", 0)) < 0:
            saved_loss_streak += 1
        else:
            break
    if saved_loss_streak >= max_consecutive_losses and not state.get("paused_for_loss_streak", False):
        state["paused_for_loss_streak"] = True
        state_changed = True
    # Reconcile rolling strategy health even when the feed has no newer candle.
    if (
        strategy_health_pause
        and not state.get("paused_for_strategy_health", False)
        and _rolling_health_triggered(
            state["trades"], state["initial_cash"], strategy_health_drawdown_fraction
        )
    ):
        state["paused_for_strategy_health"] = True
        state_changed = True
    for timestamp, close in normalized:
        last = state.get("last_timestamp")
        if last is not None and timestamp <= int(last):
            continue

        history = [float(x) for x in state["recent_closes"]]
        required_history = 200 if strategy in ("sma200_regime", "ema50_200_regime", "bollinger_mean_reversion", "rsi14_mean_reversion") else 50
        if len(history) >= required_history:
            prior_close = history[-1]
            if strategy == "rsi14_mean_reversion":
                momentum = _rsi_last(history, 14)
                regime_sma = sum(history[-200:]) / 200
                if state["btc"] <= 0:
                    want_long = momentum < 30 and prior_close > regime_sma
                    want_flat = False
                else:
                    want_flat = (
                        momentum > 55
                        or prior_close < regime_sma
                        or int(state.get("holding_bars", 0)) >= 10
                    )
                    want_long = not want_flat
            elif strategy == "bollinger_mean_reversion":
                window = history[-20:]
                mean = sum(window) / 20
                variance = sum((value - mean) ** 2 for value in window) / 20
                lower_band = mean - 2 * math.sqrt(variance)
                regime_sma = sum(history[-200:]) / 200
                if state["btc"] <= 0:
                    want_long = prior_close < lower_band and prior_close > regime_sma
                    want_flat = False
                else:
                    want_flat = (
                        prior_close >= mean
                        or prior_close < regime_sma
                        or int(state.get("holding_bars", 0)) >= 10
                    )
                    want_long = not want_flat
            elif strategy == "ema50_200_regime":
                fast = state.get("ema50_state")
                slow = state.get("ema200_state")
                if fast is None:
                    fast = _ema_last(history, 50)
                if slow is None:
                    slow = _ema_last(history, 200)
                state["ema50_state"] = fast
                state["ema200_state"] = slow
                want_long = fast > slow and prior_close > slow
                want_flat = not want_long
            elif strategy == "sma200_regime":
                sma20 = sum(history[-20:]) / 20
                sma50 = sum(history[-50:]) / 50
                sma200 = sum(history[-200:]) / 200
                want_long = prior_close > sma20 > sma50 and prior_close > sma200
                want_flat = not want_long
            elif strategy == "sma_trend":
                sma20 = sum(history[-20:]) / 20
                sma50 = sum(history[-50:]) / 50
                want_long = prior_close > sma20 > sma50
                want_flat = not want_long
            elif strategy == "ema_trend":
                fast = _ema_last(history, 12)
                slow = _ema_last(history, 26)
                want_long = fast > slow and prior_close > slow
                want_flat = not want_long
            else:
                momentum = _rsi_last(history, 14)
                slow = _ema_last(history, 26)
                want_long = 50 < momentum < 70 and prior_close > slow
                want_flat = not want_long

            if state.get("daily_bucket") != datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat():
                state["daily_bucket"] = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
                prior_mark_price = history[-1] if history else close
                daily_mark = state["btc"] * prior_mark_price * (1 - slippage_rate)
                daily_mark -= daily_mark * fee_rate
                state["daily_start_equity"] = state["cash"] + daily_mark
                state["daily_loss_paused"] = False

            marked_position = state["btc"] * close * (1 - slippage_rate)
            marked_position -= marked_position * fee_rate
            marked_equity = state["cash"] + marked_position
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
            loss_streak = 0
            for prior_trade in reversed(state["trades"]):
                if float(prior_trade.get("pnl_usd", 0)) < 0:
                    loss_streak += 1
                else:
                    break
            if loss_streak >= max_consecutive_losses:
                state["paused_for_loss_streak"] = True
            if (
                strategy_health_pause
                and not state.get("paused_for_strategy_health", False)
                and _rolling_health_triggered(
                    state["trades"], state["initial_cash"], strategy_health_drawdown_fraction
                )
            ):
                state["paused_for_strategy_health"] = True
            paused = (
                state.get("paused_for_drawdown", False)
                or state.get("daily_loss_paused", False)
                or state.get("paused_for_loss_streak", False)
                or state.get("paused_for_strategy_health", False)
            )

            confirmation_matches = (
                entry_confirmation_available is True
                and entry_confirmation_timestamp == timestamp
            )
            entry_permitted = (
                not require_entry_confirmation or confirmation_matches
            )
            if want_long and state["btc"] == 0 and not paused and entry_permitted:
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
                    if strategy in ("bollinger_mean_reversion", "rsi14_mean_reversion"):
                        state["holding_bars"] = 0
            elif (want_flat or daily_loss_hit or state.get("paused_for_drawdown", False) or state.get("paused_for_loss_streak", False) or state.get("paused_for_strategy_health", False) or state.get("daily_loss_paused", False)) and state["btc"] > 0:
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
                state["holding_bars"] = 0
                state["trades"].append(trade)
                new_trades.append(trade)

        history_limit = 20000 if strategy == "ema50_200_regime" else 200
        state["recent_closes"] = (history + [close])[-history_limit:]
        if strategy in ("bollinger_mean_reversion", "rsi14_mean_reversion") and state["btc"] > 0:
            state["holding_bars"] = int(state.get("holding_bars", 0)) + 1
        if strategy == "ema50_200_regime":
            alpha50 = 2.0 / 51.0
            alpha200 = 2.0 / 201.0
            prior_ema50 = state.get("ema50_state")
            prior_ema200 = state.get("ema200_state")
            state["ema50_state"] = close if prior_ema50 is None else alpha50 * close + (1 - alpha50) * prior_ema50
            state["ema200_state"] = close if prior_ema200 is None else alpha200 * close + (1 - alpha200) * prior_ema200
        state["last_timestamp"] = timestamp
        processed += 1

    last_price = normalized[-1][1]
    if state["btc"] > 0:
        liquidation = state["btc"] * last_price * (1 - slippage_rate)
        liquidation -= liquidation * fee_rate
        equity = state["cash"] + liquidation
    else:
        equity = state["cash"]

    if processed or state_changed:
        _save_state_atomically(state_path, state)

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
    account_drawdown_pct = float(state.get("max_drawdown_pct", 0.0))
    observed_peak_equity = float(state.get("peak_equity", initial))
    health_equity_curve = None
    if observed_peak_equity > 0 and 0.0 <= account_drawdown_pct < 100.0:
        # Preserve the account's measured peak-to-trough drawdown exactly.
        health_equity_curve = [
            observed_peak_equity,
            observed_peak_equity * (1.0 - account_drawdown_pct / 100.0),
        ]
    strategy_health = evaluate_strategy_health(
        [{"pnl": float(trade.get("pnl_usd", 0.0))} for trade in completed],
        equity_curve=health_equity_curve,
        min_trades=20,
        recent_window=20,
    )
    return {
        "mode": "PERSISTENT_PAPER_ONLY",
        "strategy": strategy,
        "processed_new_candles": processed,
        "last_processed_timestamp": state.get("last_timestamp"),
        "initial_cash_usd": round(initial, 2),
        "cash_usd": round(state["cash"], 2),
        "btc_units": round(state["btc"], 8),
        "equity_after_estimated_exit_costs_usd": round(equity, 2),
        "return_pct": round((equity / initial - 1) * 100, 2),
        "open_position": state["btc"] > 0,
        "completed_trades": len(completed),
        "strategy_health": strategy_health,
        "win_rate_pct": round(len(winning) / len(completed) * 100, 2) if completed else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if gross_profit else 0.0),
        "gross_profit_usd": round(gross_profit, 4),
        "gross_loss_usd": round(gross_loss, 4),
        "max_drawdown_pct": round(float(state.get("max_drawdown_pct", 0.0)), 2),
        "max_consecutive_losses": max_loss_streak,
        "current_consecutive_losses": loss_streak,
        "risk_pause_reasons": [
            reason for reason, active in (
                ("maximum_drawdown", bool(state.get("paused_for_drawdown", False))),
                ("daily_loss_limit", bool(state.get("daily_loss_paused", False))),
                ("consecutive_loss_limit", bool(state.get("paused_for_loss_streak", False))),
                ("strategy_health_deterioration", bool(state.get("paused_for_strategy_health", False))),
            ) if active
        ],
        "recent_trades": completed[-20:],
        "new_trades": new_trades,
        "fees_paid_usd": round(state["fees_paid"], 4),
        "paused_for_drawdown": bool(state.get("paused_for_drawdown", False)),
        "daily_loss_paused": bool(state.get("daily_loss_paused", False)),
        "paused_for_loss_streak": bool(state.get("paused_for_loss_streak", False)),
        "paused_for_strategy_health": bool(state.get("paused_for_strategy_health", False)),
        "risk_limits": {
            "max_drawdown_pct": round(max_drawdown_fraction * 100, 2),
            "daily_loss_pause_pct": round(daily_loss_fraction * 100, 2),
            "max_consecutive_losses": max_consecutive_losses,
            "allocation_pct": round(allocation_fraction * 100, 2),
        },
        "state_persisted": Path(state_path).exists(),
        "warning": "Paper simulation only. Daily loss, max drawdown and consecutive-loss pauses block new entries; persistent pauses require manual review/reset.",
    }
