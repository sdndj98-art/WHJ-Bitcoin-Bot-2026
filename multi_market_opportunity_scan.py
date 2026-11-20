"""Read-only, multi-market crypto and metals opportunity scanner.

Scans active Kraken spot pairs quoted in USD/USDT/USDC and tries supported
Biquote metal symbols. Uses completed hourly candles and the existing WHJ
confluence + advanced market analysis. It never changes paper ledgers or places
orders. Missing or stale markets are recorded as unavailable, not guessed.
"""
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_scanner import scan_btc_market

KRAKEN_API = "https://api.kraken.com/0/public"
QUOTE_CURRENCIES = {"USD", "USDT", "USDC"}
METALS = ("XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD")
INTERVAL_SECONDS = 3600
OUTPUT_DIR = Path("research/multi_market_scan")
USER_AGENT = "WHJ-MultiMarket-PaperScanner/1.0"


def fetch_json(url, timeout=25):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("Market provider returned HTTP " + str(response.status))
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Market provider response is not a JSON object")
    errors = payload.get("error", [])
    if errors:
        raise ValueError("Market provider error: " + "; ".join(str(x) for x in errors))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Market provider result is missing")
    return result


def finite(value, label):
    if isinstance(value, bool):
        raise ValueError(label + " must be finite numeric data")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + " must be finite numeric data") from exc
    if not math.isfinite(number):
        raise ValueError(label + " must be finite numeric data")
    return number


def discover_kraken_universe():
    pairs = fetch_json(KRAKEN_API + "/AssetPairs")
    universe = []
    for pair_key, item in pairs.items():
        if not isinstance(item, dict) or item.get("status") != "online":
            continue
        wsname = item.get("wsname")
        altname = item.get("altname")
        if not isinstance(wsname, str) or "/" not in wsname:
            continue
        base, quote = wsname.split("/", 1)
        if quote not in QUOTE_CURRENCIES:
            continue
        if not isinstance(altname, str) or not altname:
            altname = pair_key
        # Exclude leveraged token wrappers; scan ordinary spot pairs only.
        if base.upper().startswith(("2L", "2S", "3L", "3S")):
            continue
        universe.append({
            "pair_key": pair_key,
            "altname": altname,
            "symbol": wsname,
            "base": base,
            "quote": quote,
        })
    if not universe:
        raise ValueError("No active Kraken USD/USDT/USDC spot pairs were discovered")
    return universe


def rank_kraken_pairs(universe):
    tickers = fetch_json(KRAKEN_API + "/Ticker")
    ranked = []
    missing = []
    for pair in universe:
        ticker = tickers.get(pair["pair_key"]) or tickers.get(pair["altname"])
        if not isinstance(ticker, dict):
            missing.append(pair["symbol"])
            continue
        try:
            base_volume_24h = finite(ticker["v"][1], "24-hour volume")
            last_price = finite(ticker["c"][0], "last price")
        except (KeyError, IndexError, TypeError, ValueError):
            missing.append(pair["symbol"])
            continue
        if base_volume_24h <= 0 or last_price <= 0:
            continue
        pair = dict(pair)
        pair["last_price"] = last_price
        pair["quote_volume_24h_estimate"] = base_volume_24h * last_price
        ranked.append(pair)
    ranked.sort(key=lambda item: item["quote_volume_24h_estimate"], reverse=True)
    return ranked, missing


