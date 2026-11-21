import copy
import json
import tempfile
import unittest
from pathlib import Path

from whj_agents import build_agent_state, atomic_write_json, authorize_paper_entry


def healthy_snapshot():
    sleeve = {
        "initial_equity_usd": 10.0,
        "equity_usd": 10.0,
        "closed_trades": 0,
        "feed_status": "EXAMPLE_HEALTHY",
        "status": "PAPER_RUNNING",
        "data_quality": {"quality": "HEALTHY"},
        "risk_pause_reasons": [],
        "risk_limits": {"allocation_pct": 10.0},
        "new_trades": [],
    }
    return {
        "status": "BTC_AND_GOLD_PAPER_ONLY",
        "paper_only": True,
        "live_trading_enabled": False,
        "updated_at": "2026-11-18T00:00:00+00:00",
        "btc": copy.deepcopy(sleeve),
        "gold": copy.deepcopy(sleeve),
    }


class WhjAgentsTests(unittest.TestCase):
    def test_builds_six_agents_and_paper_guard(self):
        state = build_agent_state(healthy_snapshot(), generated_at="fixed")
        self.assertEqual(len(state["agents"]), 6)
        self.assertEqual(state["mode"], "PAPER_ONLY")
        self.assertFalse(state["live_trading_enabled"])
        self.assertEqual(state["agents"][3]["status"], "PAPER_READY")
        self.assertEqual(state["summary"]["markets"], ["BTC/USD", "XAUUSD"])

    def test_blocks_when_live_flag_is_not_explicitly_false(self):
        snapshot = healthy_snapshot()
        snapshot["live_trading_enabled"] = True
        state = build_agent_state(snapshot)
        self.assertEqual(state["mode"], "SAFETY_BLOCKED")
        self.assertEqual(state["agents"][1]["status"], "BLOCKED")
        self.assertEqual(state["agents"][3]["status"], "BLOCKED")

    def test_unhealthy_gold_does_not_block_healthy_btc_market(self):
        snapshot = healthy_snapshot()
        snapshot["btc"]["strategy_signal"] = "BUY"
        snapshot["gold"]["data_quality"]["quality"] = "STALE"
        state = build_agent_state(snapshot)
        self.assertEqual(state["agents"][0]["status"], "READY")
        self.assertEqual(state["agents"][3]["status"], "PAPER_READY")
        btc = state["unified_decision"]["market_decisions"]["BTC"]
        gold = state["unified_decision"]["market_decisions"]["XAUUSD"]
        self.assertEqual(btc["decision"], "BUY")
        self.assertTrue(btc["approved_by_consensus"])
        self.assertEqual(gold["decision"], "HOLD")
        self.assertIn("MARKET_DATA_NOT_HEALTHY", gold["reason_codes"])

    def test_blocks_risk_pause_and_oversized_allocation(self):
        snapshot = healthy_snapshot()
        snapshot["btc"]["risk_pause_reasons"] = ["daily loss limit"]
        snapshot["gold"]["risk_limits"]["allocation_pct"] = 15
        state = build_agent_state(snapshot)
        self.assertEqual(state["agents"][1]["status"], "PASS")
        self.assertEqual(state["agents"][2]["status"], "READY")
        btc = state["unified_decision"]["market_decisions"]["BTC"]
        gold = state["unified_decision"]["market_decisions"]["XAUUSD"]
        self.assertIn("RISK_PAUSE_ACTIVE", btc["reason_codes"])
        self.assertIn("POSITION_SIZE_INVALID", gold["reason_codes"])

    def test_equity_is_derived_from_both_ledgers(self):
        snapshot = healthy_snapshot()
        snapshot["btc"]["equity_usd"] = 11
        snapshot["gold"]["equity_usd"] = 9
        state = build_agent_state(snapshot)
        equity = state["agents"][5]["metrics"]
        self.assertEqual(equity["equity_usd"], 20.0)
        self.assertEqual(equity["pnl_usd"], 0.0)

    def test_shared_wallet_is_source_of_truth_and_reports_scanned_markets(self):
        snapshot = healthy_snapshot()
        snapshot["shared_portfolio"] = {
            "initial_cash_usd": 100.0, "equity_usd": 102.5,
            "pnl_usd": 2.5, "closed_trades": 3,
        }
        snapshot["multi_asset_paper"] = {
            "markets_scanned": ["BTC/USD", "ETH/USD", "XAUUSD", "XAGUSD"],
        }
        # Per-market sleeve values intentionally differ; do not double count them.
        snapshot["btc"]["equity_usd"] = 110.0
        snapshot["gold"]["equity_usd"] = 20.0
        state = build_agent_state(snapshot)
        equity = state["agents"][5]["metrics"]
        scanner = state["agents"][0]["metrics"]
        self.assertTrue(equity["shared_wallet"])
        self.assertEqual(equity["equity_usd"], 102.5)
        self.assertEqual(equity["pnl_usd"], 2.5)
        self.assertEqual(equity["closed_trades"], 3)
        self.assertEqual(state["summary"]["markets"], ["BTC/USD", "XAUUSD", "ETH/USD", "XAGUSD"])
        self.assertEqual(scanner["markets_scanned"], ["BTC/USD", "ETH/USD", "XAUUSD", "XAGUSD"])

    def test_scanned_markets_are_explicit_watch_only_holds_without_signal(self):
        snapshot = healthy_snapshot()
        snapshot["multi_asset_paper"] = {
            "markets_scanned": ["ETH/USD", "XAGUSD", "XAUUSD"],
        }
        state = build_agent_state(snapshot)
        decisions = state["unified_decision"]["market_decisions"]
        self.assertIn("ETH/USD", decisions)
        self.assertIn("XAGUSD", decisions)
        self.assertEqual(decisions["ETH/USD"]["decision"], "HOLD")
        self.assertTrue(decisions["ETH/USD"]["watch_only"])
        self.assertFalse(decisions["ETH/USD"]["approved_by_consensus"])
        self.assertFalse(decisions["ETH/USD"]["live_orders_enabled"])
        self.assertIn("WATCH_ONLY_NO_CLOSED_CANDLE_SIGNAL",
                      decisions["ETH/USD"]["reason_codes"])
        self.assertEqual(state["summary"]["markets"],
                         ["BTC/USD", "XAUUSD", "ETH/USD", "XAGUSD"])

    def test_unified_consensus_emits_one_safe_decision_per_market(self):
        state = build_agent_state(healthy_snapshot())
        consensus = state["unified_decision"]
        self.assertEqual(consensus["model"], "SIX_AGENT_UNIFIED_CONSENSUS")
        self.assertEqual(consensus["portfolio_decision"], "HOLD")
        self.assertEqual(consensus["market_decisions"]["BTC"]["decision"], "HOLD")
        self.assertEqual(consensus["market_decisions"]["XAUUSD"]["decision"], "HOLD")
        self.assertFalse(consensus["orders_submitted"])

    def test_unified_consensus_accepts_explicit_signal_only_when_all_gates_pass(self):
        snapshot = healthy_snapshot()
        snapshot["btc"]["strategy_signal"] = "BUY"
        state = build_agent_state(snapshot)
        decision = state["unified_decision"]["market_decisions"]["BTC"]
        self.assertEqual(decision["decision"], "BUY")
        self.assertTrue(decision["approved_by_consensus"])
        self.assertFalse(decision["live_orders_enabled"])

    def test_unified_consensus_forces_hold_when_any_gate_fails(self):
        snapshot = healthy_snapshot()
        snapshot["btc"]["strategy_signal"] = "BUY"
        snapshot["btc"]["risk_pause_reasons"] = ["daily loss limit"]
        state = build_agent_state(snapshot)
        decision = state["unified_decision"]["market_decisions"]["BTC"]
        self.assertEqual(decision["decision"], "HOLD")
        self.assertIn("RISK_PAUSE_ACTIVE", decision["reason_codes"])

    def test_six_agent_gate_approves_only_valid_paper_buy(self):
        context = {
            "signal": "BUY", "timestamp": 100, "price": 50000,
            "risk_paused": False, "allocation_pct": 10.0,
        }
        self.assertTrue(authorize_paper_entry("BTC", True, context))
        self.assertFalse(authorize_paper_entry("BTC", False, context))
        blocked = dict(context, risk_paused=True)
        self.assertFalse(authorize_paper_entry("BTC", True, blocked))
        oversized = dict(context, allocation_pct=10.01)
        self.assertFalse(authorize_paper_entry("BTC", True, oversized))
        self.assertFalse(authorize_paper_entry("BTC", True, dict(context, signal="SELL")))

    def test_research_report_is_attached_as_advisory_only(self):
        report = {
            "mode": "READ_ONLY_PAPER_RESEARCH",
            "paper_only": True,
            "live_trading_enabled": False,
            "comparison": {"status": "INSUFFICIENT_FORWARD_SAMPLE"},
            "markets": {
                "BTC": {"review_status": "COLLECTING_SAMPLE", "next_action": "CONTINUE_PAPER_TEST", "closed_trades": 2},
                "XAUUSD": {"review_status": "COLLECTING_SAMPLE", "next_action": "CONTINUE_PAPER_TEST", "closed_trades": 1},
            },
            "governance": {
                "strategy_auto_changes": False, "ledger_mutation": False,
                "risk_limit_changes": False, "dashboard_modified": False,
                "orders_submitted": False,
            },
        }
        state = build_agent_state(healthy_snapshot(), research_report=report)
        advisory = state["unified_decision"]["research_advisory"]
        self.assertEqual(advisory["status"], "INSUFFICIENT_FORWARD_SAMPLE")
        self.assertFalse(advisory["changes_strategy"])
        self.assertFalse(advisory["execution_authority"])
        self.assertEqual(state["unified_decision"]["market_decisions"]["BTC"]["decision"], "HOLD")

    def test_unsafe_research_report_is_rejected_and_cannot_change_consensus(self):
        report = {
            "mode": "READ_ONLY_PAPER_RESEARCH", "paper_only": True,
            "live_trading_enabled": True,
            "markets": {"BTC": {}, "XAUUSD": {}},
            "governance": {"strategy_auto_changes": True, "orders_submitted": False},
        }
        report["live_trading_enabled"] = False
        report["governance"].update({
            "strategy_auto_changes": False, "ledger_mutation": True,
            "risk_limit_changes": False, "dashboard_modified": False,
        })
        state = build_agent_state(healthy_snapshot(), research_report=report)
        self.assertEqual(state["unified_decision"]["research_advisory"]["status"], "REJECTED_UNSAFE_REPORT")
        self.assertEqual(state["unified_decision"]["portfolio_decision"], "HOLD")

    def test_malformed_comparison_is_rejected(self):
        report = {
            "mode": "READ_ONLY_PAPER_RESEARCH",
            "paper_only": True,
            "live_trading_enabled": False,
            "comparison": [],
            "markets": {"BTC": {}, "XAUUSD": {}},
            "governance": {
                "strategy_auto_changes": False, "ledger_mutation": False,
                "risk_limit_changes": False, "dashboard_modified": False,
                "orders_submitted": False,
            },
        }
        state = build_agent_state(healthy_snapshot(), research_report=report)
        self.assertEqual(
            state["unified_decision"]["research_advisory"]["status"],
            "INVALID_REPORT",
        )

    def test_atomic_output_is_valid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state" / "agents.json"
            payload = build_agent_state(healthy_snapshot())
            atomic_write_json(path, payload)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(loaded["agents"]), 6)


if __name__ == "__main__":
    unittest.main()
