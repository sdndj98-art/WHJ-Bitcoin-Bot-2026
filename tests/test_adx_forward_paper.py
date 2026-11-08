import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adx_forward_paper import process_native_bars


def make_bars(count=300):
    rows = []
    price = 100.0
    for i in range(count):
        price *= 1.0015 if (i // 18) % 2 == 0 else 0.9992
        rows.append({
            "timestamp": i * 4 * 3_600_000,
            "open": price * 0.999,
            "high": price * 1.004,
            "low": price * 0.996,
            "close": price,
            "volume": 10.0,
        })
    return rows


class AdxForwardPaperTests(unittest.TestCase):
    def test_first_run_seeds_watermark_without_historical_trades(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            result = process_native_bars(make_bars(), 20.0, 4, path)
            state = json.loads(path.read_text())
            self.assertTrue(result["seeded_without_historical_trades"])
            self.assertEqual(result["closed_trades"], 0)
            self.assertEqual(state["last_timestamp"], make_bars()[-1]["timestamp"])
            self.assertEqual(state["cash"], 500.0)

    def test_reprocessing_same_bars_never_duplicates_or_creates_trades(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            bars = make_bars()
            process_native_bars(bars, 20.0, 4, path)
            before = path.read_text()
            result = process_native_bars(bars, 20.0, 4, path)
            self.assertEqual(result["processed_new_bars"], 0)
            self.assertEqual(path.read_text(), before)


    def test_new_forward_bars_execute_once_and_exit_on_baseline_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            process_native_bars(make_bars(), 20.0, 4, path)

            extended = make_bars(301)
            baseline = [True] * len(extended)
            confirmed = [False] * len(extended)
            confirmed[-2] = True
            with patch("adx_forward_paper._build_sleeve_signals", return_value=(baseline, confirmed)):
                opened = process_native_bars(extended, 20.0, 4, path)

            self.assertEqual(opened["processed_new_bars"], 1)
            self.assertTrue(opened["open_position"])
            self.assertEqual(opened["closed_trades"], 0)
            cash_after_entry = json.loads(path.read_text())["cash"]
            self.assertLess(cash_after_entry, 500.0)

            extended = make_bars(302)
            baseline = [True] * len(extended)
            baseline[-2] = False
            confirmed = [False] * len(extended)
            with patch("adx_forward_paper._build_sleeve_signals", return_value=(baseline, confirmed)):
                closed = process_native_bars(extended, 20.0, 4, path)

            self.assertEqual(closed["processed_new_bars"], 1)
            self.assertFalse(closed["open_position"])
            self.assertEqual(closed["closed_trades"], 1)
            saved_after_close = path.read_text()
            with patch("adx_forward_paper._build_sleeve_signals", return_value=(baseline, confirmed)):
                repeated = process_native_bars(extended, 20.0, 4, path)
            self.assertEqual(repeated["processed_new_bars"], 0)
            self.assertEqual(repeated["closed_trades"], 1)
            self.assertEqual(path.read_text(), saved_after_close)

    def test_native_gap_is_rejected_without_changing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            bars = make_bars()
            process_native_bars(bars, 20.0, 4, path)
            before = path.read_text()
            gapped = bars[:150] + bars[151:]
            with self.assertRaisesRegex(ValueError, "contain a gap"):
                process_native_bars(gapped, 20.0, 4, path)
            self.assertEqual(path.read_text(), before)


    def test_future_or_missing_watermark_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            bars = make_bars()
            process_native_bars(bars, 20.0, 4, path)
            state = json.loads(path.read_text())
            state["last_timestamp"] += 4 * 3_600_000
            path.write_text(json.dumps(state))
            before = path.read_text()
            with self.assertRaisesRegex(ValueError, "watermark is absent"):
                process_native_bars(bars, 20.0, 4, path)
            self.assertEqual(path.read_text(), before)


    def test_malformed_trade_history_is_rejected_without_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            bars = make_bars()
            process_native_bars(bars, 20.0, 4, path)
            state = json.loads(path.read_text())
            state["trades"] = [{"side": "BUY", "pnl_usd": 12.0}]
            path.write_text(json.dumps(state))
            before = path.read_text()
            with self.assertRaisesRegex(ValueError, "trade record is invalid"):
                process_native_bars(bars, 20.0, 4, path)
            self.assertEqual(path.read_text(), before)

    def test_profitable_ledger_above_starting_cash_remains_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            bars = make_bars()
            process_native_bars(bars, 20.0, 4, path)
            state = json.loads(path.read_text())
            state["cash"] = 550.0
            state["peak_equity"] = 550.0
            state["daily_start_equity"] = 550.0
            path.write_text(json.dumps(state))
            result = process_native_bars(bars, 20.0, 4, path)
            self.assertEqual(result["equity_usd"], 550.0)
            self.assertEqual(result["processed_new_bars"], 0)

    def test_corrupt_state_is_not_silently_reseeded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "isolated.json"
            path.write_text("{broken")
            with self.assertRaisesRegex(ValueError, "refusing to reset"):
                process_native_bars(make_bars(), 20.0, 4, path)

    def test_threshold_and_timeframe_are_fixed_to_supported_values(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                process_native_bars(make_bars(), 17.0, 4, Path(directory) / "x.json")
            with self.assertRaises(ValueError):
                process_native_bars(make_bars(), 20.0, 5, Path(directory) / "y.json")


if __name__ == "__main__":
    unittest.main()
