import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gold_forward_shadow_runner import run_gold_shadow


def bars(n=400):
    rows = []
    start = 1_700_000_000_000
    for i in range(n):
        close = 1800.0 + i * 2.0
        rows.append({
            "timestamp": start + i * 86_400_000,
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
        })
    return rows


class GoldForwardShadowRunnerTests(unittest.TestCase):
    def test_first_run_seeds_two_separate_ledgers_without_trades(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_gold_shadow(folder, bars=bars())
            self.assertEqual(len(result["summaries"]), 2)
            self.assertFalse(result["live_orders"])
            for item in result["summaries"]:
                self.assertEqual(item["action"], "seeded_no_historical_trades")
                saved = json.loads(Path(item["state_file"]).read_text(encoding="utf-8"))
                self.assertEqual(saved["completed_trades"], 0)
                self.assertEqual(saved["historical_trades_booked"], 0)
                self.assertFalse(saved["live_trading_eligible"])

    def test_second_run_is_idempotent_without_new_closed_candles(self):
        data = bars()
        with tempfile.TemporaryDirectory() as folder:
            run_gold_shadow(folder, bars=data)
            first = run_gold_shadow(folder, bars=data)
            self.assertTrue(all(x["action"] == "unchanged" for x in first["summaries"]))

    def test_missing_checkpoint_fails_closed_and_does_not_reseed(self):
        data = bars()
        with tempfile.TemporaryDirectory() as folder:
            run_gold_shadow(folder, bars=data)
            path = Path(folder) / "ema50_200.json"
            state = json.loads(path.read_text(encoding="utf-8"))
            state["last_processed_timestamp"] += 1
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Checkpoint candle is absent"):
                run_gold_shadow(folder, bars=data)


if __name__ == "__main__":
    unittest.main()
