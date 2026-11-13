"""$10 BTC forward-only paper portfolio. No exchange order endpoints."""
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
from historical_research import load_two_year_candles
from forward_paper_monitor import validate_hourly_feed
from paper_account import seed_forward_paper_account, update_paper_account

STATE = Path("state/btc_10usd_rsi14_mean_reversion.json")
CASH = 10.0
COMPOUND_ALLOCATION_FRACTION = 0.10
STRATEGY = "rsi14_mean_reversion"

def atomic_json(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                prefix="."+path.name+".", suffix=".tmp", delete=False) as f:
            tmp = f.name; json.dump(payload, f, indent=2, allow_nan=False)
            f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if tmp and os.path.exists(tmp): os.unlink(tmp)
        raise

def main():
    candles = load_two_year_candles(days=300)
    quality = validate_hourly_feed(candles)
    def convert(rows):
        return [[int(r["timestamp"]//1000), r["open"], r["high"], r["low"], r["close"], r["volume"]] for r in rows]
    seed = seed_forward_paper_account(convert(candles[-200:]), STATE,
        initial_cash=CASH, strategy=STRATEGY)
    result = update_paper_account(convert(candles), state_path=str(STATE),
        initial_cash=CASH, fee_rate=0.001, slippage_rate=0.0005,
        allocation_fraction=COMPOUND_ALLOCATION_FRACTION, max_drawdown_fraction=0.10,
        daily_loss_fraction=0.03, max_consecutive_losses=3,
        strategy=STRATEGY)
    equity = result["equity_after_estimated_exit_costs_usd"]
    status = "RISK_PAUSED" if result["risk_pause_reasons"] else (
        "PAPER_RUNNING" if result["processed_new_candles"] else "PAPER_ACTIVE_WAITING_NEXT_CLOSED_CANDLE")
    btc = {"asset":"BTC","symbol":"BTC/USD","initial_equity_usd":CASH,
        "equity_usd":equity,"pnl_usd":round(equity-CASH,4),
        "return_pct":result["return_pct"],"closed_trades":result["completed_trades"],
        "fees_usd":result["fees_paid_usd"],"max_drawdown_pct":result["max_drawdown_pct"],
        "feed_status":"COINBASE_BTC_USD_HOURLY_HEALTHY","status":status,
        "last_price_usd":float(candles[-1]["close"]),
        "last_processed_timestamp":result["last_processed_timestamp"],
        "open_position":result["open_position"],"btc_units":result["btc_units"],
        "cash_usd":result["cash_usd"],"strategy":STRATEGY,
        "risk_pause_reasons":result["risk_pause_reasons"],"risk_limits":result["risk_limits"],
        "new_trades":result["new_trades"],"warmup_seed_created":seed["created"],
        "processed_new_candles":result["processed_new_candles"],"data_quality":quality,
        "execution_model":"Newly closed hourly candles; 0.10% fee and 0.05% slippage per side; no live orders."}
    gold={"asset":"XAUUSD","symbol":"XAU/USD spot","initial_equity_usd":10.0,
        "equity_usd":10.0,"pnl_usd":0.0,"return_pct":0.0,"closed_trades":0,
        "fees_usd":0.0,"max_drawdown_pct":0.0,"feed_status":"SPOT_FEED_REQUIRED",
        "status":"DISABLED_PENDING_VALIDATED_XAUUSD_BID_ASK_FEED"}
    snapshot={"schema_version":1,"status":"BTC_PAPER_ONLY_GOLD_DISABLED",
        "paper_only":True,"live_trading_enabled":False,
        "compounding_enabled":True,"sizing_mode":"COMPOUND_CURRENT_EQUITY_FRACTION",
        "allocation_fraction":COMPOUND_ALLOCATION_FRACTION,
        "updated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "btc":btc,"gold":gold,"strategies":[{"asset":"BTC","strategy":STRATEGY,
        "equity_usd":equity,"return_pct":result["return_pct"],
        "closed_trades":result["completed_trades"],"fees_usd":result["fees_paid_usd"],
        "max_drawdown_pct":result["max_drawdown_pct"],"status":status}],
        "bull_summary":"RSI14 mean-reversion exploratory paper test; not approved for live use.",
        "bear_summary":"No entry unless a completed candle satisfies the strategy rule.",
        "risk_decision":status+(": "+", ".join(result["risk_pause_reasons"]) if result["risk_pause_reasons"] else ""),
        "notes":["BTC starts with $10 simulated capital; each new entry sizes at 10% of current realized equity (compounding).","Historical candles warm indicators only; no historical trades or PnL are counted.",
        "Gold disabled: indicative spot mid-price is not an executable broker bid/ask feed.",
        "Exploratory strategy; minimum forward sample gate not yet met.","No real orders are sent."]}
    atomic_json("dual_portfolio.json",snapshot)
    print(json.dumps({"status":status,"seed_created":seed["created"],
        "processed_new_candles":result["processed_new_candles"],"equity_usd":equity,
        "closed_trades":result["completed_trades"],"open_position":result["open_position"],
        "risk_pause_reasons":result["risk_pause_reasons"]},indent=2))

if __name__=="__main__": main()
