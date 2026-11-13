"""Single-account BTC forward paper runner for the $10 dashboard portfolio.

No exchange credentials or order endpoints. Historical candles only warm indicators;
only candles newer than the persisted seed timestamp can create simulated trades.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from historical_research import load_two_year_candles
from forward_paper_monitor import validate_hourly_feed
from paper_account import seed_forward_paper_account, update_paper_account

STATE_PATH = Path("state/btc_10usd_rsi14_mean_reversion.json")
SNAPSHOT_PATH = Path("dual_portfolio.json")
INITIAL_CASH = 10.0
STRATEGY = "rsi14_mean_reversion"
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005
ALLOCATION = 0.10


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                                         prefix="." + path.name + ".", suffix=".tmp",
                                         delete=False) as handle:
            temp_name = handle.name
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
        raise


def main():
    candles = load_two_year_candles(days=300)
    quality = validate_hourly_feed(candles)
    # Existing account state is never reset. A first run seeds only the latest
    # 200 completed bars, so historical prices cannot be counted as paper trades.
    warmup = candles[-200:]
    warmup_rows = [
        [int(row["timestamp"] // 1000), row["open"], row["high"],
         row["low"], row["close"], row["volume"]]
        for row in warmup
    ]
    seed = seed_forward_paper_account(
        warmup_rows, STATE_PATH, initial_cash=INITIAL_CASH, strategy=STRATEGY
    )
    rows = [
        [int(row["timestamp"] // 1000), row["open"], row["high"],
         row["low"], row["close"], row["volume"]]
        for row in candles
    ]
    account = update_paper_account(
        rows,
        state_path=str(STATE_PATH),
        initial_cash=INITIAL_CASH,
        fee_rate=FEE_RATE,
        slippage_rate=SLIPPAGE_RATE,
        allocation_fraction=ALLOCATION,
        max_drawdown_fraction=0.10,
        daily_loss_fraction=0.03,
        max_consecutive_losses=3,
        strategy=STRATEGY,
        strategy_health_pause=False,
    )
    price = float(candles[-1]["close"])
    status = "PAPER_RUNNING" if account["processed_new_candles"] else "PAPER_ACTIVE_WAITING_NEXT_CLOSED_CANDLE"
    if account["risk_pause_reasons"]:
        status = "RISK_PAUSED"
    btc = {
        "asset": "BTC",
        "symbol": "BTC/USD",
        "initial_equity_usd": INITIAL_CASH,
        "equity_usd": account["equity_after_estimated_exit_costs_usd"],
        "pnl_usd": round(account["equity_after_estimated_exit_costs_usd"] - INITIAL_CASH, 4),
        "return_pct": account["return_pct"],
        "closed_trades": account["completed_trades"],
        "fees_usd": account["fees_paid_usd"],
        "max_drawdown_pct": account["max_drawdown_pct"],
        "feed_status": "COINBASE_BTC_USD_HOURLY_HEALTHY",
        "status": status,
        "last_price_usd": price,
        "last_processed_timestamp": account["last_processed_timestamp"],
        "open_position": account["open_position"],
        "btc_units": account["btc_units"],
        "cash_usd": account["cash_usd"],
        "strategy": STRATEGY,
        "risk_pause_reasons": account["risk_pause_reasons"],
        "risk_limits": account["risk_limits"],
        "new_trades": account["new_trades"],
        "warmup_seed_created": seed["created"],
        "processed_new_candles": account["processed_new_candles"],
        "data_quality": quality,
        "execution_model": "Next newly closed hourly candle; 0.10% fee and 0.05% slippage per side; no live orders.",
    }
    snapshot = {
        "schema_version": 1,
        "status": "BTC_PAPER_ONLY_GOLD_DISABLED",
        "paper_only": True,
        "live_trading_enabled": False,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "btc": btc,
        "gold": {
            "asset": "XAUUSD",
            "symbol": "XAU/USD spot",
            "initial_equity_usd": 10.0,
            "equity_usd": 10.0,
            "pnl_usd": 0.0,
            "return_pct": 0.0,
            "closed_trades": 0,
            "fees_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "feed_status": "SPOT_FEED_REQUIRED",
            "status": "DISABLED_PENDING_VALIDATED_XAUUSD_BID_ASK_FEED",
        },
        "strategies": [{
            "asset": "BTC",
            "strategy": STRATEGY,
            "equity_usd": btc["equity_usd"],
            "return_pct": btc["return_pct"],
            "closed_trades": btc["closed_trades"],
            "fees_usd": btc["fees_usd"],
            "max_drawdown_pct": btc["max_drawdown_pct"],
            "status": status,
        }],
        "bull_summary": "RSI14 mean-reversion exploratory paper sleeve; not historically approved for live use.",
        "bear_summary": "No entry unless the strategy rule is satisfied on a completed candle.",
        "risk_decision": status + (": " + ", ".join(account["risk_pause_reasons"]) if account["risk_pause_reasons"] else ""),
        "notes": [
            "BTC paper ledger starts with exactly $10.00 simulated cash.",
            "Historical candles warm indicators only; they never create trades or profit.",
            "Gold remains disabled because an indicative spot mid-price is not an executable broker bid/ask feed.",
            "This strategy is exploratory and has not passed the minimum forward sample gate.",
            "No real orders are sent; paper trading does not guarantee future results.",
        ],
    }
    atomic_json(SNAPSHOT_PATH, snapshot)
    print(json.dumps({
        "status": status,
        "seed_created": seed["created"],
        "processed_new_candles": account["processed_new_candles"],
        "equity_usd": btc["equity_usd"],
        "closed_trades": btc["closed_trades"],
        "open_position": btc["open_position"],
        "risk_pause_reasons": btc["risk_pause_reasons"],
        "snapshot": str(SNAPSHOT_PATH),
    }, indent=2))


if __name__ == "__main__":
    main()
