import tempfile
import unittest
from pathlib import Path

from paper_account import update_paper_account


class StrategyHealthIntegrationTests(unittest.TestCase):
    def test_paper_account_exposes_isolated_health_diagnostic(self):
        candles = [
            [index * 3600, 0, 0, 0, 100.0 + index * 0.25, 1]
            for index in range(220)
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = update_paper_account(
                candles,
                state_path=str(Path(directory) / "sma_health.json"),
                initial_cash=1000.0,
                strategy="sma_trend",
            )

        health = result["strategy_health"]
        self.assertEqual(result["strategy"], "sma_trend")
        self.assertEqual(health["status"], "INSUFFICIENT_DATA")
        self.assertEqual(health["completed_trades"], result["completed_trades"])
        self.assertFalse(health["live_trading_approved"])
        self.assertFalse(health["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
