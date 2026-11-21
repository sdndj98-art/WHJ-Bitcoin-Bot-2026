import unittest
from datetime import datetime, timezone

from multi_asset_paper_runner import (
    _market_position_id, _risk_state, _seed_market_state,
    MAX_GROSS_EXPOSURE, MAX_OPEN_POSITIONS, TRADE_ALLOCATION,
)
from shared_paper_portfolio import SUPPORTED_STRATEGIES


class FakeBook:
    def __init__(self, cash):
        self.state = {"cash_usd": cash, "positions": {}}
        self.cash = cash

    def snapshot(self, marks):
        return {"cash_usd": self.cash, "open_positions": []}


class MultiAssetPaperRunnerTests(unittest.TestCase):
    def test_seeds_each_strategy_at_the_latest_completed_candle(self):
        rows = [[i * 3600, 100, 101, 99, 100 + i, 0, 1] for i in range(250)]
        state = _seed_market_state(rows)
        self.assertEqual(set(state), set(SUPPORTED_STRATEGIES))
        self.assertEqual(
            {item["last_timestamp"] for item in state.values()},
            {rows[-1][0]},
        )
        self.assertTrue(all(len(item["recent_closes"]) == 200 for item in state.values()))

    def test_position_ids_are_deterministic_and_market_specific(self):
        first = _market_position_id("ETH/USD", "ema_trend")
        second = _market_position_id("XAUUSD", "ema_trend")
        self.assertEqual(first, "multi-ETH_USD-ema_trend")
        self.assertNotEqual(first, second)

    def test_allocation_and_exposure_limits_are_conservative(self):
        self.assertEqual(TRADE_ALLOCATION, 0.02)
        self.assertLessEqual(MAX_GROSS_EXPOSURE, 0.50)
        self.assertLessEqual(MAX_OPEN_POSITIONS, 8)

    def test_daily_loss_and_drawdown_pauses_are_enforced(self):
        timestamp = int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp())
        book = FakeBook(96.0)
        risk = {
            "peak_equity_usd": 110.0,
            "daily_bucket": "2026-11-21",
            "daily_start_equity_usd": 100.0,
            "daily_loss_paused": False,
            "drawdown_paused": False,
        }
        updated = _risk_state(book, {}, risk, timestamp)
        self.assertTrue(updated["daily_loss_paused"])
        self.assertTrue(updated["drawdown_paused"])
        self.assertFalse(updated.get("live_trading_enabled", False))


if __name__ == "__main__":
    unittest.main()
