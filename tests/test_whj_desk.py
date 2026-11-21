import unittest
from whj_desk import build_desk

class DeskTests(unittest.TestCase):
    def test_eight_read_only_roles_and_paper_guard(self):
        snap={"paper_only":True,"live_trading_enabled":False,"multi_asset_paper":{"markets_scanned":["BTC/USD","XAUUSD"],"strategy_diagnostics":{"strat":{"entry_signals":2,"exit_signals":1,"blocked":1,"opened":0}},"events_this_run":[],"shared_portfolio":{"equity_usd":99.9,"pnl_usd":-0.1,"open_positions":[],"closed_trades":[]}}}
        state=build_desk(snap,generated_at="fixed")
        self.assertEqual(state["summary"]["agent_count"],8)
        self.assertEqual(len(state["agents"]),8)
        self.assertFalse(state["live_trading_enabled"])
        self.assertFalse(state["orders_submitted"])
        self.assertEqual(state["summary"]["entry_signals"],2)
        self.assertEqual(state["agents"][4]["status"],"DATA_UNAVAILABLE")
        self.assertEqual(state["agents"][6]["status"],"DATA_UNAVAILABLE")
    def test_unsafe_snapshot_is_blocked(self):
        state=build_desk({"paper_only":True,"live_trading_enabled":True})
        self.assertEqual(state["mode"],"SAFETY_BLOCKED")
        self.assertFalse(state["orders_submitted"])
if __name__=="__main__": unittest.main()
