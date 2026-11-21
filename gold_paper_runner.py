"""Legacy forward-only $10 XAUUSD paper sleeve using validated delayed goldprice.dev spot.

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
from whj_agents import authorize_paper_entry
from metal_price_sources import fetch_spot, fetch_hourly_bars

STATE = Path("state/xauusd_10usd_ema_trend.json")
SNAPSHOT = Path("dual_portfolio.json")
INITIAL_CASH = 10.0
COMPOUND_ALLOCATION_FRACTION = 0.10
STRATEGY = "ema_trend"
QUOTE_URL = "https://api.goldprice.dev/v1/prices?symbol=XAU-USD-SPOT"
HISTORY_URL = "https://api.goldprice.dev/v1/bars?symbol=XAU-USD-SPOT&interval=1h"
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
    quote = fetch_spot("XAUUSD", now)
    rows = fetch_hourly_bars("XAUUSD", now)
    bars = [{
        "timestamp": int(row[0]), "open": float(row[1]), "high": float(row[2]),
        "low": float(row[3]), "close": float(row[4]), "volume": float(row[6]),
        "imputed": False,
    } for row in rows]
    mid = quote["price_usd"]
    market = {
        "provider": quote["provider"], "source": "goldprice.dev XAU/USD spot",
        "quote_timestamp": quote["computed_at"], "quote_age_seconds": quote["quote_age_seconds"],
        "expected_delay_minutes": quote["expected_delay_minutes"],
        "mid_usd_oz": mid, "spread_usd_oz": mid * 0.001,
        "spread_model": "assumed 0.10% spread; free spot provider has no bid/ask",
        "history_interval": "1h", "history_bars": len(bars),
        "latest_closed_bar": datetime.fromtimestamp(bars[-1]["timestamp"], timezone.utc).isoformat(),
        "quality": "DELAYED_SPOT_AND_VALIDATED_HOURLY_BARS",
    }
    return bars, market


def main():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}
    previous_gold = snapshot.get("gold", {})
    try:
        bars, market = load_market()
        spread_cost = market["spread_usd_oz"] / (2.0 * market["mid_usd_oz"])
        slippage = spread_cost + 0.0005
        rows = [[bar["timestamp"], bar["open"], bar["high"], bar["low"], bar["close"], 0.0] for bar in bars]
        seed = seed_forward_paper_account(rows[-50:], STATE, initial_cash=INITIAL_CASH, strategy=STRATEGY)
        entry_audit = {"strategy_signal": "HOLD", "approved_by_consensus": False}
        def entry_gate(context):
            approved = authorize_paper_entry(
                "XAUUSD", market.get("quality") == "HEALTHY", context
            )
            entry_audit.update({
                "strategy_signal": context.get("signal", "HOLD"),
                "approved_by_consensus": approved,
                "timestamp": context.get("timestamp"),
                "reason": "SIX_AGENT_CONSENSUS_APPROVED" if approved else "SIX_AGENT_CONSENSUS_VETO",
            })
            return approved
        result = update_paper_account(
            rows, state_path=str(STATE), initial_cash=INITIAL_CASH,
            fee_rate=0.001, slippage_rate=slippage,
            allocation_fraction=COMPOUND_ALLOCATION_FRACTION,
            max_drawdown_fraction=0.10, daily_loss_fraction=0.03,
            max_consecutive_losses=3, strategy=STRATEGY,
            entry_gate=entry_gate,
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
            "max_drawdown_pct": result["max_drawdown_pct"], "feed_status": "GOLDPRICE_DEV_DELAYED_SPOT_AND_VALIDATED_HOURLY_BARS",
            "status": status, "bid_usd_oz": None, "ask_usd_oz": None,
            "mid_usd_oz": market["mid_usd_oz"], "spread_usd_oz": market["spread_usd_oz"],
            "xau_ounces": round(units, 10), "cash_usd": round(cash, 4),
            "open_position": units > 0, "strategy": STRATEGY,
            "last_processed_timestamp": result["last_processed_timestamp"],
            "processed_new_candles": result["processed_new_candles"],
            "new_trades": result["new_trades"], "risk_pause_reasons": result["risk_pause_reasons"],
            "risk_limits": result["risk_limits"], "warmup_seed_created": seed["created"],
            "data_quality": market,
            "strategy_signal": entry_audit["strategy_signal"],
            "entry_consensus": entry_audit,
            "execution_model": "1h completed goldprice.dev OHLC; spot delayed 15m; assumed 0.10% spread + 0.05% slippage and 0.10% fee per side. No live orders.",
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
        gold["strategy_signal"] = "HOLD"
        gold["entry_consensus"] = {
            "strategy_signal": "HOLD",
            "approved_by_consensus": False,
            "reason": "MARKET_FEED_UNAVAILABLE",
        }
        gold["last_error"] = str(exc)
        gold["processed_new_candles"] = 0
        gold["new_trades"] = []
        print("Gold paper processing blocked:", str(exc))

    snapshot.update({
        "schema_version": 1,
        "status": "BTC_AND_GOLD_PAPER_ONLY",
        "paper_only": True,
        "live_trading_enabled": False,
        "compounding_enabled": True,
        "sizing_mode": "COMPOUND_CURRENT_EQUITY_FRACTION",
        "allocation_fraction": COMPOUND_ALLOCATION_FRACTION,
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
        "Gold uses goldprice.dev delayed XAU/USD spot. Free/keyless intraday bars are plan-gated; no bid/ask is claimed.",
        "Gold transaction costs conservatively model half the latest observed spread, 0.05% slippage and 0.10% fee per side.",
        "Gold strategy is exploratory and has not passed a forward-sample approval gate.",
        "Each new Gold entry sizes at 10% of current realized equity (compounding).",
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
