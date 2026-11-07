"""WHJ Bitcoin Bot: read-only market analysis and historical paper simulation.

This program NEVER places real orders and does not require exchange credentials.
"""
import json
import math
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from paper_trading import run_backtest
from paper_account import update_paper_account
from strategy_lab import run_strategy_lab

API = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60"
REPORT_PATH = Path("report.json")
USER_AGENT = "WHJ-Bitcoin-Bot/1.2"


def fetch_closed_candles():
    request = urllib.request.Request(API, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("Kraken API error: " + ", ".join(map(str, errors)))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Kraken response is missing result data")
    pair_key = next((key for key in result if key != "last"), None)
    if pair_key is None:
        raise ValueError("Kraken response contains no BTC/USD candles")
    candles = result[pair_key]
    if not isinstance(candles, list) or len(candles) < 52:
        raise ValueError("Not enough hourly candles; at least 52 are required to retain 51 closed candles")
    closed_candles = candles[:-1]
    timestamps = []
    for candle in closed_candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 5:
            raise ValueError("Market data contains a malformed OHLC candle")
        try:
            timestamp, close = int(candle[0]), float(candle[4])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Market data contains an invalid timestamp or close") from exc
        if timestamp < 0 or not math.isfinite(close) or close <= 0:
            raise ValueError("Market data contains an invalid timestamp or close")
        timestamps.append(timestamp)
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Market candle timestamps are duplicated or out of order")
    return closed_candles


def fetch_closes():
    """Compatibility helper returning only completed hourly close prices."""
    return [float(candle[4]) for candle in fetch_closed_candles()]

def analyze(prices):
    if len(prices) < 51:
        raise ValueError("At least 51 closed prices are required")
    if any(isinstance(p, bool) or not isinstance(p, (int, float))
           or not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError("Prices must be finite positive numbers")

    sma20 = sum(prices[-20:]) / 20
    sma50 = sum(prices[-50:]) / 50
    price = float(prices[-1])

    if price > sma20 > sma50:
        signal = "BUY"
    elif price < sma20 < sma50:
        signal = "SELL"
    else:
        signal = "HOLD"

    strategy_lab = (run_strategy_lab(prices) if len(prices) >= 120 else {
        "mode": "INSUFFICIENT_DATA",
        "sample_count": len(prices),
        "required_prices": 120,
        "strategies": {},
        "message": "Strategy holdout comparison requires at least 120 closed candles."
    })

    return {
        "project": "WHJ Bitcoin Bot",
        "mode": "ANALYSIS_AND_HISTORICAL_PAPER_ONLY",
        "time": datetime.now(timezone.utc).isoformat(),
        "market": "BTC/USD",
        "interval": "1h",
        "closed_candles_used": len(prices),
        "BTC_price": round(price, 2),
        "SMA20": round(sma20, 2),
        "SMA50": round(sma50, 2),
        "signal": signal,
        "paper_backtest": run_backtest(prices),
        "strategy_lab": strategy_lab,
        "disclaimer": "Historical simulation is not a forecast or financial advice. No real orders were placed."
    }


def main():
    candles = fetch_closed_candles()
    closes = [float(candle[4]) for candle in candles]
    report = analyze(closes)
    report["persistent_paper_account"] = update_paper_account(candles)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("WHJ ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
