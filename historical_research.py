"""Fetch two years of public BTC/USDT hourly candles and run fixed-rule research.

Research only: no credentials, orders, or trading endpoints are used.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_account import update_paper_account
from strategy_lab import run_strategy_lab

BASE_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
INTERVAL_MS = 60 * 60 * 1000
DAYS = 730
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005


def _iso_utc(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(timespec="seconds")


def fetch_page(start_ms, end_ms):
    params = urllib.parse.urlencode({
        "granularity": 3600,
        "start": _iso_utc(start_ms),
        "end": _iso_utc(end_ms),
    })
    request = urllib.request.Request(
        BASE_URL + "?" + params,
        headers={
            "User-Agent": "WHJ-Bitcoin-Bot-Research/1.0",
            "Accept": "application/json",
        },
    )
    last_error = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Coinbase returned an unexpected candle payload")
            # Coinbase format: [time, low, high, open, close, volume].
            rows = []
            for item in payload:
                if not isinstance(item, list) or len(item) < 6:
                    raise ValueError("Malformed Coinbase historical candle")
                rows.append([
                    int(item[0]) * 1000,
                    float(item[3]),
                    float(item[2]),
                    float(item[1]),
                    float(item[4]),
                    float(item[5]),
                ])
            return rows
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError("Unable to download historical candles from Coinbase: " + str(last_error))

def load_two_year_candles(days=DAYS, now=None):
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    start_ms = (now_ms - days * 24 * INTERVAL_MS) // INTERVAL_MS * INTERVAL_MS
    rows = []
    cursor = start_ms
    # Coinbase caps hourly responses at 300 candles. Use 299-hour slices
    # to avoid truncation and keep inclusive boundaries unambiguous.
    while cursor < now_ms:
        page_end = min(cursor + 299 * INTERVAL_MS, now_ms)
        page = fetch_page(cursor, page_end)
        rows.extend(page)
        next_cursor = page_end + INTERVAL_MS
        if next_cursor <= cursor:
            raise ValueError("Historical API pagination did not advance")
        cursor = next_cursor
        time.sleep(0.2)

    if not rows:
        raise ValueError("No historical candles were downloaded")

    unique = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError("Malformed historical candle")
        timestamp = int(row[0])
        values = [float(row[i]) for i in (1, 2, 3, 4, 5)]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite OHLCV value in historical data")
        open_price, high, low, close, volume = values
        if min(open_price, high, low, close) <= 0 or volume < 0:
            raise ValueError("Non-positive OHLC price or negative volume")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Impossible OHLC candle relationship")
        unique[timestamp] = {
            "timestamp": timestamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "imputed": False,
        }

    observed = [unique[key] for key in sorted(unique)]
    # Drop any candle whose one-hour interval has not fully closed.
    cutoff = now_ms - (now_ms % INTERVAL_MS)
    observed = [row for row in observed if row["timestamp"] + INTERVAL_MS <= cutoff]
    if len(observed) < 1000:
        raise ValueError("Insufficient closed hourly candles for multi-regime research")

    # Coinbase may omit intervals with no reported trades. For short gaps only,
    # insert clearly-marked flat candles at the previous close with zero volume.
    # Large gaps are rejected instead of fabricating a long price path.
    candles = []
    imputed_count = 0
    for current in observed:
        if candles:
            previous = candles[-1]
            delta = current["timestamp"] - previous["timestamp"]
            if delta <= 0 or delta % INTERVAL_MS:
                raise ValueError("Historical candle timestamps are not aligned to hourly boundaries")
            missing = delta // INTERVAL_MS - 1
            if missing > 6:
                raise ValueError(
                    "Historical data gap exceeds the six-hour repair limit: "
                    + str({"after": previous["timestamp"], "before": current["timestamp"], "missing_hours": missing})
                )
            for offset in range(1, missing + 1):
                flat = previous["close"]
                candles.append({
                    "timestamp": previous["timestamp"] + offset * INTERVAL_MS,
                    "open": flat,
                    "high": flat,
                    "low": flat,
                    "close": flat,
                    "volume": 0.0,
                    "imputed": True,
                })
                imputed_count += 1
        candles.append(current)

    if len(candles) < 1000:
        raise ValueError("Insufficient hourly candles after data-quality repair")
    # Keep the imputation count available to the report without hiding it in prices.
    candles[0]["_imputed_hour_count"] = imputed_count
    return candles


def aggregate_candles(candles, hours):
    """Aggregate complete UTC-aligned hourly bars without using partial periods."""
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
        raise ValueError("Aggregation hours must be a positive integer")
    span = hours * INTERVAL_MS
    groups = {}
    for row in candles:
        bucket = row["timestamp"] // span
        groups.setdefault(bucket, []).append(row)
    aggregated = []
    for bucket in sorted(groups):
        group = sorted(groups[bucket], key=lambda item: item["timestamp"])
        if len(group) != hours:
            continue
        expected_start = bucket * span
        if group[0]["timestamp"] != expected_start:
            continue
        if any(group[i]["timestamp"] != expected_start + i * INTERVAL_MS
               for i in range(hours)):
            continue
        aggregated.append({
            "timestamp": expected_start,
            "open": group[0]["open"],
            "high": max(item["high"] for item in group),
            "low": min(item["low"] for item in group),
            "close": group[-1]["close"],
            "volume": sum(item["volume"] for item in group),
            "imputed": any(item.get("imputed", False) for item in group),
        })
    if len(aggregated) < 200:
        raise ValueError(f"Not enough complete {hours}-hour bars for strategy comparison")
    return aggregated


def run_forward_paper_accounts(candles, state_dir="."):
    """Maintain independent 1d and 4h paper accounts across daily workflow runs."""
    directory = Path(state_dir)
    daily = aggregate_candles(candles, 24)
    four_hour = aggregate_candles(candles, 4)

    def account_rows(bars):
        return [[int(row["timestamp"] // 1000), 0, 0, 0, str(row["close"])] for row in bars]

    daily_result = update_paper_account(
        account_rows(daily),
        state_path=str(directory / "paper_daily_sma20_50.json"),
        strategy="sma_trend",
    )
    four_hour_result = update_paper_account(
        account_rows(four_hour),
        state_path=str(directory / "paper_4h_ema50_200.json"),
        strategy="ema50_200_regime",
    )
    return {
        "mode": "PERSISTENT_MULTI_TIMEFRAME_PAPER_ONLY",
        "daily_sma20_50": daily_result,
        "four_hour_ema50_200": four_hour_result,
        "note": "These accounts process only newly closed aggregated bars and persist state between scheduled runs. No real orders are sent.",
    }


def main():
    candles = load_two_year_candles()
    prices = [row["close"] for row in candles]
    research = run_strategy_lab(prices, fee=FEE_RATE, slippage=SLIPPAGE_RATE)
    timeframe_research = {}
    for label, hours in (("1h", 1), ("4h", 4), ("6h", 6), ("1d", 24)):
        bars = candles if hours == 1 else aggregate_candles(candles, hours)
        timeframe_research[label] = {
            "bar_count": len(bars),
            "first_bar_utc": datetime.fromtimestamp(bars[0]["timestamp"] / 1000, timezone.utc).isoformat(),
            "last_bar_utc": datetime.fromtimestamp(bars[-1]["timestamp"] / 1000, timezone.utc).isoformat(),
            "imputed_bar_count": sum(1 for bar in bars if bar.get("imputed", False)),
            "research": run_strategy_lab(
                [bar["close"] for bar in bars],
                fee=FEE_RATE,
                slippage=SLIPPAGE_RATE,
            ),
        }
    stress_cost_research = {}
    for label in ("4h", "1d"):
        hours = 4 if label == "4h" else 24
        aggregated = aggregate_candles(candles, hours)
        stress_cost_research[label] = run_strategy_lab(
            [bar["close"] for bar in aggregated],
            fee=0.002,
            slippage=0.001,
        )

    forward_paper = run_forward_paper_accounts(candles)
    result = {
        "project": "WHJ Bitcoin Bot",
        "mode": "TWO_YEAR_HISTORICAL_RESEARCH_ONLY",
        "source": "Coinbase Exchange public BTC-USD candles",
        "interval": "1h",
        "requested_days": DAYS,
        "actual_days": round((candles[-1]["timestamp"] - candles[0]["timestamp"]) / 86400000, 2),
        "candles": len(candles),
        "first_closed_candle_utc": datetime.fromtimestamp(candles[0]["timestamp"] / 1000, timezone.utc).isoformat(),
        "last_closed_candle_utc": datetime.fromtimestamp(candles[-1]["timestamp"] / 1000, timezone.utc).isoformat(),
        "fees": {"entry_and_exit_rate": FEE_RATE, "slippage_each_side": SLIPPAGE_RATE},
        "data_quality": {
            "hourly_intervals_contiguous_after_repair": True,
            "imputed_missing_hour_count": candles[0].get("_imputed_hour_count", 0),
            "imputation_method": "Forward-filled prior close with zero volume for gaps of at most six hours; larger gaps are rejected.",
            "ohlcv_validated": True,
        },
        "research": research,
        "timeframe_research": timeframe_research,
        "stress_cost_research": stress_cost_research,
        "forward_paper_accounts": forward_paper,
        "warning": "Historical results are not forecasts. Strategy selection requires robust out-of-sample performance and forward paper trading. No live orders were placed.",
    }
    Path("historical_research.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = {
        "source": result["source"],
        "candles": result["candles"],
        "first": result["first_closed_candle_utc"],
        "last": result["last_closed_candle_utc"],
        "forward_paper_accounts": {
            name: {
                "return_pct": account["return_pct"],
                "equity_usd": account["equity_after_estimated_exit_costs_usd"],
                "completed_trades": account["completed_trades"],
                "win_rate_pct": account["win_rate_pct"],
                "max_drawdown_pct": account["max_drawdown_pct"],
                "processed_new_candles": account["processed_new_candles"],
            }
            for name, account in (
                ("daily_sma20_50", forward_paper["daily_sma20_50"]),
                ("four_hour_ema50_200", forward_paper["four_hour_ema50_200"]),
            )
        },
        "strategies": {
            name: {
                "oos_return_pct": metrics["out_of_sample"]["return_pct"],
                "oos_max_drawdown_pct": metrics["out_of_sample"]["max_drawdown_pct"],
                "oos_profit_factor": metrics["out_of_sample"]["profit_factor"],
                "oos_trades": metrics["out_of_sample"]["closed_trades"],
                "worst_window_return_pct": metrics.get("worst_window_return_pct"),
                "window_returns_pct": [
                    item["metrics"]["return_pct"] for item in metrics.get("walk_forward_windows", [])
                ],
            }
            for name, metrics in research["strategies"].items()
        },
    }
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
