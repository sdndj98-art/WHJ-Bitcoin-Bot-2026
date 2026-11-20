import tempfile
import unittest
from pathlib import Path

from multi_asset_paper import process_snapshot, atomic_write_json, load_state


def snap(t, signals, healthy=None, quotes=None):
    return {
        "quotes": quotes or {
            "BTCUSD": {"bid": 99.0, "ask": 100.0, "timestamp": t,
                      "contract_size": 1, "quote_to_usd": 1},
            "XAUUSD": {"bid": 1990.0, "ask": 2000.0, "timestamp": t,
                       "contract_size": 1, "quote_to_usd": 1},
        },
        "signals": signals,
        "healthy_symbols": ["BTCUSD", "XAUUSD"] if healthy is None else healthy,
    }


class MultiAssetPaperTests(unittest.TestCase):
    def test_market_sleeves_are_independent_and_open_paper_positions(self):
        state = process_snapshot(snap(1000, {"BTCUSD": "BUY", "XAUUSD": "BUY"}),
                                 now=1000)
        self.assertEqual(state["summary"]["open_positions"], 2)
        btc = state["summary"]["markets"]["BTCUSD"]
        gold = state["summary"]["markets"]["XAUUSD"]
        self.assertLess(btc["cash_usd"], 1000)
        self.assertLess(gold["cash_usd"], 1000)
        self.assertFalse(state["live_trading_enabled"])
        self.assertFalse(state["orders_submitted"])

    def test_unhealthy_market_cannot_enter(self):
        state = process_snapshot(snap(1000, {"BTCUSD": "BUY"}, healthy=[]), now=1000)
        self.assertFalse(state["summary"]["markets"]["BTCUSD"]["position_open"])
        self.assertEqual(state["events"][0]["reason"], "DATA_NOT_HEALTHY")

    def test_sell_closes_position_and_books_costs(self):
        state = process_snapshot(snap(1000, {"BTCUSD": "BUY"}), now=1000)
        profitable = snap(1100, {"BTCUSD": "SELL"}, quotes={
            "BTCUSD": {"bid": 102.0, "ask": 103.0, "timestamp": 1100,
                      "contract_size": 1, "quote_to_usd": 1}
        })
        state = process_snapshot(profitable, state, now=1200)
        btc = state["summary"]["markets"]["BTCUSD"]
        self.assertFalse(btc["position_open"])
        self.assertEqual(btc["closed_trades"], 1)
        self.assertGreater(btc["realized_pnl_usd"], 0)
        self.assertGreater(btc["fees_paid_usd"], 0)

    def test_duplicate_quote_is_ignored(self):
        state = process_snapshot(snap(1000, {"BTCUSD": "BUY"}), now=1000)
        state = process_snapshot(snap(1000, {"BTCUSD": "BUY"}), state, now=1000)
        self.assertEqual(state["events"][0]["reason"], "DUPLICATE_OR_OLD_QUOTE")
        self.assertEqual(state["summary"]["markets"]["BTCUSD"]["position_open"], True)

    def test_invalid_quote_and_contract_metadata_rejected(self):
        bad = snap(1000, {"BTCUSD": "BUY"})
        bad["quotes"]["BTCUSD"]["ask"] = 98
        with self.assertRaisesRegex(ValueError, "ask must be"):
            process_snapshot(bad, now=1000)
        bad = snap(1000, {"BTCUSD": "BUY"})
        del bad["quotes"]["BTCUSD"]["contract_size"]
        with self.assertRaises(ValueError):
            process_snapshot(bad, now=1000)

    def test_stale_quote_is_skipped_before_entry(self):
        state = process_snapshot(snap(800, {"BTCUSD": "BUY"}), now=1000)
        self.assertEqual(state["events"][0]["reason"], "STALE_QUOTE")
        self.assertEqual(state["summary"]["open_positions"], 0)

    def test_stale_quote_does_not_mark_existing_position(self):
        state = process_snapshot(snap(1000, {"BTCUSD": "BUY"}), now=1000)
        stale = snap(800, {"BTCUSD": "SELL"})
        state = process_snapshot(stale, state, now=1200)
        btc = state["summary"]["markets"]["BTCUSD"]
        self.assertEqual(state["events"][0]["reason"], "STALE_QUOTE")
        self.assertTrue(btc["position_open"])
        self.assertAlmostEqual(
            btc["equity_usd"],
            btc["cash_usd"] + state["markets"]["BTCUSD"]["position"]["entry_notional_usd"],
        )

    def test_risk_limits_cannot_exceed_100_percent(self):
        with self.assertRaisesRegex(ValueError, "risk limits"):
            process_snapshot(snap(1000, {"BTCUSD": "HOLD"}), now=1000,
                             max_daily_loss_pct=101)

    def test_state_persists_atomically(self):
        state = process_snapshot(snap(1000, {"BTCUSD": "BUY"}), now=1000)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            atomic_write_json(path, state)
            loaded = load_state(path)
            self.assertEqual(loaded["summary"]["open_positions"], 1)
            self.assertFalse(loaded["live_trading_enabled"])


if __name__ == "__main__":
    unittest.main()
