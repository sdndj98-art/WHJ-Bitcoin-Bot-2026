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
from paper_account import run_paper_portfolio
from strategy_lab import run_strategy_lab
from risk_analysis import block_bootstrap_trade_risk, monte_carlo_trade_risk
from market_scanner import scan_btc_market, scan_btc_multi_timeframe
from harmonic_supply_demand import analyze_harmonic_supply_demand

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
        if not isinstance(candle, (list, tuple)) or len(candle) < 8:
            raise ValueError("Market data contains a malformed OHLCV candle")
        try:
            if isinstance(candle[0], bool) or any(
                isinstance(candle[index], bool) for index in (1, 2, 3, 4, 6, 7)
            ):
                raise ValueError("Boolean candle fields are not valid market data")
            raw_timestamp = float(candle[0])
            if not math.isfinite(raw_timestamp) or not raw_timestamp.is_integer():
                raise ValueError("Candle timestamp must be a finite whole number")
            timestamp = int(raw_timestamp)
            open_price, high, low, close = (float(candle[index]) for index in (1, 2, 3, 4))
            volume = float(candle[6])
            raw_trade_count = float(candle[7])
            if not math.isfinite(raw_trade_count) or not raw_trade_count.is_integer():
                raise ValueError("Candle trade count must be a finite whole number")
            trade_count = int(raw_trade_count)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Market data contains invalid OHLCV fields") from exc
        numeric = (open_price, high, low, close, volume)
        if timestamp < 0 or any(not math.isfinite(value) for value in numeric):
            raise ValueError("Market data contains non-finite OHLCV values")
        if min(open_price, high, low, close) <= 0 or volume < 0 or trade_count < 0:
            raise ValueError("Market data contains non-positive prices or negative activity")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Market data contains inconsistent OHLC bounds")
        timestamps.append(timestamp)
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Market candle timestamps are duplicated or out of order")
    if any((current - previous) % 3600 for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("Hourly candle timestamps are not aligned to whole-hour intervals")
    return closed_candles


def fetch_closes():
    """Compatibility helper returning only completed hourly close prices."""
    return [float(candle[4]) for candle in fetch_closed_candles()]


def assess_candle_quality(candles, now_timestamp=None):
    """Report hourly gaps and freshness; block paper execution on recent bad data."""
    if not candles:
        raise ValueError("Cannot assess an empty candle series")
    timestamps = []
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 8:
            raise ValueError("Candle quality check requires complete OHLCV rows")
        if isinstance(candle[0], bool):
            raise ValueError("Candle timestamps cannot be boolean values")
        raw_timestamp = float(candle[0])
        if not math.isfinite(raw_timestamp) or not raw_timestamp.is_integer():
            raise ValueError("Candle timestamps must be finite whole seconds")
        timestamps.append(int(raw_timestamp))
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("Candle timestamps must be strictly increasing")
    gaps_total = 0
    recent_gaps = 0
    recent_start = max(0, len(timestamps) - 51)
    for index, (previous, current) in enumerate(zip(timestamps, timestamps[1:])):
        delta = current - previous
        if delta % 3600:
            raise ValueError("Hourly candle intervals must be exact multiples of 3600 seconds")
        if delta > 3600:
            missing = delta // 3600 - 1
            gaps_total += missing
            if index >= recent_start:
                recent_gaps += missing
    now = datetime.now(timezone.utc).timestamp() if now_timestamp is None else float(now_timestamp)
    if not math.isfinite(now):
        raise ValueError("Current timestamp must be finite")
    age_minutes = (now - (timestamps[-1] + 3600)) / 60
    fresh = -1 <= age_minutes <= 120
    reasons = []
    if recent_gaps:
        reasons.append("recent_hourly_gaps")
    if not fresh:
        reasons.append("stale_or_future_candle")
    return {
        "candle_count": len(candles),
        "missing_hour_gaps_total": gaps_total,
        "recent_missing_hour_gaps": recent_gaps,
        "latest_closed_candle_age_minutes": round(age_minutes, 2),
        "latest_candle_fresh": fresh,
        "quality_status": "HEALTHY" if not reasons else "BLOCKED",
        "quality_block_reasons": reasons,
        "paper_execution_allowed": not reasons,
    }


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

    backtest = run_backtest(prices)
    risk_diagnostics = monte_carlo_trade_risk(backtest["trade_log"])
    block_risk_diagnostics = block_bootstrap_trade_risk(backtest["trade_log"])

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
        "paper_backtest": backtest,
        "monte_carlo_risk": risk_diagnostics,
        "block_bootstrap_risk": block_risk_diagnostics,
        "strategy_lab": strategy_lab,
        "disclaimer": "Historical simulation is not a forecast or financial advice. No real orders were placed."
    }


def main():
    candles = fetch_closed_candles()
    closes = [float(candle[4]) for candle in candles]
    report = analyze(closes)
    quality = assess_candle_quality(candles)
    report["market_data_quality"] = quality
    report["market_scanner"] = scan_btc_market(candles, quality)
    report["market_scanner_multi_timeframe"] = scan_btc_multi_timeframe(candles, quality)
    report["harmonic_supply_demand_divergence"] = analyze_harmonic_supply_demand(candles)
    if quality["paper_execution_allowed"]:
        portfolio = run_paper_portfolio(candles)
        report["persistent_paper_account"] = portfolio["accounts"]["sma_trend"]
    else:
        portfolio = {
            "mode": "PAUSED_DATA_QUALITY",
            "accounts": {},
            "message": "Paper entries are paused because recent candle gaps or stale data were detected.",
        }
        report["persistent_paper_account"] = {}
    report["persistent_paper_portfolio"] = portfolio
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("WHJ ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
