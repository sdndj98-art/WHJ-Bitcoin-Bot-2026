import json
import tempfile
import unittest
from pathlib import Path

from main import load_shared_paper_portfolio
from shared_paper_portfolio import SUPPORTED_STRATEGIES


class SharedPaperReportingTests(unittest.TestCase):
    def test_report_exposes_one_100_dollar_pool_across_seven_strategy_rows(self):
        rows = [{
            "asset": "BTC", "strategy": name, "equity_usd": 100.0 / 7,
            "return_pct": 0.0, "closed_trades": 0, "max_drawdown_pct": 0.0,
            "paused": False, "paused_for_drawdown": False,
            "daily_loss_paused": False, "paused_for_loss_streak": False,
        } for name in SUPPORTED_STRATEGIES]
        snapshot = {
            "paper_only": True, "live_trading_enabled": False,
            "shared_portfolio": {
                "mode": "PAPER_ONLY", "live_trading_enabled": False,
                "initial_cash_usd": 100.0, "equity_usd": 100.0,
                "cash_usd": 100.0, "closed_trades": 0,
                "fees_paid_usd": 0.0, "open_positions": [],
            },
            "strategies": rows,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            portfolio, summary = load_shared_paper_portfolio(path)
        self.assertEqual(portfolio["mode"], "SHARED_100USD_PAPER_ONLY")
        self.assertEqual(len(portfolio["accounts"]), 7)
        self.assertAlmostEqual(sum(a["initial_cash_usd"] for a in portfolio["accounts"].values()), 100.0)
        self.assertAlmostEqual(sum(a["equity_after_estimated_exit_costs_usd"] for a in portfolio["accounts"].values()), 100.0)
        self.assertEqual(summary["initial_cash_usd"], 100.0)
        self.assertFalse(summary["open_position"])

    def test_refuses_unsafe_or_wrong_capital_snapshot(self):
        unsafe = {"paper_only": False, "live_trading_enabled": False}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_shared_paper_portfolio(path)


    def test_legacy_snapshot_waits_without_creating_an_independent_wallet(self):
        legacy = {"paper_only": True, "live_trading_enabled": False, "btc": {}, "gold": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            portfolio, summary = load_shared_paper_portfolio(path)
        self.assertEqual(portfolio["mode"], "WAITING_FOR_SHARED_100USD_LEDGER")
        self.assertEqual(portfolio["accounts"], {})
        self.assertEqual(summary, {})

    def test_missing_snapshot_does_not_create_fallback_account(self):
        with tempfile.TemporaryDirectory() as directory:
            portfolio, summary = load_shared_paper_portfolio(Path(directory) / "missing.json")
        self.assertEqual(portfolio["accounts"], {})
        self.assertEqual(summary, {})


if __name__ == "__main__":
    unittest.main()
