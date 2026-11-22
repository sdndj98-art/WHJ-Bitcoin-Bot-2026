"""Eight-strategy shared-$100 BTC paper engine. No exchange order endpoints."""
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from historical_research import load_two_year_candles
from forward_paper_monitor import validate_hourly_feed
from shared_paper_portfolio import SharedPaperPortfolio, SUPPORTED_STRATEGIES
from whj_agents import authorize_paper_entry

LEDGER = Path("state/shared_paper_100usd.json")
SNAPSHOT = Path("dual_portfolio.json")
INITIAL_CASH = 100.0
ALLOCATION_FRACTION = 0.10
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005
MAX_DRAWDOWN = 0.10
DAILY_LOSS_LIMIT = 0.03
MIN_TRADE_USD = 1.0


def atomic_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(target.parent),
                prefix="." + target.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
        raise


def ema(values, period):
    alpha = 2.0 / (period + 1.0)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1.0 - alpha) * result
    return result


def rsi(values, period=14):
    changes = [float(values[i]) - float(values[i - 1]) for i in range(1, len(values))]
    recent = changes[-period:]
    gains = sum(max(x, 0.0) for x in recent) / period
    losses = sum(max(-x, 0.0) for x in recent) / period
    if losses == 0:
        return 100.0 if gains else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def strategy_signal(strategy, history, holding_bars=0):
    """Signals use only completed candles before the current execution candle."""
    minimum_history = {
        "sma_trend": 20,
        "ema_trend": 50,
        "rsi_momentum": 50,
        "sma200_regime": 200,
        "ema50_200_regime": 200,
        "bollinger_mean_reversion": 20,
        "rsi14_mean_reversion": 15,
        "compound_momentum": 50,
    }
    if strategy not in minimum_history:
        raise ValueError("Unsupported strategy: " + str(strategy))
    if len(history) < minimum_history[strategy]:
        return False, False
    prior = float(history[-1])
    values = [float(x) for x in history]
    sma_window = values[-20:]
    sma20 = sum(sma_window) / len(sma_window)
    sma50 = sum(values[-50:]) / 50.0 if len(values) >= 50 else None
    if strategy == "sma_trend":
        # Faster paper-test entry: participate when price is above the 20-bar
        # mean, rather than waiting for the slower 50-bar trend confirmation.
        want = prior > sma20
        return want, not want
    if strategy == "ema_trend":
        fast, slow = ema(values[-50:], 12), ema(values[-50:], 26)
        # Earlier entry while the fast EMA is above the slow EMA; retain price
        # confirmation so the strategy does not buy a falling EMA cross alone.
        want = fast > slow and prior > slow
        return want, not want
    if strategy == "rsi_momentum":
        momentum = rsi(values, 14)
        fast_rsi = rsi(values, 2)
        slow = ema(values[-50:], 26)
        # Normal momentum entries plus a short RSI pullback entry in an
        # established 50-bar uptrend; all inputs are completed candles.
        want = (50 < momentum < 75 and prior > slow) or (fast_rsi < 25 and prior > sma50)
        return want, not want
    if strategy in ("sma200_regime", "ema50_200_regime"):
        sma200 = sum(values[-200:]) / 200.0
    if strategy == "sma200_regime":
        want = prior > sma20 > sma50 and prior > sma200
        return want, not want
    if strategy == "ema50_200_regime":
        fast, slow = ema(values[-200:], 50), ema(values[-200:], 200)
        want = fast > slow and prior > slow
        return want, not want
    if strategy == "bollinger_mean_reversion":
        window = values[-20:]
        mean = sum(window) / 20.0
        variance = sum((x - mean) ** 2 for x in window) / 20.0
        lower = mean - 2.0 * math.sqrt(variance)
        if holding_bars <= 0:
            return prior < lower, False
        return False, prior >= mean or holding_bars >= 10
    if strategy == "rsi14_mean_reversion":
        momentum = rsi(values, 14)
        if holding_bars <= 0:
            return momentum < 30, False
        return False, momentum > 55 or momentum < 20 or holding_bars >= 10
    if strategy == "compound_momentum":
        fast, slow = ema(values[-50:], 12), ema(values[-50:], 26)
        momentum = rsi(values, 14)
        return_20 = prior / values[-21] - 1.0 if values[-21] > 0 else 0.0
        trend_confirmed = fast > slow and prior > slow and return_20 > 0
        # Allow a mild RSI pullback while preserving positive trend and 20-bar
        # return; avoid chasing overbought momentum above 72.
        momentum_window = 45 <= momentum <= 72
        want = trend_confirmed and momentum_window
        exit_signal = (
            fast <= slow or prior <= slow or momentum >= 80 or return_20 <= -0.01
        )
        return want, exit_signal
    raise ValueError("Unsupported strategy: " + str(strategy))


