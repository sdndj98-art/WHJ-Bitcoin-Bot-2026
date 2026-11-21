"""WHJ six-agent paper-trading coordinator.

This module reads the existing BTC/XAUUSD paper snapshot and emits truthful
agent telemetry. It never places orders, changes portfolio ledgers, or enables
live trading. The dashboard is intentionally not modified by this module.
"""
import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_INPUT = Path("dual_portfolio.json")
DEFAULT_OUTPUT = Path("state/whj_agents.json")
DEFAULT_RESEARCH_REPORT = Path("research/paper_learning/latest_report.json")
AGENT_NAMES = ("SCANNER", "RUG CHECK", "SIZER", "EXECUTOR", "LOGGER", "EQUITY")


def _finite_number(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value))


def _quality_ok(sleeve):
    quality = sleeve.get("data_quality")
    if not isinstance(quality, dict):
        return False
    return str(quality.get("quality", "")).upper() == "HEALTHY"


def _feed_ok(sleeve):
    feed = str(sleeve.get("feed_status", "")).upper()
    status = str(sleeve.get("status", "")).upper()
    return bool(feed) and status.startswith("PAPER_")


def _agent(name, status, detail, metrics=None):
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "metrics": metrics or {},
    }


def _market_signal(sleeve):
    """Read only an explicit, already-computed strategy signal; never invent one."""
    for key in ("strategy_signal", "entry_signal", "signal"):
        value = sleeve.get(key)
        if isinstance(value, str) and value.upper() in ("BUY", "SELL", "HOLD"):
            return value.upper()
    return "HOLD"


def build_unified_decision(sleeves, healthy, safety_ok, risk_ok, sizing_ok):
    """One central decision per market, gated by all six agent responsibilities."""
    market_decisions = {}
    for symbol, sleeve in sleeves.items():
        signal = _market_signal(sleeve)
        reasons = []
        if not safety_ok:
            reasons.append("PAPER_ONLY_SAFETY_GATE_FAILED")
        if not healthy.get(symbol, False):
            reasons.append("MARKET_DATA_NOT_HEALTHY")
        if sleeve.get("risk_pause_reasons"):
            reasons.append("RISK_PAUSE_ACTIVE")
        allocation = (sleeve.get("risk_limits") or {}).get("allocation_pct")
        if not _finite_number(allocation) or not 0 < allocation <= 10:
            reasons.append("POSITION_SIZE_INVALID")
        if not risk_ok:
            reasons.append("GLOBAL_RISK_GATE_FAILED")
        if not sizing_ok:
            reasons.append("GLOBAL_SIZING_GATE_FAILED")
        if signal == "HOLD":
            reasons.append("NO_EXPLICIT_BUY_OR_SELL_SIGNAL")
        decision = signal if not reasons else "HOLD"
        market_decisions[symbol] = {
            "decision": decision,
            "strategy_signal": signal,
            "reason_codes": sorted(set(reasons)),
            "approved_by_consensus": decision in ("BUY", "SELL"),
            "execution_mode": "PAPER_ONLY",
            "live_orders_enabled": False,
        }
    values = [item["decision"] for item in market_decisions.values()]
    portfolio_decision = (
        "HOLD" if not values or all(value == "HOLD" for value in values)
        else "ACTION_REQUIRED"
    )
    return {
        "model": "SIX_AGENT_UNIFIED_CONSENSUS",
        "portfolio_decision": portfolio_decision,
        "market_decisions": market_decisions,
        "agent_roles": list(AGENT_NAMES),
        "rule": "Any failed safety, data, risk, or sizing gate forces HOLD for that market.",
        "paper_only": True,
        "live_trading_enabled": False,
        "orders_submitted": False,
    }


def authorize_paper_entry(market, feed_healthy, context):
    """Return True only when the six-agent paper consensus approves a BUY entry."""
    if not isinstance(context, dict) or context.get("signal") != "BUY":
        return False
    allocation_pct = context.get("allocation_pct")
    risk_paused = context.get("risk_paused") is True
    sleeve = {
        "strategy_signal": "BUY",
        "feed_status": "PAPER_FEED_HEALTHY" if feed_healthy else "FEED_BLOCKED",
        "status": "PAPER_RUNNING" if feed_healthy else "FEED_BLOCKED",
        "data_quality": {"quality": "HEALTHY" if feed_healthy else "UNHEALTHY"},
        "risk_pause_reasons": ["RISK_PAUSE_ACTIVE"] if risk_paused else [],
        "risk_limits": {"allocation_pct": allocation_pct},
    }
    safety_ok = True
    healthy = {market: bool(feed_healthy)}
    risk_ok = bool(feed_healthy) and not risk_paused
    sizing_ok = _finite_number(allocation_pct) and 0 < allocation_pct <= 10
    decision = build_unified_decision(
        {market: sleeve}, healthy, safety_ok, risk_ok, sizing_ok
    )
    return decision["market_decisions"][market]["approved_by_consensus"] is True


