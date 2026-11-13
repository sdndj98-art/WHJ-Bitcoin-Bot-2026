"""Forward-only $10 XAUUSD paper sleeve using live MT5-sourced biquote two-way quotes.

The history endpoint supplies completed hourly OHLC bars. Entry/exit costs
conservatively include half the currently observed dealer bid/ask spread plus
5 bps slippage and a 10 bps fee per side. No live orders are possible.
"""
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from paper_account import seed_forward_paper_account, update_paper_account

STATE = Path("state/xauusd_10usd_ema_trend.json")
SNAPSHOT = Path("dual_portfolio.json")
INITIAL_CASH = 10.0
STRATEGY = "ema_trend"
QUOTE_URL = "https://biquote.io/api/XAUUSD?allowStale=false"
HISTORY_URL = "https://biquote.io/api/XAUUSD/ohlc?interval=1h&limit=1000"
BAR_SECONDS = 3600


def get_json(url):
    request = Request(url, headers={"User-Agent": "WHJ-PaperResearch/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError("Gold provider returned HTTP " + str(response.status))
        return json.loads(response.read().decode("utf-8"))


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("Provider timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Provider timestamp must include a timezone")
    return parsed.timestamp()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                prefix="." + path.name + ".", suffix=".tmp", delete=False) as handle:
            temp = handle.name
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        if temp and os.path.exists(temp):
            os.unlink(temp)
        raise


def load_market():
    now = datetime.now(timezone.utc).timestamp()
    quote = get_json(QUOTE_URL)
    quote_age = float(quote.get("quoteAgeSeconds", math.inf))
    quote_time = parse_time(quote.get("timestamp"))
    if quote.get("symbol") != "XAUUSD":
        raise ValueError("Unexpected live gold quote symbol")
    if quote.get("marketState") != "open" or quote.get("stale") is not False:
        raise ValueError("Gold market is closed or quote is marked stale")
    if not math.isfinite(quote_age) or quote_age < 0 or quote_age > 180:
        raise ValueError("Gold bid/ask quote is stale")
    if quote_time > now + 30:
        raise ValueError("Gold quote timestamp is in the future")
    bid, ask = float(quote["bid"]), float(quote["ask"])
    if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
        raise ValueError("Invalid gold bid/ask")
    mid = (bid + ask) / 2.0
    spread = ask - bid
    half_spread_fraction = spread / (2.0 * mid)
    if half_spread_fraction > 0.005:
        raise ValueError("Gold bid/ask spread exceeds the 0.50% safety ceiling")

    history_data = get_json(HISTORY_URL)
    if history_data.get("symbol") != "XAUUSD" or history_data.get("interval") != "1h":
        raise ValueError("Gold OHLC response symbol or interval is invalid")
    source_bars = history_data.get("bars")
    if not isinstance(source_bars, list):
        raise ValueError("Gold OHLC bars are missing")
    bars = []
    for row in source_bars:
        if row.get("isOpen") is not False:
            continue
        timestamp = parse_time(row.get("openTime"))
        if abs(timestamp % BAR_SECONDS) > 1:
            raise ValueError("Gold hourly candle is not aligned")
        values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError("Gold OHLC contains an invalid price")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError("Gold candle high is inconsistent")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError("Gold candle low is inconsistent")
        bars.append({
            "timestamp": int(timestamp), **values,
            "volume": float(row.get("tickVolume", 0) or 0),
            "imputed": False,
        })
    bars.sort(key=lambda item: item["timestamp"])
    unique = {}
    for bar in bars:
        unique[bar["timestamp"]] = bar
    bars = list(unique.values())
    if len(bars) < 50:
        raise ValueError("Insufficient completed hourly gold candles for EMA12/26: " + str(len(bars)) + " of " + str(len(source_bars)) + " provider bars after closed-bar validation")
    if any(bars[i]["timestamp"] >= bars[i + 1]["timestamp"] for i in range(len(bars) - 1)):
        raise ValueError("Gold candle timestamps are not strictly increasing")
    recent = bars[-25:]
    if any(b["timestamp"] - a["timestamp"] != BAR_SECONDS for a, b in zip(recent, recent[1:])):
        raise ValueError("Recent gold hourly history has gaps; execution blocked")
    history_age = now - (bars[-1]["timestamp"] + BAR_SECONDS)
    if history_age < -60 or history_age > 90 * 60:
        raise ValueError("Latest completed gold hourly candle is stale")
    return bars, {
        "provider": "biquote · MT5 broker feed",
        "source": quote.get("source"),
        "quote_timestamp": quote.get("timestamp"),
        "quote_age_seconds": round(quote_age, 1),
        "bid_usd_oz": bid,
        "ask_usd_oz": ask,
        "mid_usd_oz": mid,
        "spread_usd_oz": spread,
        "half_spread_pct": round(half_spread_fraction * 100, 5),
        "history_interval": "1h",
        "history_bars": len(bars),
        "latest_closed_bar": datetime.fromtimestamp(bars[-1]["timestamp"], timezone.utc).isoformat(),
        "latest_closed_bar_age_minutes": round(history_age / 60, 2),
        "quality": "HEALTHY",
    }

def main():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}
    previous_gold = snapshot.get("gold", {})
    try:
        bars, market = load_market()
        spread_cost = market["spread_usd_oz"] / (2.0 * market["mid_usd_oz"])
        slippage = spread_cost + 0.0005
        rows = [[bar["timestamp"], bar["open"], bar["high"], bar["low"], bar["close"], 0.0] for bar in bars]
        seed = seed_forward_paper_account(rows[-50:], STATE, initial_cash=INITIAL_CASH, strategy=STRATEGY)
        result = update_paper_account(
            rows, state_path=str(STATE), initial_cash=INITIAL_CASH,
            fee_rate=0.001, slippage_rate=slippage, allocation_fraction=0.10,
            max_drawdown_fraction=0.10, daily_loss_fraction=0.03,
            max_consecutive_losses=3, strategy=STRATEGY,
        )
        ledger = json.loads(STATE.read_text(encoding="utf-8"))
        units = float(ledger["btc"])
        cash = float(ledger["cash"])
        equity = cash + units * market["mid_usd_oz"] * (1.0 - slippage) * (1.0 - 0.001)
        status = "RISK_PAUSED" if result["risk_pause_reasons"] else (
            "PAPER_RUNNING" if result["processed_new_candles"] else "PAPER_ACTIVE_WAITING_NEXT_1H_CANDLE")
        gold = {
            "asset": "XAUUSD", "symbol": "XAU/USD spot", "initial_equity_usd": INITIAL_CASH,
            "equity_usd": round(equity, 4), "pnl_usd": round(equity - INITIAL_CASH, 4),
            "return_pct": round((equity / INITIAL_CASH - 1.0) * 100.0, 4),
            "closed_trades": result["completed_trades"], "fees_usd": result["fees_paid_usd"],
            "max_drawdown_pct": result["max_drawdown_pct"], "feed_status": "BIQUOTE_MT5_XAUUSD_BID_ASK_FRESH",
            "status": status, "bid_usd_oz": market["bid_usd_oz"], "ask_usd_oz": market["ask_usd_oz"],
            "mid_usd_oz": market["mid_usd_oz"], "spread_usd_oz": market["spread_usd_oz"],
            "xau_ounces": round(units, 10), "cash_usd": round(cash, 4),
            "open_position": units > 0, "strategy": STRATEGY,
            "last_processed_timestamp": result["last_processed_timestamp"],
            "processed_new_candles": result["processed_new_candles"],
            "new_trades": result["new_trades"], "risk_pause_reasons": result["risk_pause_reasons"],
            "risk_limits": result["risk_limits"], "warmup_seed_created": seed["created"],
            "data_quality": market,
            "execution_model": "1h completed MT5 OHLC; buy/sell cost includes half current bid/ask spread + 0.05% slippage and 0.10% fee per side. No live orders.",
        }
    except Exception as exc:
        gold = dict(previous_gold)
        gold.setdefault("asset", "XAUUSD")
        gold.setdefault("symbol", "XAU/USD spot")
        gold.setdefault("initial_equity_usd", INITIAL_CASH)
        gold.setdefault("equity_usd", INITIAL_CASH)
        gold.setdefault("pnl_usd", 0.0)
        gold.setdefault("return_pct", 0.0)
        gold.setdefault("closed_trades", 0)
        gold["feed_status"] = "BIQUOTE_MT5_UNAVAILABLE"
        gold["status"] = "FEED_BLOCKED_NO_NEW_TRADES"
        gold["last_error"] = str(exc)
        gold["processed_new_candles"] = 0
        gold["new_trades"] = []
        print("Gold paper processing blocked:", str(exc))

    snapshot.update({
        "schema_version": 1,
        "status": "BTC_AND_GOLD_PAPER_ONLY",
        "paper_only": True,
        "live_trading_enabled": False,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gold": gold,
    })
    strategies = [item for item in snapshot.get("strategies", []) if item.get("asset") != "XAUUSD"]
    strategies.append({
        "asset": "XAUUSD", "strategy": STRATEGY,
        "equity_usd": gold.get("equity_usd", INITIAL_CASH),
        "return_pct": gold.get("return_pct", 0.0),
        "closed_trades": gold.get("closed_trades", 0),
        "fees_usd": gold.get("fees_usd", 0.0),
        "max_drawdown_pct": gold.get("max_drawdown_pct", 0.0),
        "status": gold.get("status", "UNKNOWN"),
    })
    snapshot["strategies"] = strategies
    snapshot["notes"] = [
        "BTC and XAUUSD are independent $10 forward-only paper ledgers.",
        "Gold uses biquote's MT5-sourced XAUUSD bid/ask and hourly OHLC feed; this is a third-party broker feed, not the user's own broker quote.",
        "Gold transaction costs conservatively model half the latest observed spread, 0.05% slippage and 0.10% fee per side.",
        "Gold strategy is exploratory and has not passed a forward-sample approval gate.",
        "Historical candles warm indicators only; no historical trades or PnL are counted.",
        "No real orders are sent.",
    ]
    atomic_json(SNAPSHOT, snapshot)
    print(json.dumps({
        "gold_status": gold.get("status"),
        "equity_usd": gold.get("equity_usd"),
        "pnl_usd": gold.get("pnl_usd"),
        "closed_trades": gold.get("closed_trades"),
        "processed_new_candles": gold.get("processed_new_candles", 0),
        "quote": {k: market.get(k) for k in ("bid_usd_oz", "ask_usd_oz", "spread_usd_oz")} if "market" in locals() else None,
        "error": gold.get("last_error"),
    }, indent=2))


if __name__ == "__main__":
    main()
