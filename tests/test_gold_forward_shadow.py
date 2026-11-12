import unittest
from gold_forward_shadow import (
    STRATEGIES, advance_gold_shadow_state, seed_gold_shadow_state,
    write_state_atomically,
)
import tempfile
from pathlib import Path
import json


def rising_bars(count=400):
    rows = []
    start = 1_700_000_000_000
    for i in range(count):
        close = 1800.0 + i * 2.0
        rows.append({
            "timestamp": start + i * 86_400_000,
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
        })
    return rows


class GoldForwardShadowTests(unittest.TestCase):
    def test_seed_uses_history_only_for_warmup_and_books_no_historical_trades(self):
        bars = rising_bars()
        for strategy in STRATEGIES:
            state = seed_gold_shadow_state(bars, strategy)
            self.assertEqual(state["last_processed_timestamp"], bars[-1]["timestamp"])
            self.assertEqual(state["completed_trades"], 0)
            self.assertEqual(state["trade_log"], [])
            self.assertEqual(state["historical_trades_booked"], 0)
            self.assertEqual(state["equity_usd"], 1000.0)
            self.assertFalse(state["live_trading_eligible"])

    def test_new_daily_bar_executes_prior_close_signal_only_once(self):
        bars = rising_bars()
        state = seed_gold_shadow_state(bars, "ema50_200")
        next_close = bars[-1]["close"] + 2.0
        next_bar = {
            "timestamp": bars[-1]["timestamp"] + 86_400_000,
            "open": next_close - 0.5,
            "high": next_close + 2.0,
            "low": next_close - 2.0,
            "close": next_close,
        }
        updated = advance_gold_shadow_state(bars + [next_bar], state)
        self.assertEqual(updated["last_processed_timestamp"], next_bar["timestamp"])
        self.assertGreater(updated["units"], 0)
        self.assertEqual(updated["completed_trades"], 0)
        snapshot = json.dumps(updated, sort_keys=True)
        repeated = advance_gold_shadow_state(bars + [next_bar], updated)
        self.assertEqual(json.dumps(repeated, sort_keys=True), snapshot)

    def test_stop_first_when_daily_bar_touches_stop_and_target(self):
        bars = rising_bars()
        state = seed_gold_shadow_state(bars, "ema50_200")
        close = bars[-1]["close"] + 2.0
        entry_bar = {
            "timestamp": bars[-1]["timestamp"] + 86_400_000,
            "open": close - 0.5, "high": close + 2, "low": close - 2, "close": close,
        }
        state = advance_gold_shadow_state(bars + [entry_bar], state)
        self.assertGreater(state["units"], 0)
        stop = state["stop_price"]
        target = state["target_price"]
        collision = {
            "timestamp": entry_bar["timestamp"] + 86_400_000,
            "open": (stop + target) / 2,
            "high": target + 1,
            "low": stop - 1,
            "close": (stop + target) / 2,
        }
        state = advance_gold_shadow_state(bars + [entry_bar, collision], state)
        self.assertEqual(state["completed_trades"], 1)
        self.assertEqual(state["trade_log"][-1]["reason"], "stop_first_same_bar")

    def test_rejects_missing_checkpoint_instead_of_reseeding(self):
        bars = rising_bars()
        state = seed_gold_shadow_state(bars, "ema50_200")
        with self.assertRaisesRegex(ValueError, "Checkpoint candle is absent"):
            advance_gold_shadow_state(bars[1:], state)

    def test_rejects_duplicate_or_out_of_order_timestamps(self):
        bars = rising_bars()
        state = seed_gold_shadow_state(bars, "ema50_200")
        malformed = bars + [dict(bars[-1])]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            advance_gold_shadow_state(malformed, state)

    def test_atomic_state_write_preserves_valid_json(self):
        state = seed_gold_shadow_state(rising_bars(), "ema50_200")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gold" / "state.json"
            write_state_atomically(state, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["strategy"], "ema50_200")
            self.assertEqual(saved["completed_trades"], 0)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_rejects_unknown_strategy_and_invalid_market_data(self):
        bars = rising_bars()
        with self.assertRaisesRegex(ValueError, "Unknown gold shadow strategy"):
            seed_gold_shadow_state(bars, "unknown")
        bad = [dict(row) for row in bars]
        bad[-1]["high"] = 1.0
        with self.assertRaisesRegex(ValueError, "Impossible daily OHLC"):
            seed_gold_shadow_state(bad, "ema50_200")


if __name__ == "__main__":
    unittest.main()
