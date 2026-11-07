"""WHJ Bitcoin Bot: read-only market analysis and historical paper simulation.

This program NEVER places real orders and does not require exchange credentials.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from paper_trading import run_backtest

API = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60"
REPORT_PATH = Path("report.json")
USER_AGENT = "WHJ-Bitcoin-Bot/1.2"


def fetch_closes():
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
    if not isinstance(candles, list) or len(candles) < 51:
        raise ValueError("Not enough hourly candles; at least 51 are required")

    # Kraken's final OHLC candle is the currently-forming hour. Exclude it.
    closed_candles = candles[:-1]
    closes = [float(candle[4]) for candle in closed_candles]
    if any(price <= 0 for price in closes):
        raise ValueError("Market data contains a non-positive close price")
    return closes


def analyze(prices):
    if len(prices) < 50:
        raise ValueError("At least 50 closed prices are required")
    if any(not isinstance(p, (int, float)) or p <= 0 for p in prices):
        raise ValueError("Prices must be positive numbers")

    sma20 = sum(prices[-20:]) / 20
    sma50 = sum(prices[-50:]) / 50
    price = float(prices[-1])

    if price > sma20 > sma50:
        signal = "BUY"
    elif price < sma20 < sma50:
        signal = "SELL"
    else:
        signal = "HOLD"

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
        "disclaimer": "Historical simulation is not a forecast or financial advice. No real orders were placed."
    }


def main():
    report = analyze(fetch_closes())
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("WHJ ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