def _research_advisory(report):
    """Accept only a correctly marked, read-only paper report; never trade from it."""
    if report is None:
        return {"status": "NOT_PROVIDED", "markets": {}, "changes_strategy": False}
    if not isinstance(report, dict):
        return {"status": "INVALID_REPORT", "markets": {}, "changes_strategy": False}
    governance = report.get("governance")
    if (report.get("mode") != "READ_ONLY_PAPER_RESEARCH"
            or report.get("paper_only") is not True
            or report.get("live_trading_enabled") is not False
            or not isinstance(governance, dict)
            or governance.get("strategy_auto_changes") is not False
            or governance.get("ledger_mutation") is not False
            or governance.get("risk_limit_changes") is not False
            or governance.get("dashboard_modified") is not False
            or governance.get("orders_submitted") is not False):
        return {"status": "REJECTED_UNSAFE_REPORT", "markets": {},
                "changes_strategy": False}
    markets = report.get("markets")
    if not isinstance(markets, dict):
        return {"status": "INVALID_REPORT", "markets": {},
                "changes_strategy": False}
    comparison = report.get("comparison")
    if not isinstance(comparison, dict):
        return {"status": "INVALID_REPORT", "markets": {},
                "changes_strategy": False}
    selected = {}
    for symbol in ("BTC", "XAUUSD"):
        item = markets.get(symbol)
        if not isinstance(item, dict):
            return {"status": "INCOMPLETE_REPORT", "markets": {},
                    "changes_strategy": False}
        selected[symbol] = {
            "review_status": item.get("review_status", "UNKNOWN"),
            "next_action": item.get("next_action", "HUMAN_REVIEW_ONLY"),
            "closed_trades": item.get("closed_trades", 0),
            "return_pct": item.get("return_pct"),
            "profit_factor": item.get("profit_factor"),
            "max_drawdown_pct": item.get("max_drawdown_pct"),
        }
    return {
        "status": comparison.get("status", "UNKNOWN"),
        "markets": selected,
        "changes_strategy": False,
        "execution_authority": False,
        "note": "Research advisory only. It cannot override live signal, risk, feed, sizing, or paper consensus gates.",
    }


