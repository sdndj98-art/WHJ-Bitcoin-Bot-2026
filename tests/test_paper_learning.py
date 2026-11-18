import unittest

from paper_learning import build_report


def snapshot():
    sleeve = {
        "strategy": "example",
        "status": "PAPER_RUNNING",
        "initial_equity_usd": 10.0,
        "equity_usd": 10.0,
        "max_drawdown_pct": 0.0,
    }
    return {
        "paper_only": True,
        "live_trading_enabled": False,
        "btc": dict(sleeve),
        "gold": dict(sleeve),
    }


def ledger(pnls):
    return {"trades": [
        {"pnl_usd": value, "side": "SELL", "result": "WIN" if value > 0 else "LOSS"}
        for value in pnls
    ]}


class PaperLearningTests(unittest.TestCase):
    def test_empty_ledgers_wait_for_forward_sample(self):
        report = build_report(snapshot(), ledger([]), ledger([]), generated_at="fixed")
        self.assertEqual(report["comparison"]["status"], "INSUFFICIENT_FORWARD_SAMPLE")
        self.assertEqual(report["markets"]["BTC"]["review_status"], "COLLECTING_SAMPLE")
        self.assertEqual(report["markets"]["BTC"]["win_rate_pct"], None)

    def test_metrics_are_calculated_from_closed_ledger_trades(self):
        report = build_report(snapshot(), ledger([2.0, -1.0, 1.0]), ledger([1.0, -0.5]))
        btc = report["markets"]["BTC"]
        self.assertEqual(btc["closed_trades"], 3)
        self.assertEqual(btc["wins"], 2)
        self.assertEqual(btc["losses"], 1)
        self.assertEqual(btc["net_closed_trade_pnl_usd"], 2.0)
        self.assertEqual(btc["profit_factor"], 3.0)

    def test_human_review_gate_requires_ten_trades_in_both_markets(self):
        enough = [1.0, -0.25] * 5
        report = build_report(snapshot(), ledger(enough), ledger(enough))
        self.assertTrue(report["comparison"]["both_markets_have_minimum_sample"])
        self.assertEqual(report["comparison"]["status"], "DESCRIPTIVE_SAMPLE_AVAILABLE")
        self.assertEqual(report["markets"]["BTC"]["next_action"], "HUMAN_REVIEW_ONLY")

    def test_negative_performance_flags_human_review_not_auto_tuning(self):
        enough = [-0.1] * 10
        report = build_report(snapshot(), ledger(enough), ledger(enough))
        self.assertEqual(report["markets"]["BTC"]["review_status"], "REVIEW_REQUIRED")
        self.assertFalse(report["governance"]["strategy_auto_changes"])
        self.assertFalse(report["governance"]["ledger_mutation"])

    def test_live_or_non_paper_snapshot_is_rejected(self):
        data = snapshot()
        data["live_trading_enabled"] = True
        with self.assertRaises(ValueError):
            build_report(data, ledger([]), ledger([]))

    def test_invalid_non_finite_trade_is_rejected(self):
        with self.assertRaises(ValueError):
            build_report(snapshot(), ledger([float("nan")]), ledger([]))


if __name__ == "__main__":
    unittest.main()
