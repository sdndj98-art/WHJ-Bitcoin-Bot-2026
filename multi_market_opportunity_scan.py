"""Read-only multi-market crypto and metals opportunity scanner.

Scans Kraken USD/USDT/USDC pairs and five metal spot symbols. Metals use
timestamp-validated Gold-API spot; XAU/XAG/HG also use validated daily bars.
No orders are placed and paper ledgers are never changed.
"""
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_scanner import scan_btc_market
from metal_price_sources import fetch_spot, fetch_daily_bars

KRAKEN_API = "https://api.kraken.com/0/public"
QUOTE_CURRENCIES = {"USD", "USDT", "USDC"}
METALS = ("XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "XCUUSD")
INTERVAL_SECONDS = 3600
STABLE_BASES = {
    "USDT", "USDC", "USDS", "USDP", "USDG", "DAI", "EURC", "FDUSD",
    "TUSD", "PYUSD", "USDE", "USDD", "DUSD", "BUSD", "UST", "USTC",
    "FRAX", "GUSD", "LUSD", "USD0", "CRVUSD",
}
FIAT_BASES = {
    "EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "NZD", "CNY", "CNH",
    "SGD", "HKD", "MXN", "BRL", "ZAR", "TRY", "PLN", "SEK", "NOK",
    "DKK", "CZK", "HUF", "ILS", "AED", "SAR", "THB", "IDR", "INR",
    "KRW", "UAH", "RUB",
}
OUTPUT_DIR = Path("research/multi_market_scan")
USER_AGENT = "WHJ-MultiMarket-PaperScanner/1.0"


def _fetch_payload(url, timeout=25):
    """Fetch a JSON object, retrying only transient HTTP throttling/server errors."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    retryable_statuses = {429, 500, 502, 503, 504}
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError("Market provider returned HTTP " + str(response.status))
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Market provider response is not a JSON object")
            return payload
        except HTTPError as exc:
            if exc.code not in retryable_statuses or attempt == 2:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = min(8.0, max(1.0, float(retry_after)))
            except (TypeError, ValueError, OverflowError):
                delay = float(2 ** attempt)
            time.sleep(delay)
    raise RuntimeError("Market provider retry loop ended unexpectedly")


def fetch_json(url, timeout=25):
    payload = _fetch_payload(url, timeout=timeout)
    errors = payload.get("error", [])
    if errors:
        raise ValueError("Market provider error: " + "; ".join(str(x) for x in errors))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Market provider result is missing")
    return result


def fetch_raw_json(url, timeout=25):
    return _fetch_payload(url, timeout=timeout)


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
        base = str(pair.get("base", "")).upper()
        if base in STABLE_BASES or base in FIAT_BASES:
            continue
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
    """Validate current spot; only XAU/XAG/HG have free daily bar history."""
    quote = fetch_spot(symbol, now_seconds)
    units = quote["price_unit"]
    base = {
        "asset_class": "METAL_SPOT", "symbol": symbol,
        "provider": quote["provider"], "last_price": quote["price_usd"],
        "quote_currency": "USD", "price_unit": units,
        "quote_age_seconds": quote["quote_age_seconds"],
        "expected_delay_minutes": quote["expected_delay_minutes"],
        "computed_at": quote["computed_at"],
        "research_only": True, "execution_enabled": False,
    }
    if symbol in ("XPTUSD", "XPDUSD", "XCUUSD"):
        base.update({
            "history_interval": None, "closed_daily_bars": 0,
            "data_quality": {
                "quality_status": "TIMESTAMP_VALIDATED_SPOT_ONLY",
                "paper_execution_allowed": False,
                "reason": ("goldprice.dev free tier returns plan_gated for HG daily OHLC" if symbol == "XCUUSD" else "No validated free daily OHLC history for platinum/palladium"),
            },
            "directional_research": "WATCH",
        })
        return base
    bars = fetch_daily_bars(symbol, now_seconds)
    base.update({
        "history_interval": "1d", "closed_daily_bars": len(bars),
        "latest_closed_bar": datetime.fromtimestamp(bars[-1][0], timezone.utc).isoformat(),
        "data_quality": {
            "quality_status": "TIMESTAMP_VALIDATED_SPOT_AND_DAILY_BARS",
            "paper_execution_allowed": False,
            "reason": "Scanner is read-only; shared paper engine evaluates daily bars",
        },
        "directional_research": "WATCH",
    })
    return base


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
    ranked_count = 0
    universe_ready = False
    crypto_pairs_scanned = 0
    current_market = None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def make_report(scan_status):
        opportunities = [
            item for item in assets
            if item.get("scanner", {}).get("status") == "PAPER_CANDIDATE"
            or item.get("directional_research") in (
                "BULLISH_RESEARCH_CANDIDATE", "BEARISH_RESEARCH_CANDIDATE"
            )
        ]
        opportunities.sort(key=opportunity_rank, reverse=True)
        ordered_assets = sorted(assets, key=opportunity_rank, reverse=True)
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scan_started_at_utc": now.isoformat(timespec="seconds"),
            "scan_status": scan_status,
            "scan_complete": scan_status == "COMPLETE",
            "universe_discovery_succeeded": universe_ready,
            "current_market": current_market,
            "crypto_pairs_discovered": universe_count,
            "crypto_pairs_ranked": ranked_count,
            "crypto_pairs_scanned": crypto_pairs_scanned,
            "crypto_pairs_remaining": max(0, ranked_count - crypto_pairs_scanned),
            "markets_successfully_scanned": len(assets),
            "opportunity_count": len(opportunities),
            "opportunities": opportunities[:100],
            "markets": ordered_assets,
            "unavailable_or_failed_markets": errors,
            "scan_mode": "ALL_DISCOVERED_KRAKEN_USD_USDT_USDC_SPOT_PAIRS_PLUS_CONFIGURED_METALS",
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

    def checkpoint():
        report = make_report("PARTIAL")
        temporary = OUTPUT_DIR / ".latest.json.tmp"
        temporary.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(OUTPUT_DIR / "latest.json")

    try:
        universe = discover_kraken_universe()
        universe_count = len(universe)
        ranked, missing_tickers = rank_kraken_pairs(universe)
        ranked_count = len(ranked)
        universe_ready = True
        print(f"[WHJ scan] Discovered {universe_count} active pairs; ranked {ranked_count}.", flush=True)
        if missing_tickers:
            errors["kraken_ticker_missing"] = missing_tickers[:100]
        for index, pair in enumerate(ranked):
            current_market = pair["symbol"]
            try:
                assets.append(scan_crypto_pair(pair, now_seconds))
            except Exception as exc:
                errors[pair["symbol"]] = str(exc)[:300]
            crypto_pairs_scanned += 1
            if crypto_pairs_scanned % 25 == 0 or crypto_pairs_scanned == ranked_count:
                print(
                    f"[WHJ scan] {crypto_pairs_scanned}/{ranked_count} crypto pairs; "
                    f"{len(assets)} successful; {len(errors)} unavailable. Current: {current_market}",
                    flush=True,
                )
                checkpoint()
            # Public endpoint pacing; prevents hammering the exchange.
            if index < len(ranked) - 1:
                time.sleep(1.05)
    except Exception as exc:
        errors["kraken_universe"] = str(exc)[:500]
        checkpoint()

    for symbol in METALS:
        current_market = symbol
        try:
            assets.append(normalize_biquote_metals(symbol, now_seconds))
        except Exception as exc:
            errors[symbol] = str(exc)[:300]
        checkpoint()

    return make_report("COMPLETE" if universe_ready and crypto_pairs_scanned == ranked_count else "PARTIAL")

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
