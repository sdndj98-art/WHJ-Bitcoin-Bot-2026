"""Eight-role WHJ desk telemetry for the shared paper portfolio.

All roles are read-only/advisory. This module never creates orders, modifies
portfolio state, changes strategy parameters, or enables live trading.
"""
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_INPUT = Path("dual_portfolio.json")
DEFAULT_REPORT = Path("state/multi_asset_paper_report.json")
DEFAULT_OUTPUT = Path("state/whj_desk.json")

ROLES = [
    ("SEARCH", "Market and data discovery"),
    ("RUG", "Liquidity and safety watch"),
    ("SNIPER", "Paper entry timing"),
    ("RISK", "Portfolio risk gate"),
    ("WHALE", "Large-wallet signal watch"),
    ("EXIT", "Exit and position monitoring"),
    ("SHILL", "Social-sentiment watch"),
    ("HEAD OF DESK", "Read-only consensus and handoff"),
]

def build_desk(snapshot, report=None, generated_at=None):
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    report = report if isinstance(report, dict) else {}
    multi = snapshot.get("multi_asset_paper") or {}
    markets = multi.get("markets_scanned") or report.get("markets") or []
    diagnostics = multi.get("strategy_diagnostics") or report.get("strategy_diagnostics") or {}
    events = multi.get("events_this_run") or report.get("events") or []
    portfolio = snapshot.get("shared_portfolio") or {}
    paper = snapshot.get("paper_only") is True and snapshot.get("live_trading_enabled") is False
    scanned = len(markets) if isinstance(markets, list) else 0
    entry_signals = sum(int(v.get("entry_signals", 0) or 0) for v in diagnostics.values() if isinstance(v, dict))
    exit_signals = sum(int(v.get("exit_signals", 0) or 0) for v in diagnostics.values() if isinstance(v, dict))
    blocked = sum(int(v.get("blocked", 0) or 0) for v in diagnostics.values() if isinstance(v, dict))
    opened = sum(int(v.get("opened", 0) or 0) for v in diagnostics.values() if isinstance(v, dict))
    positions = portfolio.get("open_positions")
    if not isinstance(positions, list):
        positions = []
    closed = portfolio.get("closed_trades", 0)
    # Some ledger schemas store closed trades as a list; preserve count safely.
    closed_count = len(closed) if isinstance(closed, list) else int(closed or 0)
    roles = [
        {"name":"SEARCH","status":"DATA_FOUND" if scanned else "WAITING_DATA","detail":"Reports only validated symbols from the paper scan.","metrics":{"markets_scanned":scanned}},
        {"name":"RUG","status":"PAPER_GUARD" if paper else "BLOCKED","detail":"No contract-audit or liquidity-proof claims are made from spot candles alone.","metrics":{"paper_only":paper,"live_trading_enabled":not paper}},
        {"name":"SNIPER","status":"SIGNALS_REVIEWED" if entry_signals else "WAITING_SIGNAL","detail":"Reads closed-candle strategy signals; does not submit orders.","metrics":{"entry_signals":entry_signals,"opened":opened}},
        {"name":"RISK","status":"RISK_GATES_ACTIVE","detail":"Uses the engine's existing portfolio and position limits.","metrics":{"blocked_entries":blocked,"open_positions":len(positions)}},
        {"name":"WHALE","status":"DATA_UNAVAILABLE","detail":"On-chain wallet-flow data is not connected; no whale accumulation is fabricated.","metrics":{"wallet_feed_connected":False}},
        {"name":"EXIT","status":"EXIT_SIGNALS_RECORDED" if exit_signals else "MONITORING","detail":"Reports strategy exit signals; does not force-close positions.","metrics":{"exit_signals":exit_signals}},
        {"name":"SHILL","status":"DATA_UNAVAILABLE","detail":"Social sentiment feed is not connected; social buzz is not used as a trade signal.","metrics":{"social_feed_connected":False}},
        {"name":"HEAD OF DESK","status":"PAPER_ONLY" if paper else "SAFETY_BLOCKED","detail":"Summarizes the current run. Human review remains required; no order authority.","metrics":{"events_this_run":len(events) if isinstance(events,list) else 0,"consensus":"READ_ONLY","orders_submitted":False}},
    ]
    return {
        "schema_version":1,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(),
        "mode":"PAPER_ONLY" if paper else "SAFETY_BLOCKED",
        "live_trading_enabled":False,
        "orders_submitted":False,
        "wallet":"SHARED_VIRTUAL_100_USD",
        "portfolio":{"equity_usd":portfolio.get("equity_usd"),"pnl_usd":portfolio.get("pnl_usd"),"open_positions":len(positions),"closed_trades":closed_count},
        "summary":{"agent_count":8,"markets_scanned":scanned,"entry_signals":entry_signals,"exit_signals":exit_signals,"blocked_entries":blocked,"opened":opened},
        "agents":roles,
        "notice":"SEARCH/RUG/SNIPER/RISK/WHale/EXIT/SHILL are telemetry/advisory roles only. No browser agents, social/on-chain feeds, or live trading are enabled."
    }

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,default=DEFAULT_INPUT)
    parser.add_argument("--report",type=Path,default=DEFAULT_REPORT)
    parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args(argv)
    snapshot=json.loads(args.input.read_text(encoding="utf-8"))
    report=json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {}
    payload=build_desk(snapshot,report)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=args.output.with_suffix(args.output.suffix+".tmp")
    tmp.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    tmp.replace(args.output)
    print(json.dumps(payload["summary"],sort_keys=True))

if __name__=="__main__":
    main()