def _new_strategy_state(rows):
    closes = [float(row[4]) for row in rows[-200:]]
    timestamp = int(rows[-1][0])
    return {
        name: {
            "last_timestamp": timestamp,
            "recent_closes": closes,
            "holding_bars": 0,
            "daily_bucket": datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(),
            "daily_start_equity": INITIAL_CASH,
            "peak_equity": INITIAL_CASH,
            "paused_for_drawdown": False,
            "daily_loss_paused": False,
            "loss_streak": 0,
            "paused_for_loss_streak": False,
            "trades": 0,
            "warmup_seeded": True,
        } for name in SUPPORTED_STRATEGIES
    }



def _ensure_strategy_state(strategy_state, rows):
    """Add newly introduced strategy cursors without resetting existing ones."""
    if not isinstance(strategy_state, dict):
        raise ValueError("Saved BTC strategy state is malformed; refusing reset")
    fresh = _new_strategy_state(rows)
    added = []
    for name in SUPPORTED_STRATEGIES:
        if not isinstance(strategy_state.get(name), dict):
            strategy_state[name] = fresh[name]
            added.append(name)
    return added

def main():
    candles = load_two_year_candles(days=300)
    quality = validate_hourly_feed(candles)
    if quality.get("quality") != "HEALTHY":
        raise RuntimeError("BTC feed failed quality gate; shared portfolio not advanced")
    rows = [[int(row["timestamp"] // 1000), float(row["open"]), float(row["high"]),
             float(row["low"]), float(row["close"]), float(row.get("volume", 0) or 0)]
            for row in candles]
    if len(rows) < 200:
        raise RuntimeError("At least 200 completed BTC candles are required")
    if any(rows[i][0] >= rows[i + 1][0] for i in range(len(rows) - 1)):
        raise RuntimeError("BTC candle timestamps must be unique and increasing")

    book = SharedPaperPortfolio(LEDGER, initial_cash_usd=INITIAL_CASH, fee_rate=FEE_RATE)
    # If non-BTC positions exist but the shared snapshot has stale/missing marks,
    # pause this BTC sub-engine without valuing them at stale prices or failing
    # the whole workflow. The multi-asset engine refreshes marks from providers.
    try:
        liquidation_equity(book, rows[-1][4])
    except RuntimeError as exc:
        print(json.dumps({
            "status": "PAPER_BLOCKED_STALE_SHARED_MARKS",
            "reason": str(exc)[:300],
            "paper_only": True,
            "live_trading_enabled": False,
            "trades_opened": 0,
            "ledger_unchanged": True,
        }, indent=2))
        return
    strategy_state = book.state.get("strategy_state", {})
    if not strategy_state:
        strategy_state = _new_strategy_state(rows)
        book.save_strategy_state(strategy_state)
        latest = rows[-1]
        snapshot = _make_snapshot(book, strategy_state, latest[4], quality, "WARMUP_SEEDED")
        book.save_strategy_state(strategy_state)
        atomic_json(SNAPSHOT, snapshot)
        print(json.dumps({"status": "WARMUP_SEEDED", "initial_cash_usd": INITIAL_CASH,
                          "strategies": len(SUPPORTED_STRATEGIES), "processed_new_candles": 0}, indent=2))
        return

    _ensure_strategy_state(strategy_state, rows)
    processed = 0
    new_trades = []
    for row in rows:
        timestamp, close = int(row[0]), float(row[4])
        if all(timestamp <= int(strategy_state[name]["last_timestamp"]) for name in SUPPORTED_STRATEGIES):
            continue
        for name in SUPPORTED_STRATEGIES:
            state = strategy_state[name]
            if timestamp <= int(state["last_timestamp"]):
                continue
            history = list(state["recent_closes"])
            if len(history) >= (200 if name in ("sma200_regime", "ema50_200_regime",
                                                  "bollinger_mean_reversion", "rsi14_mean_reversion") else 50):
                equity = liquidation_equity(book, close)
                peak = max(float(state["peak_equity"]), equity)
                state["peak_equity"] = peak
                drawdown = (peak - equity) / peak if peak > 0 else 0.0
                if drawdown >= MAX_DRAWDOWN:
                    state["paused_for_drawdown"] = True
                day = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
                if day != state["daily_bucket"]:
                    state["daily_bucket"] = day
                    state["daily_start_equity"] = equity
                    state["daily_loss_paused"] = False
                if equity <= float(state["daily_start_equity"]) * (1.0 - DAILY_LOSS_LIMIT):
                    state["daily_loss_paused"] = True
                want_long, want_flat = strategy_signal(name, history, int(state["holding_bars"]))
                position_id = "btc-" + name
                position = book.state["positions"].get(position_id)
                paused = (state["paused_for_drawdown"] or state["daily_loss_paused"]
                          or state["paused_for_loss_streak"])
                if position and (want_flat or paused):
                    trade = book.close_position(position_id, close * (1.0 - SLIPPAGE_RATE))
                    new_trades.append(trade)
                    state["trades"] += 1
                    state["loss_streak"] = state["loss_streak"] + 1 if trade["pnl_usd"] < 0 else 0
                    if state["loss_streak"] >= 3:
                        state["paused_for_loss_streak"] = True
                    state["holding_bars"] = 0
                elif not position and want_long and not paused:
                    allowed = authorize_paper_entry(
                        "BTC", True,
                        {"signal": "BUY", "allocation_pct": ALLOCATION_FRACTION * 100,
                         "risk_paused": False},
                    )
                    if allowed:
                        current_equity = liquidation_equity(book, close)
                        notional = min(book.state["cash_usd"] / (1.0 + FEE_RATE),
                                       current_equity * ALLOCATION_FRACTION)
                        if notional >= MIN_TRADE_USD:
                            try:
                                opened = book.open_position(
                                    name, "BTC/USD", close * (1.0 + SLIPPAGE_RATE),
                                    notional, position_id,
                                )
                                new_trades.append({"event": "OPEN", **opened,
                                                   "timestamp": timestamp})
                                state["holding_bars"] = 0
                            except ValueError as exc:
                                if "Insufficient shared cash" not in str(exc):
                                    raise
                if position and not (want_flat or paused) and name in ("bollinger_mean_reversion", "rsi14_mean_reversion"):
                    state["holding_bars"] += 1
            state["recent_closes"] = (history + [close])[-200:]
            state["last_timestamp"] = timestamp
        processed += 1

    book.save_strategy_state(strategy_state)
    latest_close = rows[-1][4]
    snapshot = _make_snapshot(book, strategy_state, latest_close, quality,
                              "PAPER_RUNNING" if processed else "WAITING_NEXT_CLOSED_CANDLE",
                              processed, new_trades)
    book.save_strategy_state(strategy_state)
    atomic_json(SNAPSHOT, snapshot)
    print(json.dumps({
        "status": snapshot["status"], "initial_cash_usd": INITIAL_CASH,
        "cash_usd": snapshot["shared_portfolio"]["cash_usd"],
        "equity_usd": snapshot["shared_portfolio"]["equity_usd"],
        "pnl_usd": snapshot["shared_portfolio"]["pnl_usd"],
        "processed_new_candles": processed, "new_events": len(new_trades),
        "open_positions": len(snapshot["shared_portfolio"]["open_positions"]),
        "paper_only": True, "live_trading_enabled": False,
    }, indent=2))


def _shared_mark_prices(book, btc_price):
    """Use the current BTC candle and fresh prior marks for other shared assets."""
    prices = {"BTC/USD": float(btc_price)}
    other_positions = [
        (position_id, position)
        for position_id, position in book.state["positions"].items()
        if position.get("asset") != "BTC/USD"
    ]
    if not other_positions:
        return prices
    try:
        previous = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(str(previous["updated_at"]).replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - updated).total_seconds()
        if age_seconds < -60 or age_seconds > 1800:
            raise ValueError("Prior shared-asset marks are stale")
        listed = previous["shared_portfolio"]["open_positions"]
        marks = {
            item["position_id"]: float(item["mark_price"])
            for item in listed
            if isinstance(item, dict) and item.get("position_id")
            and item.get("mark_price") is not None
        }
    except Exception as exc:
        raise RuntimeError("Cannot value non-BTC shared positions safely: " + str(exc)) from exc
    for position_id, position in other_positions:
        mark = marks.get(position_id)
        if mark is None or not math.isfinite(mark) or mark <= 0:
            raise RuntimeError("Missing fresh prior mark for shared position " + str(position_id))
        prices[position["asset"]] = mark
    return prices


def liquidation_equity(book, price):
    prices = _shared_mark_prices(book, price)
    mark = book.snapshot(prices)
    liquidation_value = sum(
        float(position["units"]) * float(prices[position["asset"]])
        * (1.0 - SLIPPAGE_RATE) * (1.0 - FEE_RATE)
        for position in mark["open_positions"]
    )
    return float(mark["cash_usd"]) + liquidation_value


def _make_snapshot(book, strategy_state, price, quality, status,
                   processed=0, new_trades=None):
    prices = _shared_mark_prices(book, price)
    shared = book.snapshot(prices)
    gross_market_value = float(shared["market_value_usd"])
    net_market_value = sum(
        float(position["units"]) * float(prices[position["asset"]])
        * (1.0 - SLIPPAGE_RATE) * (1.0 - FEE_RATE)
        for position in shared["open_positions"]
    )
    for position in shared["open_positions"]:
        position["gross_market_value_usd"] = position["market_value_usd"]
        position["market_value_usd"] = round(
            float(position["units"]) * float(prices[position["asset"]])
            * (1.0 - SLIPPAGE_RATE) * (1.0 - FEE_RATE), 10
        )
    shared["gross_market_value_usd"] = gross_market_value
    shared["estimated_exit_costs_usd"] = gross_market_value - net_market_value
    shared["market_value_usd"] = net_market_value
    shared["equity_usd"] = float(shared["cash_usd"]) + net_market_value
    shared["pnl_usd"] = shared["equity_usd"] - float(shared["initial_cash_usd"])
    by_strategy = {}
    for name in SUPPORTED_STRATEGIES:
        positions = [p for p in shared["open_positions"] if p["strategy"] == name]
        market_value = sum(p["market_value_usd"] for p in positions)
        state = strategy_state[name]
        closed = [trade for trade in book.state["closed_trades"] if trade.get("strategy") == name]
        pnls = [float(trade.get("pnl_usd", 0.0)) for trade in closed]
        wins = [value for value in pnls if value > 0]
        losses = [-value for value in pnls if value < 0]
        gross_profit, gross_loss = sum(wins), sum(losses)
        loss_streak = 0
        for value in reversed(pnls):
            if value < 0:
                loss_streak += 1
            else:
                break
        open_fees = sum(float(book.state["positions"][p["position_id"]]["entry_fee_usd"])
                        for p in positions if p["position_id"] in book.state["positions"])
        fees = sum(float(trade.get("fees_usd", 0.0)) for trade in closed) + open_fees
        # Attribute each strategy's own realized and open-position PnL.
        # Shared cash is not divided equally: that misstates returns when
        # strategies have different amounts of capital deployed.
        realized_pnl = sum(pnls)
        unrealized_pnl = sum(
            float(book.state["positions"][p["position_id"]]["units"])
            * float(prices[p["asset"]])
            * (1.0 - SLIPPAGE_RATE) * (1.0 - FEE_RATE)
            - float(book.state["positions"][p["position_id"]]["entry_notional_usd"])
            - float(book.state["positions"][p["position_id"]]["entry_fee_usd"])
            for p in positions
        )
        allocated_initial = INITIAL_CASH / len(SUPPORTED_STRATEGIES)
        strategy_pnl = realized_pnl + unrealized_pnl
        strategy_equity = allocated_initial + strategy_pnl
        # Persist a per-strategy high-water mark at each completed snapshot.
        # This is candle/snapshot-sampled drawdown, not tick-level intrabar DD.
        peak = max(
            float(state.get("peak_strategy_equity_usd", allocated_initial)),
            strategy_equity,
        )
        current_drawdown = max(0.0, (peak - strategy_equity) / peak * 100.0)
        max_drawdown = max(
            float(state.get("max_strategy_drawdown_pct", 0.0)),
            current_drawdown,
        )
        state["peak_strategy_equity_usd"] = round(peak, 8)
        state["max_strategy_drawdown_pct"] = round(max_drawdown, 4)
        by_strategy[name] = {
            "asset": "BTC", "strategy": name,
            "initial_equity_usd": round(allocated_initial, 8),
            "equity_usd": round(strategy_equity, 8),
            "realized_pnl_usd": round(realized_pnl, 8),
            "unrealized_pnl_usd": round(unrealized_pnl, 8),
            "net_pnl_usd": round(strategy_pnl, 8),
            "return_pct": round(strategy_pnl / allocated_initial * 100.0, 4),
            "open_positions": len(positions), "market_value_usd": round(market_value, 8),
            "trades": len(closed),
            "win_rate_pct": round(len(wins) / len(closed) * 100.0, 4) if closed else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else (None if not gross_profit else None),
            "fees_paid_usd": round(fees, 8),
            "max_consecutive_losses": loss_streak,
            "current_drawdown_pct": round(current_drawdown, 4),
            "max_drawdown_pct": round(max_drawdown, 4),
            "drawdown_observation": "COMPLETED_CANDLE_SNAPSHOT_SAMPLED",
            "paused_for_drawdown": bool(state.get("paused_for_drawdown")),
            "daily_loss_paused": bool(state.get("daily_loss_paused")),
            "paused_for_loss_streak": bool(state.get("paused_for_loss_streak")),
            "paused": bool(state.get("paused_for_drawdown")
                           or state.get("daily_loss_paused")
                           or state.get("paused_for_loss_streak")),
        }
    btc = {
        "asset": "BTC", "symbol": "BTC/USD", "initial_equity_usd": INITIAL_CASH,
        "equity_usd": round(shared["equity_usd"], 4),
        "pnl_usd": round(shared["pnl_usd"], 4),
        "return_pct": round(shared["pnl_usd"] / INITIAL_CASH * 100, 4),
        "closed_trades": shared["closed_trades"], "fees_usd": shared["fees_paid_usd"],
        "feed_status": "COINBASE_BTC_USD_HOURLY_HEALTHY", "status": status if str(status).startswith("PAPER_") else "PAPER_" + str(status),
        "last_price_usd": float(price), "open_position": bool(shared["open_positions"]),
        "cash_usd": shared["cash_usd"], "data_quality": quality,
        "risk_limits": {"max_drawdown_pct": 10, "daily_loss_pause_pct": 3,
                        "max_consecutive_losses": 3, "allocation_pct": 10},
        "risk_pause_reasons": [],
        "strategy_signal": "MULTI_STRATEGY_PAPER",
        "new_trades": new_trades or [],
        "execution_model": "Completed hourly BTC candles; shared $100 cash pool; 0.10% fee and 0.05% slippage per side. No live orders.",
    }
    gold = {
        "asset": "XAUUSD", "symbol": "XAU/USD spot",
        "initial_equity_usd": 0.0, "equity_usd": 0.0, "pnl_usd": 0.0,
        "return_pct": 0.0, "closed_trades": 0, "fees_usd": 0.0,
        "feed_status": "DISABLED_NO_VALIDATED_FEED",
        "status": "FEED_BLOCKED_NO_NEW_TRADES",
        "strategy_signal": "HOLD",
        "entry_consensus": {"approved_by_consensus": False, "reason": "NO_VALIDATED_FEED"},
        "last_error": "Gold trading remains disabled until a fresh, validated two-way XAUUSD feed is available.",
        "new_trades": [],
    }
    return {
        "schema_version": 2, "status": status, "paper_only": True,
        "live_trading_enabled": False, "compounding_enabled": True,
        "sizing_mode": "SHARED_100USD_EQUITY_FRACTION",
        "initial_capital_usd": INITIAL_CASH, "updated_at": datetime.now(timezone.utc).isoformat(),
        "shared_portfolio": shared, "btc": btc, "gold": gold,
        "strategies": [
            {"asset": "BTC", "strategy": name,
             "initial_equity_usd": by_strategy[name]["initial_equity_usd"],
             "equity_usd": by_strategy[name]["equity_usd"],
             "return_pct": by_strategy[name]["return_pct"],
             "realized_pnl_usd": by_strategy[name]["realized_pnl_usd"],
             "unrealized_pnl_usd": by_strategy[name]["unrealized_pnl_usd"],
             "net_pnl_usd": by_strategy[name]["net_pnl_usd"],
             "closed_trades": by_strategy[name]["trades"],
             "win_rate_pct": by_strategy[name]["win_rate_pct"],
             "profit_factor": by_strategy[name]["profit_factor"],
             "fees_usd": by_strategy[name]["fees_paid_usd"],
             "max_consecutive_losses": by_strategy[name]["max_consecutive_losses"],
             "current_drawdown_pct": by_strategy[name]["current_drawdown_pct"],
             "max_drawdown_pct": by_strategy[name]["max_drawdown_pct"],
             "status": "PAPER_ONLY", "open_positions": by_strategy[name]["open_positions"],
             "paused": by_strategy[name]["paused"],
             "paused_for_drawdown": by_strategy[name]["paused_for_drawdown"],
             "daily_loss_paused": by_strategy[name]["daily_loss_paused"],
             "paused_for_loss_streak": by_strategy[name]["paused_for_loss_streak"]}
            for name in SUPPORTED_STRATEGIES
        ],
        "strategy_details": by_strategy,
        "bull_summary": "Eight strategy families share one $100 paper-only BTC portfolio.",
        "bear_summary": "Entries require completed-candle signals, fresh feed quality, sizing and six-agent consensus.",
        "risk_decision": status,
        "notes": [
            "One $100 simulated cash pool is shared across all eight BTC strategies; cash and net PnL compound together.",
            "Legacy independent BTC/Gold $10 ledgers are preserved and are not added to the new account.",
            "Gold is disabled until a fresh validated two-way XAUUSD feed is available.",
            "Historical candles warm indicators only; first run seeds the forward-only cursor without historical trades.",
            "No real exchange or broker orders are sent.",
        ],
    }


if __name__ == "__main__":
    main()