def normalize_kraken_ohlc(payload, now_seconds):
    if not isinstance(payload, dict):
        raise ValueError("Kraken OHLC payload is malformed")
    rows = []
    for row in payload.get("rows", []):
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            continue
        timestamp = finite(row[0], "candle timestamp")
        if not timestamp.is_integer() or int(timestamp) % INTERVAL_SECONDS:
            raise ValueError("Kraken hourly candle timestamp is invalid")
        values = [finite(row[index], "OHLCV field") for index in (1, 2, 3, 4, 6, 7)]
        open_price, high, low, close, volume, trades = values
        if min(open_price, high, low, close) <= 0 or volume < 0 or trades < 0:
            raise ValueError("Kraken OHLCV contains an invalid value")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Kraken OHLC bounds are inconsistent")
        # Kraken includes the currently forming candle as the final row.
        if int(timestamp) + INTERVAL_SECONDS > int(now_seconds // INTERVAL_SECONDS) * INTERVAL_SECONDS:
            continue
        rows.append([
            int(timestamp), open_price, high, low, close,
            finite(row[5], "VWAP"), volume, int(trades),
        ])
    rows.sort(key=lambda row: row[0])
    unique = {row[0]: row for row in rows}
    rows = [unique[key] for key in sorted(unique)]
    if len(rows) < 51:
        raise ValueError("Fewer than 51 completed hourly candles")
    recent = rows[-51:]
    if any(b[0] - a[0] != INTERVAL_SECONDS for a, b in zip(recent, recent[1:])):
        raise ValueError("Recent crypto candles contain a missing hourly interval")
    age_minutes = (now_seconds - (rows[-1][0] + INTERVAL_SECONDS)) / 60.0
    if not -5 <= age_minutes <= 120:
        raise ValueError("Latest completed crypto candle is stale or future-dated")
    return rows, {
        "quality_status": "HEALTHY",
        "paper_execution_allowed": True,
        "latest_closed_candle_age_minutes": round(age_minutes, 2),
        "completed_hourly_candles": len(rows),
        "recent_51_hour_gap_free": True,
    }


def scan_crypto_pair(pair, now_seconds):
    query = urlencode({"pair": pair["altname"], "interval": 60})
    result = fetch_json(KRAKEN_API + "/OHLC?" + query)
    data_key = next((key for key in result if key != "last"), None)
    if data_key is None:
        raise ValueError("Kraken OHLC pair result is missing")
    rows, quality = normalize_kraken_ohlc({"rows": result[data_key]}, now_seconds)
    scanner = scan_btc_market(
        rows,
        market_data_quality=quality,
        interval_hours=1,
        market_label=pair["symbol"],
    )
    return {
        "asset_class": "CRYPTO_SPOT",
        "symbol": pair["symbol"],
        "provider": "Kraken public spot market data",
        "quote_currency": pair["quote"],
        "last_price": pair["last_price"],
        "estimated_24h_quote_volume": round(pair["quote_volume_24h_estimate"], 2),
        "data_quality": quality,
        "scanner": scanner,
        "directional_research": scanner.get("advanced_analysis", {}).get("status", "WATCH"),
        "research_only": True,
        "execution_enabled": False,
    }


def normalize_biquote_metals(symbol, now_seconds):
    quote = fetch_json("https://biquote.io/api/" + symbol + "?allowStale=false")
    if quote.get("symbol") != symbol:
        raise ValueError("Biquote quote symbol mismatch")
    quote_age = finite(quote.get("quoteAgeSeconds"), "metal quote age")
    if quote.get("marketState") != "open" or quote.get("stale") is not False:
        raise ValueError("Metal market is closed or quote is marked stale")
    if not 0 <= quote_age <= 180:
        raise ValueError("Metal bid/ask quote is stale")
    bid, ask = finite(quote.get("bid"), "metal bid"), finite(quote.get("ask"), "metal ask")
    if bid <= 0 or ask < bid:
        raise ValueError("Metal bid/ask is invalid")
    history = fetch_json(
        "https://biquote.io/api/" + symbol + "/ohlc?interval=1h&limit=1000"
    )
    if history.get("symbol") != symbol or history.get("interval") != "1h":
        raise ValueError("Metal hourly history symbol or interval mismatch")
    bars = []
    for item in history.get("bars", []):
        if not isinstance(item, dict) or item.get("isOpen") is not False:
            continue
        stamp = item.get("openTime")
        if not isinstance(stamp, str):
            continue
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Metal candle timestamp lacks timezone")
        timestamp = int(parsed.timestamp())
        if timestamp % INTERVAL_SECONDS:
            raise ValueError("Metal candle timestamp is not UTC-hour aligned")
        values = [finite(item[key], "metal OHLC") for key in ("open", "high", "low", "close")]
        op, high, low, close = values
        if min(values) <= 0 or high < max(op, close, low) or low > min(op, close, high):
            raise ValueError("Metal OHLC bounds are invalid")
        volume = finite(item.get("tickVolume", 0) or 0, "metal tick volume")
        if volume < 0:
            raise ValueError("Metal tick volume cannot be negative")
        bars.append({
            "timestamp": timestamp, "open": op, "high": high, "low": low,
            "close": close, "volume": volume,
        })
    bars.sort(key=lambda item: item["timestamp"])
    unique = {bar["timestamp"]: bar for bar in bars}
    bars = [unique[key] for key in sorted(unique)]
    if len(bars) < 51:
        raise ValueError("Fewer than 51 completed metal hourly candles")
    recent = bars[-51:]
    if any(b["timestamp"] - a["timestamp"] > 4 * INTERVAL_SECONDS
           for a, b in zip(recent, recent[1:])):
        raise ValueError("Metal session history has a gap exceeding four hours")
    age_minutes = (now_seconds - (bars[-1]["timestamp"] + INTERVAL_SECONDS)) / 60.0
    if not -5 <= age_minutes <= 120:
        raise ValueError("Latest completed metal candle is stale")
    scanner_rows = [
        [bar["timestamp"], bar["open"], bar["high"], bar["low"], bar["close"],
         0.0, bar["volume"], int(bar["volume"])]
        for bar in bars
    ]
    quality = {
        "quality_status": "HEALTHY",
        "paper_execution_allowed": True,
        "quote_age_seconds": round(quote_age, 1),
        "latest_closed_candle_age_minutes": round(age_minutes, 2),
        "completed_hourly_candles": len(bars),
        "bounded_session_gaps_allowed": True,
    }
    scanner = scan_btc_market(
        scanner_rows,
        market_data_quality=quality,
        interval_hours=1,
        market_label=symbol,
        allow_session_gaps=True,
        max_session_gap_hours=4,
    )
    return {
        "asset_class": "METAL",
        "symbol": symbol,
        "provider": "Biquote MT5-derived feed",
        "bid": bid,
        "ask": ask,
        "spread": round(ask - bid, 6),
        "data_quality": quality,
        "scanner": scanner,
        "directional_research": scanner.get("advanced_analysis", {}).get("status", "WATCH"),
        "research_only": True,
        "execution_enabled": False,
    }


def opportunity_rank(item):
    scanner = item.get("scanner", {})
    advanced = scanner.get("advanced_analysis", {})
    status = item.get("directional_research", "WATCH")
    priority = 2 if status in ("BULLISH_RESEARCH_CANDIDATE", "BEARISH_RESEARCH_CANDIDATE") else (
        1 if scanner.get("status") == "PAPER_CANDIDATE" else 0
    )
    score = scanner.get("confluence_score", 0)
    total = scanner.get("confluence_total", 8)
    pct = (score / total * 100.0) if isinstance(score, (int, float)) and total else 0
    direction_score = max(
        advanced.get("bullish_score", 0) or 0,
        advanced.get("bearish_score", 0) or 0,
    )
    return (priority, direction_score, pct, item.get("estimated_24h_quote_volume", 0))


def build_report():
    now = datetime.now(timezone.utc)
    now_seconds = now.timestamp()
    assets = []
    errors = {}
    universe_count = 0
    try:
        universe = discover_kraken_universe()
        universe_count = len(universe)
        ranked, missing_tickers = rank_kraken_pairs(universe)
        if missing_tickers:
            errors["kraken_ticker_missing"] = missing_tickers[:100]
        for index, pair in enumerate(ranked):
            try:
                assets.append(scan_crypto_pair(pair, now_seconds))
            except Exception as exc:
                errors[pair["symbol"]] = str(exc)[:300]
            # Public endpoint pacing; prevents hammering the exchange.
            if index < len(ranked) - 1:
                time.sleep(1.05)
    except Exception as exc:
        errors["kraken_universe"] = str(exc)[:500]

    for symbol in METALS:
        try:
            assets.append(normalize_biquote_metals(symbol, now_seconds))
        except Exception as exc:
            errors[symbol] = str(exc)[:300]

    opportunities = [
        item for item in assets
        if item.get("scanner", {}).get("status") == "PAPER_CANDIDATE"
        or item.get("directional_research") in (
            "BULLISH_RESEARCH_CANDIDATE", "BEARISH_RESEARCH_CANDIDATE"
        )
    ]
    opportunities.sort(key=opportunity_rank, reverse=True)
    assets.sort(key=opportunity_rank, reverse=True)
    return {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "scan_mode": "ALL_DISCOVERED_KRAKEN_USD_USDT_USDC_SPOT_PAIRS_PLUS_CONFIGURED_METALS",
        "crypto_pairs_discovered": universe_count,
        "markets_successfully_scanned": len(assets),
        "opportunity_count": len(opportunities),
        "opportunities": opportunities[:100],
        "markets": assets,
        "unavailable_or_failed_markets": errors,
        "safety": {
            "paper_research_only": True,
            "live_orders_enabled": False,
            "paper_ledgers_modified": False,
            "execution_enabled": False,
            "signal_definition": "Existing WHJ scanner confluence and advanced OHLCV research labels; no prediction guarantee",
            "crypto_quote_universe": sorted(QUOTE_CURRENCIES),
            "metals_attempted": list(METALS),
            "all_markets_are_not_guaranteed": (
                "Only markets listed by the selected public providers are scanned. "
                "Provider outages, API limits, unavailable symbols, stale data, and "
                "exchange-specific pairs can leave markets unscanned."
            ),
        },
    }


def main():
    report = build_report()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "latest.json"
    md_path = OUTPUT_DIR / "latest.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "# WHJ multi-market opportunity scan",
        "",
        f"- Generated UTC: {report['generated_at_utc']}",
        f"- Kraken USD/USDT/USDC pairs discovered: {report['crypto_pairs_discovered']}",
        f"- Markets scanned successfully: {report['markets_successfully_scanned']}",
        f"- Research opportunities flagged: {report['opportunity_count']}",
        "- Mode: READ-ONLY PAPER RESEARCH; no orders; no paper ledger changes",
        "",
        "| Rank | Market | Class | Directional research | Confluence | 24h quote volume (est.) |",
        "|---:|---|---|---|---:|---:|",
    ]
    for rank, item in enumerate(report["opportunities"][:50], 1):
        scanner = item.get("scanner", {})
        score = scanner.get("confluence_score", "—")
        total = scanner.get("confluence_total", "—")
        volume = item.get("estimated_24h_quote_volume", "—")
        lines.append(
            f"| {rank} | {item['symbol']} | {item['asset_class']} | "
            f"{item.get('directional_research', 'WATCH')} | {score}/{total} | {volume} |"
        )
    lines += [
        "",
        "## Markets with data issues or unavailable feeds",
        "",
    ]
    if report["unavailable_or_failed_markets"]:
        for symbol, reason in list(report["unavailable_or_failed_markets"].items())[:80]:
            lines.append(f"- **{symbol}:** {reason}")
    else:
        lines.append("- None reported")
    lines += [
        "",
        "> Research labels are not orders or guarantees. The scanner only covers markets returned by its configured providers. No live trading or paper-ledger mutation is performed.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "markets_scanned": report["markets_successfully_scanned"],
        "opportunities": report["opportunity_count"],
        "report": str(json_path),
        "live_orders_enabled": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
