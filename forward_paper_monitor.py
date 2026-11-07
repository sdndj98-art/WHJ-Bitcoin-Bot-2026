"""Hourly, forward-only multi-timeframe paper monitoring. Never places live orders."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from historical_research import aggregate_candles, load_two_year_candles
from paper_account import seed_forward_paper_account, update_paper_account

STATE_FILES = {
    "1h_sma_trend": "paper_forward_1h_sma_trend.json",
    "1h_ema_trend": "paper_forward_1h_ema_trend.json",
    "1h_rsi14_mean_reversion": "paper_forward_1h_rsi14_mean_reversion.json",
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
        if timestamp % 3_600_000 != 0:
            raise ValueError("Hourly candle timestamps must align to UTC hour boundaries")
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
    imputed_count = sum(1 for row in candles if row.get("imputed", False))
    total_count = len(candles)
    return {
        "quality": "HEALTHY",
        "latest_closed_candle_age_minutes": round(age_minutes, 2),
        "total_hourly_candles": total_count,
        "observed_hourly_candles": total_count - imputed_count,
        "imputed_hourly_candles": imputed_count,
        "imputed_hourly_pct": round(imputed_count / total_count * 100.0, 4),
    }



def assess_sleeve_health(account, min_closed_trades=30, review_drawdown_pct=8.0):
    """Assess lifetime risk and the latest 20 closed trades; paper review only."""
    import math
    if isinstance(min_closed_trades, bool) or not isinstance(min_closed_trades, int) or min_closed_trades < 1:
        raise ValueError("Minimum closed trade threshold must be a positive integer")
    if isinstance(review_drawdown_pct, bool) or not isinstance(review_drawdown_pct, (int, float)) or not math.isfinite(review_drawdown_pct) or not 0 < review_drawdown_pct <= 100:
        raise ValueError("Review drawdown threshold must be between 0 and 100")
    if not isinstance(account, dict):
        raise ValueError("Paper account health input must be an object")
    trades = account.get("completed_trades")
    drawdown = account.get("max_drawdown_pct")
    profit_factor = account.get("profit_factor")
    returns = account.get("return_pct")
    if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
        raise ValueError("Completed trade count is invalid")
    for name, value in (("max drawdown", drawdown), ("return", returns)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(name + " metric is invalid")
    if profit_factor is not None and (
        isinstance(profit_factor, bool)
        or not isinstance(profit_factor, (int, float))
        or not math.isfinite(profit_factor)
        or profit_factor < 0
    ):
        raise ValueError("Profit factor metric is invalid")
    pause_reasons = account.get("risk_pause_reasons", [])
    if not isinstance(pause_reasons, list) or any(not isinstance(x, str) for x in pause_reasons):
        raise ValueError("Risk pause reasons are invalid")

    recent = account.get("recent_trades", [])
    if not isinstance(recent, list) or len(recent) > 20:
        raise ValueError("Recent trade window is invalid")
    pnl_values = []
    for trade in recent:
        if not isinstance(trade, dict):
            raise ValueError("Recent trade record is invalid")
        pnl = trade.get("pnl_usd")
        if isinstance(pnl, bool) or not isinstance(pnl, (int, float)) or not math.isfinite(pnl):
            raise ValueError("Recent trade PnL must be finite")
        pnl_values.append(float(pnl))
    rolling_count = len(pnl_values)
    rolling_profit = sum(value for value in pnl_values if value > 0)
    rolling_loss = -sum(value for value in pnl_values if value < 0)
    rolling_pf = (
        round(rolling_profit / rolling_loss, 4) if rolling_loss > 0
        else (None if rolling_profit > 0 else 0.0)
    )
    rolling_net = round(sum(pnl_values), 4)
    initial_cash = account.get("initial_cash_usd")
    if initial_cash is not None and (
        isinstance(initial_cash, bool)
        or not isinstance(initial_cash, (int, float))
        or not math.isfinite(initial_cash)
        or initial_cash <= 0
    ):
        raise ValueError("Initial paper capital for rolling drawdown is invalid")
    rolling_max_drawdown_pct = None
    if initial_cash is not None and pnl_values:
        cumulative_pnl = 0.0
        peak_cumulative_pnl = 0.0
        worst_peak_to_trough = 0.0
        for pnl in pnl_values:
            cumulative_pnl += pnl
            peak_cumulative_pnl = max(peak_cumulative_pnl, cumulative_pnl)
            worst_peak_to_trough = max(
                worst_peak_to_trough, peak_cumulative_pnl - cumulative_pnl
            )
        rolling_max_drawdown_pct = round(
            worst_peak_to_trough / float(initial_cash) * 100.0, 4
        )
    rolling_status = "INSUFFICIENT_ROLLING_SAMPLE"
    if rolling_count >= 10:
        rolling_status = (
            "ROLLING_REVIEW_REQUIRED"
            if (
                rolling_net <= 0
                or (rolling_pf is not None and rolling_pf < 1.0)
                or (
                    rolling_max_drawdown_pct is not None
                    and rolling_max_drawdown_pct >= review_drawdown_pct
                )
            )
            else "ROLLING_STABLE"
        )

    if pause_reasons:
        status = "RISK_PAUSED"
        reason = "Risk controls have paused this paper sleeve"
    elif trades < min_closed_trades:
        status = "INSUFFICIENT_FORWARD_SAMPLE"
        reason = "Not enough genuinely forward-closed trades to judge performance"
    elif (
        drawdown >= review_drawdown_pct
        or returns <= 0
        or profit_factor is None
        or profit_factor < 1
        or rolling_status == "ROLLING_REVIEW_REQUIRED"
    ):
        status = "REVIEW_REQUIRED"
        reason = (
            "The latest rolling trade window has deteriorated"
            if rolling_status == "ROLLING_REVIEW_REQUIRED"
            else "Forward results breached a conservative performance review threshold"
        )
    else:
        status = "CONTINUE_PAPER_REVIEW"
        reason = "Forward and rolling metrics pass the review screen; continue paper testing only"
    return {
        "status": status,
        "reason": reason,
        "rolling_window_trades": rolling_count,
        "rolling_net_pnl_usd": rolling_net,
        "rolling_profit_factor": rolling_pf,
        "rolling_max_drawdown_pct": rolling_max_drawdown_pct,
        "rolling_status": rolling_status,
        "minimum_closed_trades": min_closed_trades,
        "review_drawdown_threshold_pct": review_drawdown_pct,
        "live_trading_eligible": False,
    }


def _account_rows(bars):
    return [[int(row["timestamp"] // 1000), 0, 0, 0, str(row["close"])] for row in bars]


def process_forward_accounts(candles, state_dir=".", now_timestamp=None):
    quality = validate_hourly_feed(candles, now_timestamp)
    directory = Path(state_dir)
    results = {}
    configurations = (
        ("1h_sma_trend", 1, "sma_trend", 200.0),
        ("1h_ema_trend", 1, "ema_trend", 200.0),
        ("1h_rsi14_mean_reversion", 1, "rsi14_mean_reversion", 200.0),
        ("4h", 4, "ema50_200_regime", 500.0),
        ("6h", 6, "ema50_200_regime", 500.0),
    )
    for sleeve, hours, strategy, initial_cash in configurations:
        bars = candles if hours == 1 else aggregate_candles(candles, hours)
        rows = _account_rows(bars)
        state_path = directory / STATE_FILES[sleeve]
        seed = seed_forward_paper_account(
            rows, state_path=str(state_path), initial_cash=initial_cash,
            strategy=strategy,
        )
        account = update_paper_account(
            rows,
            state_path=str(state_path),
            initial_cash=initial_cash,
            allocation_fraction=0.10,
            max_drawdown_fraction=0.10,
            daily_loss_fraction=0.03,
            max_consecutive_losses=5,
            strategy=strategy,
            strategy_health_pause=True,
            strategy_health_drawdown_fraction=0.08,
        )
        results[sleeve] = {"seed": seed, "account": account}

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
            "cash_usd": account["cash_usd"],
            "btc_units": account["btc_units"],
            "exposure_usd": round(account["btc_units"] * candles[-1]["close"], 2),
            "exposure_pct_of_equity": round(
                account["btc_units"] * candles[-1]["close"]
                / account["equity_after_estimated_exit_costs_usd"] * 100.0, 4
            ),
            "fees_paid_usd": account["fees_paid_usd"],
            "current_consecutive_losses": account["current_consecutive_losses"],
            "return_pct": account["return_pct"],
            "completed_trades": account["completed_trades"],
            "win_rate_pct": account["win_rate_pct"],
            "profit_factor": account["profit_factor"],
            "max_drawdown_pct": account["max_drawdown_pct"],
            "open_position": account["open_position"],
            "risk_pause_reasons": account["risk_pause_reasons"],
            "health_assessment": assess_sleeve_health(account),
        }
    total_processed_new_candles = sum(
        item["processed_new_candles"] for item in summary.values()
    )
    total_cash = sum(item["cash_usd"] for item in summary.values())
    total_btc = sum(item["btc_units"] for item in summary.values())
    total_exposure = sum(item["exposure_usd"] for item in summary.values())
    total_fees = sum(item["fees_paid_usd"] for item in summary.values())
    open_positions = sum(1 for item in summary.values() if item["open_position"])
    cycle_status = (
        "PROCESSED_NEW_CANDLES"
        if total_processed_new_candles > 0
        else "WAITING_FOR_NEW_CLOSED_CANDLES"
    )
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "FORWARD_ONLY_PAPER_NO_LIVE_ORDERS",
        "status": (
            "RISK_PAUSED" if any(v["health_assessment"]["status"] == "RISK_PAUSED" for v in summary.values())
            else "REVIEW_REQUIRED" if any(v["health_assessment"]["status"] == "REVIEW_REQUIRED" for v in summary.values())
            else "PAPER_MONITORING"
        ),
        "cycle_status": cycle_status,
        "total_processed_new_candles": total_processed_new_candles,
        "market": "BTC/USD",
        "data_quality": quality,
        "latest_hourly_candle_timestamp": candles[-1]["timestamp"],
        "initial_cash_usd": round(total_initial, 2),
        "equity_after_estimated_exit_costs_usd": round(total_equity, 2),
        "cash_usd": round(total_cash, 2),
        "btc_units": round(total_btc, 8),
        "gross_exposure_usd": round(total_exposure, 2),
        "gross_exposure_pct_of_equity": round(total_exposure / total_equity * 100.0, 4),
        "fees_paid_usd": round(total_fees, 4),
        "open_positions": open_positions,
        "return_pct": round((total_equity / total_initial - 1) * 100, 4),
        "completed_trades": sum(v["completed_trades"] for v in summary.values()),
        "sleeves_summary": summary,
        "sleeves": results,
        "risk_limits": {
            "allocation_pct_per_sleeve": 10,
            "max_drawdown_pause_pct": 10,
            "daily_loss_pause_pct": 3,
            "consecutive_loss_pause_count": 5,
            "rolling_review_pause_pct": 8,
        },
        "warning": "Paper simulation only. Historical candles warm up indicators; only bars newer than each saved ledger timestamp are processed. No live orders are possible.",
    }


def write_report_atomically(report, output_path="forward_paper_report.json"):
    """Write a complete JSON snapshot and atomically replace the previous report."""
    if not isinstance(report, dict):
        raise ValueError("Forward paper report must be an object")
    target = Path(output_path)
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
            json.dump(report, temporary, indent=2, allow_nan=False)
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
    return target


def main():
    candles = load_two_year_candles(days=90)
    report = process_forward_accounts(candles)
    write_report_atomically(report)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FORWARD PAPER MONITOR ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
