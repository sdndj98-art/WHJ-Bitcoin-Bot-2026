"""Frequent, forward-only 4h/6h paper monitoring. Never places live orders."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from historical_research import aggregate_candles, load_two_year_candles
from paper_account import seed_forward_paper_account, update_paper_account

STATE_FILES = {
    "4h": "paper_forward_4h_ema50_200.json",
    "6h": "paper_forward_6h_ema50_200.json",
}


def validate_hourly_feed(candles, now_timestamp=None):
    """Reject malformed, impossible, synthetic or stale hourly market data."""
    import math

    if not isinstance(candles, list) or len(candles) < 24:
        raise ValueError("At least 24 hourly candles are required")
    timestamps = []
    required = ("timestamp", "open", "high", "low", "close", "volume")
    for index, row in enumerate(candles):
        if not isinstance(row, dict) or any(key not in row for key in required):
            raise ValueError("Hourly candle is missing required OHLCV fields")
        raw_timestamp = row["timestamp"]
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, float)):
            raise ValueError("Hourly candle timestamp must be numeric")
        if not math.isfinite(raw_timestamp) or not float(raw_timestamp).is_integer():
            raise ValueError("Hourly candle timestamp must be a finite integer")
        timestamp = int(raw_timestamp)
        if timestamp < 0:
            raise ValueError("Hourly candle timestamp cannot be negative")
        timestamps.append(timestamp)
        values = {}
        for key in ("open", "high", "low", "close", "volume"):
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Hourly candle " + key + " must be a finite number")
            values[key] = float(value)
        if any(values[key] <= 0 for key in ("open", "high", "low", "close")):
            raise ValueError("Hourly OHLC prices must be positive")
        if values["volume"] < 0:
            raise ValueError("Hourly candle volume cannot be negative")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError("Hourly candle high is inconsistent with OHLC prices")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError("Hourly candle low is inconsistent with OHLC prices")
        if "imputed" in row and not isinstance(row["imputed"], bool):
            raise ValueError("Hourly candle imputed flag must be boolean")
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Hourly candles must be strictly increasing and unique")
    if any(b - a != 3_600_000 for a, b in zip(timestamps[-25:], timestamps[-24:])):
        raise ValueError("Recent hourly candles contain a gap; paper processing is blocked")
    if any(row.get("imputed", False) for row in candles[-25:]):
        raise ValueError("Recent imputed candles detected; paper processing is blocked")
    now = datetime.now(timezone.utc).timestamp() if now_timestamp is None else float(now_timestamp)
    if not math.isfinite(now):
        raise ValueError("Current timestamp must be finite")
    age_minutes = (now * 1000 - (timestamps[-1] + 3_600_000)) / 60_000
    if not -5 <= age_minutes <= 120:
        raise ValueError("Latest completed hourly candle is stale or in the future")
    return {"quality": "HEALTHY", "latest_closed_candle_age_minutes": round(age_minutes, 2)}


def _account_rows(bars):
    return [[int(row["timestamp"] // 1000), 0, 0, 0, str(row["close"])] for row in bars]


def process_forward_accounts(candles, state_dir=".", now_timestamp=None):
    quality = validate_hourly_feed(candles, now_timestamp)
    directory = Path(state_dir)
    results = {}
    for timeframe, hours in (("4h", 4), ("6h", 6)):
        bars = aggregate_candles(candles, hours)
        rows = _account_rows(bars)
        state_path = directory / STATE_FILES[timeframe]
        seed = seed_forward_paper_account(
            rows, state_path=str(state_path), initial_cash=500.0
        )
        account = update_paper_account(
            rows,
            state_path=str(state_path),
            initial_cash=500.0,
            allocation_fraction=0.10,
            max_drawdown_fraction=0.10,
            daily_loss_fraction=0.03,
            max_consecutive_losses=5,
            strategy="ema50_200_regime",
        )
        results[timeframe] = {"seed": seed, "account": account}

    total_initial = sum(v["account"]["initial_cash_usd"] for v in results.values())
    total_equity = sum(
        v["account"]["equity_after_estimated_exit_costs_usd"]
        for v in results.values()
    )
    if total_initial <= 0 or total_equity <= 0:
        raise ValueError("Paper portfolio equity is invalid; refusing to publish a snapshot")
    summary = {}
    for timeframe, value in results.items():
        account = value["account"]
        summary[timeframe] = {
            "last_processed_timestamp": account["last_processed_timestamp"],
            "processed_new_candles": account["processed_new_candles"],
            "equity_usd": account["equity_after_estimated_exit_costs_usd"],
            "return_pct": account["return_pct"],
            "completed_trades": account["completed_trades"],
            "win_rate_pct": account["win_rate_pct"],
            "profit_factor": account["profit_factor"],
            "max_drawdown_pct": account["max_drawdown_pct"],
            "open_position": account["open_position"],
            "risk_pause_reasons": account["risk_pause_reasons"],
        }
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "FORWARD_ONLY_PAPER_NO_LIVE_ORDERS",
        "status": "RISK_PAUSED" if any(v["risk_pause_reasons"] for v in summary.values()) else "PAPER_MONITORING",
        "market": "BTC/USD",
        "data_quality": quality,
        "latest_hourly_candle_timestamp": candles[-1]["timestamp"],
        "initial_cash_usd": round(total_initial, 2),
        "equity_after_estimated_exit_costs_usd": round(total_equity, 2),
        "return_pct": round((total_equity / total_initial - 1) * 100, 4),
        "completed_trades": sum(v["completed_trades"] for v in summary.values()),
        "sleeves_summary": summary,
        "sleeves": results,
        "risk_limits": {
            "allocation_pct_per_sleeve": 10,
            "max_drawdown_pause_pct": 10,
            "daily_loss_pause_pct": 3,
            "consecutive_loss_pause_count": 5,
        },
        "warning": "Paper simulation only. Historical candles warm up indicators; only bars newer than each saved ledger timestamp are processed. No live orders are possible.",
    }


def main():
    candles = load_two_year_candles(days=90)
    report = process_forward_accounts(candles)
    Path("forward_paper_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FORWARD PAPER MONITOR ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
