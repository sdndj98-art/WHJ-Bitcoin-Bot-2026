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
    return bool(feed) and "HEALTHY" in feed and status.startswith("PAPER_")


def _agent(name, status, detail, metrics=None):
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "metrics": metrics or {},
    }


def build_agent_state(snapshot, generated_at=None):
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
    scanner_ok = all(healthy.values())
    scanner = _agent(
        "SCANNER",
        "READY" if scanner_ok else "WAITING_DATA",
        "Both BTC and XAUUSD feeds passed their snapshot quality checks."
        if scanner_ok else "Waiting for fresh, healthy BTC and XAUUSD feed snapshots.",
        {"healthy_markets": [s for s, ok in healthy.items() if ok],
         "markets": list(sleeves)},
    )

    pause_reasons = {
        symbol: list(sleeve.get("risk_pause_reasons") or [])
        for symbol, sleeve in sleeves.items()
    }
    risk_ok = safety_ok and all(healthy.values()) and not any(pause_reasons.values())
    rug_check = _agent(
        "RUG CHECK",
        "PASS" if risk_ok else "BLOCKED",
        "Paper-only guardrails, feed quality, and portfolio risk pauses checked."
        if risk_ok else "Blocked: verify paper-only flags, feed quality, or risk pause reasons.",
        {"paper_only": paper_only, "live_trading_disabled": live_disabled,
         "risk_pause_reasons": pause_reasons},
    )

    allocations = {}
    sizing_ok = True
    for symbol, sleeve in sleeves.items():
        limits = sleeve.get("risk_limits") or {}
        allocation = limits.get("allocation_pct")
        if not _finite_number(allocation) or not 0 < allocation <= 10:
            sizing_ok = False
        else:
            allocations[symbol] = float(allocation)
    sizer = _agent(
        "SIZER",
        "READY" if sizing_ok and risk_ok else "BLOCKED",
        "Validated per-sleeve allocation caps (maximum 10%); no order is submitted."
        if sizing_ok and risk_ok else "Position sizing is blocked until risk and allocation limits are valid.",
        {"allocation_pct": allocations, "maximum_allocation_pct": 10.0},
    )

    executor_ok = safety_ok and scanner_ok and risk_ok and sizing_ok
    executor = _agent(
        "EXECUTOR",
        "PAPER_READY" if executor_ok else "BLOCKED",
        "Paper ledger only; execution is limited to the existing simulated runners."
        if executor_ok else "No execution: safety, feed, risk, or sizing gate did not pass.",
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

    return {
        "schema_version": 1,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(),
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
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text(encoding="utf-8"))
    result = build_agent_state(snapshot)
    atomic_write_json(args.output, result)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
