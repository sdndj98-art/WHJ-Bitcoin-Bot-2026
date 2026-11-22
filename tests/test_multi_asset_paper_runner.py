import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from multi_asset_paper_runner import (
    _crypto_market, _ensure_market_strategy_state, _entry_block_reason, _is_eligible_crypto_pair, _market_position_id, _risk_state, _seed_market_state,
    MAX_GROSS_EXPOSURE, MAX_OPEN_POSITIONS, TRADE_ALLOCATION,
)
from shared_paper_portfolio import SUPPORTED_STRATEGIES
from shared_paper_runner import strategy_signal


class FakeBook:
    def __init__(self, cash):
        self.state = {"cash_usd": cash, "positions": {}}
        self.cash = cash

    def snapshot(self, marks):
        return {"cash_usd": self.cash, "open_positions": []}


class MultiAssetPaperRunnerTests(unittest.TestCase):
    def test_seeds_warmup_and_leaves_latest_completed_candle_pending(self):
        rows = [[i * 3600, 100, 101, 99, 100 + i, 0, 1] for i in range(250)]
        state = _seed_market_state(rows)
        self.assertEqual(set(state), set(SUPPORTED_STRATEGIES))
        self.assertEqual(
            {item["last_timestamp"] for item in state.values()},
            {rows[-2][0]},
        )
        self.assertTrue(all(len(item["recent_closes"]) == 200 for item in state.values()))
        self.assertTrue(all(item["seeded_pending_latest"] for item in state.values()))
        self.assertEqual(state["sma_trend"]["recent_closes"][-1], rows[-2][4])

    def test_missing_new_strategy_cursor_is_seeded_without_resetting_existing(self):
        rows = [[i * 3600, 100, 101, 99, 100 + i, 0, 1] for i in range(250)]
        state = _seed_market_state(rows)
        state["sma_trend"]["last_timestamp"] = 12345
        del state["compound_momentum"]
        added = _ensure_market_strategy_state(state, rows)
        self.assertEqual(added, ["compound_momentum"])
        self.assertEqual(state["sma_trend"]["last_timestamp"], 12345)
        self.assertEqual(state["compound_momentum"]["last_timestamp"], rows[-2][0])

    def test_daily_sma_trend_can_signal_after_20_closed_bars(self):
        history = [100.0] * 19 + [101.0]
        want_long, want_flat = strategy_signal("sma_trend", history)
        self.assertTrue(want_long)
        self.assertFalse(want_flat)

    def test_short_history_crypto_can_mark_existing_position_but_cannot_enter(self):
        rows = [[i * 3600, 100, 101, 99, 100 + i, 0, 1] for i in range(12)]
        with patch("multi_asset_paper_runner.fetch_json", return_value={"XBTUSD": {}}), \
             patch("multi_asset_paper_runner.normalize_kraken_ohlc", return_value=(rows, "HEALTHY")):
            market = _crypto_market(
                {"altname": "XBTUSD", "base": "XBT", "symbol": "XBT/USD"},
                12 * 3600,
            )
        self.assertEqual(market["symbol"], "BTC/USD")
        self.assertEqual(market["price"], rows[-1][4])
        self.assertFalse(market["strategy_history_ready"])
        self.assertFalse(market["trade_allowed"])

    def test_universe_excludes_bitcoin_alias_and_fiat_fx_pairs(self):
        self.assertTrue(_is_eligible_crypto_pair({"base": "ETH", "quote": "USD"}))
        self.assertFalse(_is_eligible_crypto_pair({"base": "XBT", "quote": "USD"}))
        self.assertFalse(_is_eligible_crypto_pair({"base": "BTC", "quote": "USD"}))
        self.assertFalse(_is_eligible_crypto_pair({"base": "EUR", "quote": "USD"}))
        self.assertTrue(_is_eligible_crypto_pair({"base": "ETH", "quote": "USDT"}))
        self.assertTrue(_is_eligible_crypto_pair({"base": "ETH", "quote": "USDC"}))

    def test_universe_excludes_stablecoin_base_pairs(self):
        for base in ("USDG", "USDP", "FDUSD", "PYUSD", "USDE", "USDD"):
            self.assertFalse(_is_eligible_crypto_pair({"base": base, "quote": "USDC"}))
        self.assertTrue(_is_eligible_crypto_pair({"base": "ETH", "quote": "USDC"}))

    def test_position_ids_are_deterministic_and_market_specific(self):
        first = _market_position_id("ETH/USD", "ema_trend")
        second = _market_position_id("XAUUSD", "ema_trend")
        self.assertEqual(first, "multi-ETH_USD-ema_trend")
        self.assertNotEqual(first, second)

    def test_entry_block_reason_identifies_binding_constraint(self):
        # Idle cash can coexist with a reached gross-exposure cap.
        self.assertEqual(_entry_block_reason(2.0, 0.05, 50.0), "MAX_GROSS_EXPOSURE")
        self.assertEqual(_entry_block_reason(2.0, 50.0, 0.25), "INSUFFICIENT_CASH")
        self.assertEqual(_entry_block_reason(0.4, 50.0, 50.0), "MIN_TRADE_SIZE")
        self.assertIsNone(_entry_block_reason(2.0, 5.0, 50.0))

    def test_allocation_and_exposure_limits_are_conservative(self):
        self.assertEqual(TRADE_ALLOCATION, 0.02)
        self.assertLessEqual(MAX_GROSS_EXPOSURE, 0.50)
        self.assertIsNone(MAX_OPEN_POSITIONS)  # cumulative trades are unbounded; risk/cash caps still apply

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
