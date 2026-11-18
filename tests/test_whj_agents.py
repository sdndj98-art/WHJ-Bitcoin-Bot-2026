import json
import tempfile
import unittest
from pathlib import Path

from whj_agents import build_agent_state, atomic_write_json


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
        "btc": dict(sleeve),
        "gold": dict(sleeve),
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

    def test_blocks_stale_or_unhealthy_feed(self):
        snapshot = healthy_snapshot()
        snapshot["gold"]["data_quality"]["quality"] = "STALE"
        state = build_agent_state(snapshot)
        self.assertEqual(state["agents"][0]["status"], "WAITING_DATA")
        self.assertEqual(state["agents"][3]["status"], "BLOCKED")

    def test_blocks_risk_pause_and_oversized_allocation(self):
        snapshot = healthy_snapshot()
        snapshot["btc"]["risk_pause_reasons"] = ["daily loss limit"]
        snapshot["gold"]["risk_limits"]["allocation_pct"] = 15
        state = build_agent_state(snapshot)
        self.assertEqual(state["agents"][1]["status"], "BLOCKED")
        self.assertEqual(state["agents"][2]["status"], "BLOCKED")

    def test_equity_is_derived_from_both_ledgers(self):
        snapshot = healthy_snapshot()
        snapshot["btc"]["equity_usd"] = 11
        snapshot["gold"]["equity_usd"] = 9
        state = build_agent_state(snapshot)
        equity = state["agents"][5]["metrics"]
        self.assertEqual(equity["equity_usd"], 20.0)
        self.assertEqual(equity["pnl_usd"], 0.0)

    def test_atomic_output_is_valid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state" / "agents.json"
            payload = build_agent_state(healthy_snapshot())
            atomic_write_json(path, payload)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(loaded["agents"]), 6)


if __name__ == "__main__":
    unittest.main()
