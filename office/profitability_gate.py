#!/usr/bin/env python3
"""Evaluate WHJ historical candidates against conservative profitability gates.

Research gate only: never promotes code, changes the paper wallet, or enables real orders.
Passing means eligible for longer forward paper review.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path("research/strategy_opportunities/latest_report.json")
OUT_JSON = Path("office/profitability_gate_report.json")
OUT_MD = Path("office/profitability_gate_report.md")
MIN_TRADES = 30
MAX_DRAWDOWN_PCT = 8.0
REQUIRED_POSITIVE_WINDOWS = 3


def evaluate_asset(asset, result):
    normal = result.get("normal_cost_ranking", {}).get("ranked_strategies", [])
    stress = result.get("elevated_cost_ranking", {}).get("ranked_strategies", [])
    stress_by_name = {item.get("strategy"): item for item in stress}
    candidates = []
    for base in normal:
        name = base.get("strategy")
        stressed = stress_by_name.get(name)
        if not stressed:
            continue
        checks = {
            "normal_net_oos_positive": base.get("out_of_sample_return_pct", -1) > 0,
            "stress_net_oos_positive": stressed.get("out_of_sample_return_pct", -1) > 0,
            "normal_drawdown_within_limit": base.get("max_drawdown_pct", 999) <= MAX_DRAWDOWN_PCT,
            "stress_drawdown_within_limit": stressed.get("max_drawdown_pct", 999) <= MAX_DRAWDOWN_PCT,
            "normal_all_walk_forward_windows_positive": base.get("positive_windows", 0) >= REQUIRED_POSITIVE_WINDOWS,
            "stress_all_walk_forward_windows_positive": stressed.get("positive_windows", 0) >= REQUIRED_POSITIVE_WINDOWS,
            "normal_trade_sample_sufficient": base.get("closed_trades", 0) >= MIN_TRADES,
            "stress_trade_sample_sufficient": stressed.get("closed_trades", 0) >= MIN_TRADES,
        }
        passed = all(checks.values())
        candidates.append({
            "strategy": name, "normal": base, "stress": stressed,
            "checks": checks, "passed_all_checks": passed,
            "state": "ELIGIBLE_FOR_FORWARD_PAPER_REVIEW" if passed else "REJECT_OR_CONTINUE_RESEARCH",
        })
    candidates.sort(key=lambda x: (not x["passed_all_checks"], -x["normal"].get("score", 0), x["strategy"]))
    return {
        "asset": asset, "candidate_count": len(candidates),
        "qualified_candidates": [x["strategy"] for x in candidates if x["passed_all_checks"]],
        "candidates": candidates,
        "status": "HISTORICAL_CANDIDATE_FOUND" if any(x["passed_all_checks"] for x in candidates) else "NO_HISTORICAL_CANDIDATE_PASSED",
    }


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Research report missing: {SOURCE}")
    report = json.loads(SOURCE.read_text(encoding="utf-8"))
    assets = report.get("assets", {})
    evaluated = {name: evaluate_asset(name, value) for name, value in assets.items()}
    found = any(item["qualified_candidates"] for item in evaluated.values())
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_generated_at_utc": report.get("generated_at_utc"),
        "source_status": report.get("status", "UNKNOWN"),
        "mode": "HISTORICAL_RESEARCH_GATE_ONLY",
        "status": "ELIGIBLE_FOR_FORWARD_PAPER_REVIEW" if found else "CONTINUE_RESEARCH_AND_PAPER_COLLECTION",
        "qualification_rules": {
            "minimum_closed_trades": MIN_TRADES,
            "maximum_oos_drawdown_pct": MAX_DRAWDOWN_PCT,
            "required_positive_walk_forward_windows": REQUIRED_POSITIVE_WINDOWS,
            "must_be_net_positive_at_normal_and_2x_costs": True,
        },
        "assets": evaluated,
        "next_action": (
            "Do not deploy. Start or continue isolated forward paper review for qualifying candidates; "
            "require separate forward evidence before any human decision."
            if found else "Keep collecting and testing candidates. No strategy is declared profitable or promoted."
        ),
        "paper_only": True, "live_trading_enabled": False,
        "orders_submitted": False, "auto_promotion": False, "wallet_mutated": False,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "# WHJ Profitability Development Gate", "",
        f"- Generated UTC: {result['generated_at_utc']}",
        f"- Historical status: **{result['status']}**",
        "- Mode: historical screening only; no deployment or live orders", "",
        "## Qualification rules", "",
        f"- At least {MIN_TRADES} closed out-of-sample trades",
        f"- Positive net OOS return at normal and 2x costs",
        f"- Maximum OOS drawdown no greater than {MAX_DRAWDOWN_PCT}%",
        f"- All {REQUIRED_POSITIVE_WINDOWS} walk-forward windows positive at both cost levels", "",
    ]
    for asset, item in evaluated.items():
        lines += [f"## {asset}: {item['status']}", ""]
        if not item["candidates"]:
            lines.append("No eligible ranking records were available.")
        for candidate in item["candidates"][:10]:
            lines.append(
                f"- {candidate['strategy']}: {'PASS' if candidate['passed_all_checks'] else 'not qualified'}; "
                f"normal OOS {candidate['normal'].get('out_of_sample_return_pct')}%, "
                f"2x-cost OOS {candidate['stress'].get('out_of_sample_return_pct')}%, "
                f"normal DD {candidate['normal'].get('max_drawdown_pct')}%, "
                f"trades {candidate['normal'].get('closed_trades')}"
            )
        lines.append("")
    lines += [
        "## Forward profitability is not yet proven", "",
        "A historical pass only qualifies a candidate for forward paper review. A successful cumulative strategy "
        "must separately show positive net cumulative PnL after fees and slippage over a sufficient forward sample, "
        "stable drawdown, and no data-quality or risk-guard violations. No historical score guarantees future profit.", "",
        "Live trading remains disabled; no strategy is automatically promoted.",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"WHJ profitability gate: {result['status']}; assets={len(evaluated)}; paper-only")


if __name__ == "__main__":
    main()
