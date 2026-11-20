"""Read-only Hyperliquid whale-position and liquidation-zone monitor.

Only documented public Info API endpoints are used. No signing, trading,
depositing, withdrawing, or order-management endpoints exist in this module.
Wallets must be supplied explicitly in config/hyperliquid_wallets.json.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.hyperliquid.xyz/info"
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
DEFAULT_CONFIG = Path("config/hyperliquid_wallets.json")
DEFAULT_OUTPUT = Path("web/data/hyperliquid_monitor.json")


class HyperliquidAPIError(RuntimeError):
    pass


def info_request(payload: dict, timeout: int = 15):
    body = json.dumps(payload).encode("utf-8")
    request = Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "WHJ-ReadOnly-Monitor/1.0",
    }, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
        raise HyperliquidAPIError(str(exc)) from exc


def load_wallets(config_path: Path, max_wallets: int = 200) -> list[dict]:
    if not config_path.is_file():
        return []
    data = json.loads(config_path.read_text(encoding="utf-8"))
    rows = data.get("wallets", []) if isinstance(data, dict) else []
    wallets, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        address = str(row.get("address", "")).strip()
        if not ADDRESS_RE.fullmatch(address) or address.lower() in seen:
            continue
        seen.add(address.lower())
        wallets.append({
            "address": address,
            "label": str(row.get("label") or address[:8] + "…" + address[-6:])[:64],
        })
        if len(wallets) >= max_wallets:
            break
    return wallets


def number(value, default=0.0):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def fetch_market_data(request_fn=info_request):
    response = request_fn({"type": "metaAndAssetCtxs"})
    if not isinstance(response, list) or len(response) < 2:
        raise HyperliquidAPIError("Unexpected metaAndAssetCtxs response")
    universe = response[0].get("universe", [])
    contexts = response[1]
    markets = {}
    for asset, context in zip(universe, contexts):
        coin = asset.get("name")
        if not coin:
            continue
        markets[coin] = {
            "mark_price": number(context.get("markPx")),
            "oracle_price": number(context.get("oraclePx")),
            "funding": number(context.get("funding")),
            "open_interest": number(context.get("openInterest")),
            "volume_24h": number(context.get("dayNtlVlm")),
        }
    return markets


def fetch_wallet(wallet: dict, request_fn=info_request):
    state = request_fn({"type": "clearinghouseState", "user": wallet["address"]})
    margin = state.get("marginSummary", {}) if isinstance(state, dict) else {}
    positions = []
    for item in state.get("assetPositions", []) if isinstance(state, dict) else []:
        position = item.get("position", {}) if isinstance(item, dict) else {}
        size = number(position.get("szi"))
        if size == 0:
            continue
        positions.append({
            "coin": position.get("coin", "UNKNOWN"),
            "side": "LONG" if size > 0 else "SHORT",
            "size": size,
            "entry_price": number(position.get("entryPx")),
            "liquidation_price": number(position.get("liquidationPx")),
            "position_value_usd": abs(number(position.get("positionValue"))),
            "unrealized_pnl_usd": number(position.get("unrealizedPnl")),
            "leverage": number((position.get("leverage") or {}).get("value"))
                if isinstance(position.get("leverage"), dict)
                else number(position.get("leverage")),
        })
    return {
        "address": wallet["address"],
        "label": wallet["label"],
        "account_value_usd": number(margin.get("accountValue")),
        "total_notional_usd": number(margin.get("totalNtlPos")),
        "unrealized_pnl_usd": sum(p["unrealized_pnl_usd"] for p in positions),
        "positions": positions,
    }


def build_liquidation_zones(wallet_reports: list[dict], markets: dict,
                            band_pct: float = 0.5) -> list[dict]:
    buckets = {}
    for wallet in wallet_reports:
        for position in wallet["positions"]:
            coin = position["coin"]
            current = markets.get(coin, {}).get("mark_price", 0)
            liquidation = position["liquidation_price"]
            if current <= 0 or liquidation <= 0:
                continue
            distance_pct = (liquidation - current) / current * 100
            band = math.floor((distance_pct / band_pct) + 0.5) * band_pct
            key = (coin, position["side"], round(band, 4))
            entry = buckets.setdefault(key, {
                "coin": coin, "side": position["side"],
                "distance_from_mark_pct": round(band, 4),
                "liquidation_price_low": liquidation,
                "liquidation_price_high": liquidation,
                "estimated_position_value_usd": 0.0,
                "wallet_count": 0,
                "wallet_labels": [],
            })
            entry["liquidation_price_low"] = min(entry["liquidation_price_low"], liquidation)
            entry["liquidation_price_high"] = max(entry["liquidation_price_high"], liquidation)
            entry["estimated_position_value_usd"] += position["position_value_usd"]
            if wallet["label"] not in entry["wallet_labels"]:
                entry["wallet_labels"].append(wallet["label"])
                entry["wallet_count"] += 1
    return sorted(buckets.values(),
                  key=lambda x: x["estimated_position_value_usd"], reverse=True)


def build_report(config_path: Path = DEFAULT_CONFIG, request_fn=info_request,
                 sleep_fn=time.sleep, wallet_limit: int = 200) -> dict:
    wallets = load_wallets(config_path, wallet_limit)
    markets = fetch_market_data(request_fn)
    wallet_reports, failures = [], []
    for index, wallet in enumerate(wallets):
        try:
            wallet_reports.append(fetch_wallet(wallet, request_fn))
        except HyperliquidAPIError as exc:
            failures.append({"label": wallet["label"], "error": str(exc)[:240]})
        # Each clearinghouseState info request has weight 2; use a conservative
        # delay so a full 200-wallet pass stays within the documented IP budget.
        if index < len(wallets) - 1:
            sleep_fn(1.1)

    zones = build_liquidation_zones(wallet_reports, markets)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Hyperliquid public Info API",
        "mode": "READ_ONLY_PAPER_ONLY",
        "status": "healthy" if not failures else "partial",
        "wallets_configured": len(wallets),
        "wallets_scanned": len(wallet_reports),
        "wallet_scan_failures": failures,
        "wallet_discovery": "EXPLICIT_CONFIGURED_ADDRESSES_ONLY",
        "wallet_ranking": "NOT_AVAILABLE_FROM_THIS_PUBLIC_INFO_QUERY",
        "markets": markets,
        "liquidation_zones": zones,
        "wallets": wallet_reports,
        "limitations": [
            "The public Info API calls used here do not provide a global top-200 wallet leaderboard or 30-day wallet PnL ranking.",
            "Only explicitly configured wallet addresses are monitored.",
            "Liquidation bands aggregate reported liquidation prices and position values; they are estimates, not guaranteed liquidation orders or exchange-wide liquidation heatmaps.",
            "This module is read-only and cannot place, amend, or cancel orders.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="WHJ read-only Hyperliquid monitor")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--wallet-limit", type=int, default=200)
    parser.add_argument("--interval", type=int, default=0,
                        help="Repeat locally every N seconds; 0 runs once")
    args = parser.parse_args(argv)
    config_path, output_path = Path(args.config), Path(args.output)
    if not 1 <= args.wallet_limit <= 200:
        parser.error("--wallet-limit must be between 1 and 200")
    if args.interval and args.interval < 60:
        parser.error("--interval must be at least 60 seconds")
    while True:
        try:
            report = build_report(config_path, wallet_limit=args.wallet_limit)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print("WHJ Hyperliquid monitor:", report["status"],
                  "wallets:", report["wallets_scanned"],
                  "zones:", len(report["liquidation_zones"]))
            if report["status"] == "partial":
                print("Some wallet requests failed; see wallet_scan_failures.")
        except (HyperliquidAPIError, OSError, json.JSONDecodeError) as exc:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            failure = {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": "Hyperliquid public Info API",
                "mode": "READ_ONLY_PAPER_ONLY",
                "status": "error",
                "error": str(exc)[:500],
                "wallets": [],
                "markets": {},
                "liquidation_zones": [],
            }
            output_path.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
            print("WHJ Hyperliquid monitor error:", str(exc))
            if not args.interval:
                return 1
        if not args.interval:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
