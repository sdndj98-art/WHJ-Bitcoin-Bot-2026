"""Scheduled, read-only Bitcoin and Gold strategy opportunity research.

Fetches public historical candles, compares fixed rules on chronological
holdouts with normal and elevated costs, and writes an artifact report.
It never changes paper ledgers, production strategies, dashboard files, or
submits orders. Missing data is reported as unavailable, never fabricated.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from historical_research import load_two_year_candles
from strategy_lab import run_strategy_lab
from strategy_ranking import rank_strategy_results

GOLD_HISTORY_URL = "https://biquote.io/api/XAUUSD/ohlc?interval=1h&limit=1000"
NORMAL_COSTS = {"fee": 0.001, "slippage": 0.0005}
STRESS_COSTS = {"fee": 0.002, "slippage": 0.001}
OUTPUT_DIR = Path("research/strategy_opportunities")


def fetch_json(url):
    request = Request(url, headers={
        "User-Agent": "WHJ-StrategyResearch/1.0",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=25) as response:
        if response.status != 200:
            raise ValueError("Market data provider returned HTTP " + str(response.status))
        return json.loads(response.read().decode("utf-8"))


def normalize_gold_history(payload):
    """Validate completed XAUUSD hourly candles from the public research feed."""
    if not isinstance(payload, dict) or payload.get("symbol") != "XAUUSD":
        raise ValueError("Gold history symbol is missing or unexpected")
    if payload.get("interval") != "1h" or not isinstance(payload.get("bars"), list):
        raise ValueError("Gold hourly bars are missing or have an unexpected interval")
    rows = []
    for item in payload["bars"]:
        if not isinstance(item, dict) or item.get("isOpen") is not False:
            continue
        stamp = item.get("openTime")
        if not isinstance(stamp, str):
            continue
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Gold candle timestamps must include a timezone")
        timestamp = int(parsed.timestamp())
        if timestamp % 3600:
            raise ValueError("Gold hourly candle timestamp is not aligned")
        values = {key: float(item[key]) for key in ("open", "high", "low", "close")}
        if any(not math.isfinite(value) or value <= 0 for value in values.values()):
            raise ValueError("Gold candle has a non-finite or non-positive price")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError("Gold candle high is inconsistent")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError("Gold candle low is inconsistent")
        rows.append({"timestamp": timestamp, **values})
    rows.sort(key=lambda row: row["timestamp"])
    unique = {row["timestamp"]: row for row in rows}
    rows = list(unique.values())
    if len(rows) < 300:
        raise ValueError("Insufficient validated closed Gold candles: " + str(len(rows)))
    if any(b["timestamp"] <= a["timestamp"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Gold candle timestamps are not strictly increasing")
    recent = rows[-25:]
    if any(b["timestamp"] - a["timestamp"] > 4 * 3600 for a, b in zip(recent, recent[1:])):
        raise ValueError("Gold recent history contains an unexplained gap over four hours")
    return rows


def analyze_prices(asset, prices, source, sample_start=None, sample_end=None):
    """Compare unchanged fixed-rule candidates at base and stressed costs."""
    if not isinstance(prices, list) or len(prices) < 300:
        raise ValueError("At least 300 finite prices are required")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0 for value in prices):
        raise ValueError("Prices must be finite positive numbers")
    normal = run_strategy_lab(prices, **NORMAL_COSTS)
    stress = run_strategy_lab(prices, **STRESS_COSTS)
    ranked = rank_strategy_results(normal["strategies"])
    stressed_ranked = rank_strategy_results(stress["strategies"])
    return {
        "asset": asset,
        "source": source,
        "sample_count": len(prices),
        "sample_start_utc": sample_start,
        "sample_end_utc": sample_end,
        "normal_costs": NORMAL_COSTS,
        "elevated_costs": STRESS_COSTS,
        "normal_cost_research": normal,
        "elevated_cost_research": stress,
        "normal_cost_ranking": ranked,
        "elevated_cost_ranking": stressed_ranked,
        "interpretation": (
            "Research ranking only. A high score is not a deployment approval; "
            "compare normal and elevated costs, sample size, drawdown, and all "
            "three chronological holdout windows. No strategy is auto-selected."
        ),
        "research_only": True,
        "paper_only": True,
        "live_trading_enabled": False,
        "execution_enabled": False,
        "production_strategy_changed": False,
        "paper_ledger_modified": False,
    }


def build_report():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    assets = {}
    errors = {}
    try:
        btc = load_two_year_candles(days=365)
        assets["BTC"] = analyze_prices(
            "BTC", [row["close"] for row in btc],
            "Coinbase public BTC-USD completed hourly candles",
            datetime.fromtimestamp(btc[0]["timestamp"] / 1000, timezone.utc).isoformat(),
            datetime.fromtimestamp(btc[-1]["timestamp"] / 1000, timezone.utc).isoformat(),
        )
        assets["BTC"]["data_quality"] = {
            "imputed_missing_hours": btc[0].get("_imputed_hour_count", 0),
            "ohlcv_source_validated": True,
        }
    except Exception as exc:
        errors["BTC"] = str(exc)
    try:
        gold = normalize_gold_history(fetch_json(GOLD_HISTORY_URL))
        assets["XAUUSD"] = analyze_prices(
            "XAUUSD", [row["close"] for row in gold],
            "Biquote public XAUUSD completed hourly OHLC history",
            datetime.fromtimestamp(gold[0]["timestamp"], timezone.utc).isoformat(),
            datetime.fromtimestamp(gold[-1]["timestamp"], timezone.utc).isoformat(),
        )
        assets["XAUUSD"]["data_quality"] = {
            "validated_closed_bars": len(gold),
            "ohlc_source_validated": True,
            "note": "Historical research feed; not a broker execution quote.",
        }
    except Exception as exc:
        errors["XAUUSD"] = str(exc)
    return {
        "project": "WHJ Terminal",
        "generated_at_utc": now,
        "mode": "READ_ONLY_STRATEGY_OPPORTUNITY_RESEARCH",
        "assets": assets,
        "data_errors": errors,
        "status": "COMPLETE" if len(assets) == 2 else ("PARTIAL" if assets else "NO_VALID_MARKET_DATA"),
        "safety": {
            "paper_only": True,
            "live_trading_enabled": False,
            "orders_submitted": False,
            "production_strategy_changed": False,
            "dashboard_changed": False,
            "paper_ledger_modified": False,
        },
        "limitations": [
            "Historical backtests do not predict future returns.",
            "Gold historical candles are not a live executable bid/ask feed.",
            "The report does not automatically select, deploy, or alter a strategy.",
            "A missing or invalid data feed is reported as an error, not replaced with invented prices.",
        ],
    }


def write_report(report, output_dir=OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "latest_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# WHJ Strategy Opportunity Research",
        "",
        "- Generated: " + report["generated_at_utc"],
        "- Status: " + report["status"],
        "- Mode: read-only historical research; no trading or ledger changes",
        "",
    ]
    for asset, result in report["assets"].items():
        lines.extend([
            "## " + asset,
            "- Candles: " + str(result["sample_count"]),
            "- Source: " + result["source"],
            "- Period: " + str(result["sample_start_utc"]) + " to " + str(result["sample_end_utc"]),
            "- Normal-cost candidates ranked: " + str(len(result["normal_cost_ranking"]["ranked_strategies"])),
            "- Elevated-cost candidates ranked: " + str(len(result["elevated_cost_ranking"]["ranked_strategies"])),
            "- Research-only; not approved for live trading",
            "",
        ])
        for label, key in (("Normal costs", "normal_cost_ranking"),
                           ("Elevated costs", "elevated_cost_ranking")):
            ranked = result[key]["ranked_strategies"]
            lines.append("### " + label)
            if not ranked:
                lines.append("No candidate met the minimum sample requirements.")
            else:
                for item in ranked[:5]:
                    lines.append(
                        "- {strategy}: score {score}, OOS {ret}% , drawdown {dd}% , "
                        "trades {trades}".format(
                            strategy=item["strategy"], score=item["score"],
                            ret=item["out_of_sample_return_pct"],
                            dd=item["max_drawdown_pct"], trades=item["closed_trades"],
                        )
                    )
            lines.append("")
    if report["data_errors"]:
        lines.extend(["## Data errors", ""])
        for asset, error in report["data_errors"].items():
            lines.append("- " + asset + ": " + error)
    lines.extend(["", "No strategy was deployed or modified."])
    (output_dir / "latest_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    report = build_report()
    write_report(report)
    print(json.dumps({
        "status": report["status"],
        "assets_analyzed": sorted(report["assets"]),
        "data_errors": report["data_errors"],
        "report_directory": str(OUTPUT_DIR),
        "paper_only": True,
        "live_trading_enabled": False,
    }, indent=2))


if __name__ == "__main__":
    main()
