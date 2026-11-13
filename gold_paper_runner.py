"""Forward-only $10 XAUUSD paper sleeve using Standard Bullion two-way quotes.

The history endpoint supplies 15-minute reference closes. Entry/exit costs
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

STATE = Path("state/xauusd_10usd_rsi14_mean_reversion.json")
SNAPSHOT = Path("dual_portfolio.json")
INITIAL_CASH = 10.0
STRATEGY = "rsi14_mean_reversion"
QUOTE_URL = "https://standardbullion.com/spot-prices.json"
HISTORY_URL = "https://standardbullion.com/api/v1/market/history?metal=XAU&range=7d"
BAR_SECONDS = 900


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
    quote_data = get_json(QUOTE_URL)
    updated = parse_time(quote_data.get("updated"))
    quote_age = now - updated
    if quote_age < -30 or quote_age > 180:
        raise ValueError("Gold bid/ask quote is stale or future-dated")
    if quote_data.get("unit") != "USD per troy ounce":
        raise ValueError("Unexpected gold quote unit")
    gold_rows = [row for row in quote_data.get("metals", []) if row.get("symbol") == "XAU"]
    if len(gold_rows) != 1:
        raise ValueError("Gold XAU quote missing or ambiguous")
    quote = gold_rows[0]
    bid, ask = float(quote["bid"]), float(quote["ask"])
    if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
        raise ValueError("Invalid gold bid/ask")
    mid = (bid + ask) / 2.0
    spread = ask - bid
    half_spread_fraction = spread / (2.0 * mid)
    if half_spread_fraction > 0.005:
        raise ValueError("Gold bid/ask spread exceeds the 0.50% safety ceiling")

    history_data = get_json(HISTORY_URL)
    points = history_data.get("points")
    if history_data.get("metal") != "XAU" or not isinstance(points, list):
        raise ValueError("Gold history response schema is invalid")
    normalized = []
    for point in points:
        timestamp = parse_time(point.get("t"))
        price = float(point.get("price"))
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Gold historical price is invalid")
        bucket = int(timestamp // BAR_SECONDS) * BAR_SECONDS
        # History points are provider-published 15-minute reference closes.
        if abs(timestamp - bucket) > 60:
            continue
        if timestamp <= updated + 30:
            normalized.append((bucket, price))
    normalized.sort()
    deduped = {}
    for timestamp, price in normalized:
        deduped[timestamp] = price
    bars = [{"timestamp": t, "open": p, "high": p, "low": p,
             "close": p, "volume": 0.0, "imputed": False}
            for t, p in sorted(deduped.items())]
    if len(bars) < 200:
        raise ValueError("At least 200 real 15-minute gold closes are required")
    if any(bars[i]["timestamp"] >= bars[i + 1]["timestamp"] for i in range(len(bars) - 1)):
        raise ValueError("Gold candle timestamps are not strictly increasing")
    recent = bars[-25:]
    if any(b["timestamp"] - a["timestamp"] != BAR_SECONDS for a, b in zip(recent, recent[1:])):
        raise ValueError("Recent gold 15-minute history has gaps; execution blocked")
    history_age = now - (bars[-1]["timestamp"] + BAR_SECONDS)
    if history_age < -60 or history_age > 45 * 60:
        raise ValueError("Latest completed gold 15-minute candle is stale")
    return bars, {
        "provider": "Standard Bullion",
        "quote_updated_at": quote_data["updated"],
        "quote_age_seconds": round(quote_age, 1),
        "bid_usd_oz": bid,
        "ask_usd_oz": ask,
        "mid_usd_oz": mid,
        "spread_usd_oz": spread,
        "half_spread_pct": round(half_spread_fraction * 100, 5),
        "history_grain": history_data.get("grain", "15-minute provider closes"),
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
        seed = seed_forward_paper_account(rows[-200:], STATE, initial_cash=INITIAL_CASH, strategy=STRATEGY)
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
            "PAPER_RUNNING" if result["processed_new_candles"] else "PAPER_ACTIVE_WAITING_NEXT_15M_CANDLE")
        gold = {
            "asset": "XAUUSD", "symbol": "XAU/USD spot", "initial_equity_usd": INITIAL_CASH,
            "equity_usd": round(equity, 4), "pnl_usd": round(equity - INITIAL_CASH, 4),
            "return_pct": round((equity / INITIAL_CASH - 1.0) * 100.0, 4),
            "closed_trades": result["completed_trades"], "fees_usd": result["fees_paid_usd"],
            "max_drawdown_pct": result["max_drawdown_pct"], "feed_status": "STANDARD_BULLION_BID_ASK_FRESH",
            "status": status, "bid_usd_oz": market["bid_usd_oz"], "ask_usd_oz": market["ask_usd_oz"],
            "mid_usd_oz": market["mid_usd_oz"], "spread_usd_oz": market["spread_usd_oz"],
            "xau_ounces": round(units, 10), "cash_usd": round(cash, 4),
            "open_position": units > 0, "strategy": STRATEGY,
            "last_processed_timestamp": result["last_processed_timestamp"],
            "processed_new_candles": result["processed_new_candles"],
            "new_trades": result["new_trades"], "risk_pause_reasons": result["risk_pause_reasons"],
            "risk_limits": result["risk_limits"], "warmup_seed_created": seed["created"],
            "data_quality": market,
            "execution_model": "15m close-only reference history; buy/sell cost includes half latest dealer spread + 0.05% slippage and 0.10% fee per side. No live orders.",
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
        gold["feed_status"] = "STANDARD_BULLION_UNAVAILABLE"
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
        "Gold uses Standard Bullion's own wholesale bid/ask quote and 15-minute reference history; provider prices are not the user's broker execution prices.",
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