def build_agent_state(snapshot, generated_at=None, research_report=None):
    """Build six agent statuses from the latest dual-paper portfolio snapshot."""
    if not isinstance(snapshot, dict):
        raise ValueError("Portfolio snapshot must be a JSON object")
    btc = snapshot.get("btc")
    gold = snapshot.get("gold")
    if not isinstance(btc, dict) or not isinstance(gold, dict):
        raise ValueError("Snapshot must contain both btc and gold paper sleeves")

    paper_only = snapshot.get("paper_only") is True
    live_disabled = snapshot.get("live_trading_enabled") is False
    safety_ok = paper_only and live_disabled

    sleeves = {"BTC": btc, "XAUUSD": gold}
    healthy = {
        symbol: _feed_ok(sleeve) and _quality_ok(sleeve)
        for symbol, sleeve in sleeves.items()
    }
    scanner_ok = any(healthy.values())
    scanner = _agent(
        "SCANNER",
        "READY" if scanner_ok else "WAITING_DATA",
        "At least one market has a fresh, healthy feed; each market is gated independently."
        if scanner_ok else "Waiting for at least one fresh, healthy market feed.",
        {"healthy_markets": [s for s, ok in healthy.items() if ok],
         "markets": list(sleeves)},
    )

    pause_reasons = {
        symbol: list(sleeve.get("risk_pause_reasons") or [])
        for symbol, sleeve in sleeves.items()
    }
    risk_ok = safety_ok
    rug_check = _agent(
        "RUG CHECK",
        "PASS" if risk_ok else "BLOCKED",
        "Paper-only safety passed; risk pauses are enforced separately for each market."
        if risk_ok else "Blocked: paper-only safety flags did not pass.",
        {"paper_only": paper_only, "live_trading_disabled": live_disabled,
         "risk_pause_reasons": pause_reasons},
    )

    allocations = {}
    allocations_valid = {}
    for symbol, sleeve in sleeves.items():
        limits = sleeve.get("risk_limits") or {}
        allocation = limits.get("allocation_pct")
        if not _finite_number(allocation) or not 0 < allocation <= 10:
            continue
        allocations[symbol] = float(allocation)
        allocations_valid[symbol] = healthy.get(symbol, False)
    sizing_ok = any(allocations_valid.values())
    sizer = _agent(
        "SIZER",
        "READY" if sizing_ok and risk_ok else "BLOCKED",
        "At least one healthy market has a valid allocation cap (maximum 10%)."
        if sizing_ok and risk_ok else "Position sizing is blocked until a healthy market has a valid allocation.",
        {"allocation_pct": allocations, "maximum_allocation_pct": 10.0},
    )

    executor_ok = safety_ok and scanner_ok and sizing_ok
    executor = _agent(
        "EXECUTOR",
        "PAPER_READY" if executor_ok else "BLOCKED",
        "Paper ledger only; every market still needs its own six-agent approval."
        if executor_ok else "No execution: safety, healthy-feed, or sizing gate did not pass.",
        {"mode": "PAPER_ONLY", "live_orders_enabled": False,
         "order_submission_by_agent": False},
    )

    trade_count = 0
    for sleeve in sleeves.values():
        entries = sleeve.get("new_trades", [])
        if isinstance(entries, list):
            trade_count += len(entries)
    logger = _agent(
        "LOGGER",
        "RECORDS_AVAILABLE" if trade_count else "WAITING_EVENTS",
        "Found trade events in the portfolio snapshot."
        if trade_count else "No new trade events are present in this snapshot.",
        {"new_trade_events": trade_count},
    )

    total_equity = sum(
        float(sleeve.get("equity_usd", 0))
        for sleeve in sleeves.values()
        if _finite_number(sleeve.get("equity_usd", 0))
    )
    total_initial = sum(
        float(sleeve.get("initial_equity_usd", 0))
        for sleeve in sleeves.values()
        if _finite_number(sleeve.get("initial_equity_usd", 0))
    )
    total_pnl = total_equity - total_initial
    closed = sum(
        int(sleeve.get("closed_trades", 0))
        for sleeve in sleeves.values()
        if isinstance(sleeve.get("closed_trades", 0), int)
        and not isinstance(sleeve.get("closed_trades", 0), bool)
    )
    equity_agent = _agent(
        "EQUITY",
        "TRACKING" if total_initial > 0 else "WAITING_CAPITAL",
        "Combined paper equity calculated from the BTC and XAUUSD ledgers.",
        {"equity_usd": round(total_equity, 4),
         "initial_equity_usd": round(total_initial, 4),
         "pnl_usd": round(total_pnl, 4),
         "return_pct": round(total_pnl / total_initial * 100, 4) if total_initial else None,
         "closed_trades": closed},
    )

    unified_decision = build_unified_decision(
        sleeves, healthy, safety_ok, safety_ok, sizing_ok
    )
    unified_decision["research_advisory"] = _research_advisory(research_report)

    return {
        "schema_version": 2,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(),
        "unified_decision": unified_decision,
        "source_updated_at": snapshot.get("updated_at"),
        "mode": "PAPER_ONLY" if safety_ok else "SAFETY_BLOCKED",
        "live_trading_enabled": False,
        "portfolio_status": snapshot.get("status", "UNKNOWN"),
        "agents": [scanner, rug_check, sizer, executor, logger, equity_agent],
        "summary": {
            "agent_count": len(AGENT_NAMES),
            "ready_count": sum(a["status"] in ("READY", "PASS", "PAPER_READY", "TRACKING", "RECORDS_AVAILABLE") for a in
                               (scanner, rug_check, sizer, executor, logger, equity_agent)),
            "markets": ["BTC/USD", "XAUUSD"],
            "paper_only": safety_ok,
        },
    }


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent),
            prefix="." + path.name + ".", suffix=".tmp", delete=False
        ) as handle:
            temp = handle.name
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        if temp and os.path.exists(temp):
            os.unlink(temp)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--research-report", type=Path, default=DEFAULT_RESEARCH_REPORT)
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text(encoding="utf-8"))
    research_report = None
    if args.research_report.exists():
        research_report = json.loads(args.research_report.read_text(encoding="utf-8"))
    result = build_agent_state(snapshot, research_report=research_report)
    atomic_write_json(args.output, result)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
