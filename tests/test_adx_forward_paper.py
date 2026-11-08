import json
import tempfile
import unittest
from pathlib import Path

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
