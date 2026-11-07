import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from forward_paper_monitor import process_forward_accounts, validate_hourly_feed


class ForwardPaperMonitorTests(unittest.TestCase):
    def make_candles(self, hours=24 * 60):
        start = 1_700_000_000
        start -= start % 3600
        rows = []
        for i in range(hours):
            close = 30000 + i * 2 + (i % 19) * 3
            rows.append({
                "timestamp": (start + i * 3600) * 1000,
                "open": float(close - 1),
                "high": float(close + 2),
                "low": float(close - 2),
                "close": float(close),
                "volume": 10.0,
                "imputed": False,
            })
        return rows

    def test_initialization_is_forward_only_and_idempotent(self):
        candles = self.make_candles()
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with tempfile.TemporaryDirectory() as folder:
            first = process_forward_accounts(candles, folder, now)
            self.assertEqual(first["initial_cash_usd"], 1000.0)
            self.assertEqual(first["completed_trades"], 0)
            self.assertEqual(first["schema_version"], 1)
            self.assertEqual(first["status"], "PAPER_MONITORING")
            self.assertEqual(set(first["sleeves_summary"]), {"4h", "6h"})
            for timeframe in ("4h", "6h"):
                account = first["sleeves"][timeframe]["account"]
                self.assertEqual(account["processed_new_candles"], 0)
                self.assertEqual(account["return_pct"], 0.0)
                self.assertEqual(account["completed_trades"], 0)
            second = process_forward_accounts(candles, folder, now)
            for timeframe in ("4h", "6h"):
                self.assertEqual(
                    second["sleeves"][timeframe]["account"]["processed_new_candles"], 0
                )
            self.assertEqual(first["equity_after_estimated_exit_costs_usd"],
                             second["equity_after_estimated_exit_costs_usd"])

    def test_new_bars_are_processed_once_after_seed(self):
        candles = self.make_candles()
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with tempfile.TemporaryDirectory() as folder:
            process_forward_accounts(candles, folder, now)
            extended = candles + self.make_candles(8)
            # Shift appended fixture timestamps to immediately follow the original feed.
            for i, row in enumerate(extended[len(candles):]):
                row["timestamp"] = candles[-1]["timestamp"] + (i + 1) * 3_600_000
            now2 = extended[-1]["timestamp"] / 1000 + 3600 + 60
            result = process_forward_accounts(extended, folder, now2)
            self.assertGreater(result["sleeves"]["4h"]["account"]["processed_new_candles"], 0)
            self.assertGreater(result["sleeves"]["6h"]["account"]["processed_new_candles"], 0)
            again = process_forward_accounts(extended, folder, now2)
            self.assertEqual(again["sleeves"]["4h"]["account"]["processed_new_candles"], 0)
            self.assertEqual(again["sleeves"]["6h"]["account"]["processed_new_candles"], 0)

    def test_recent_hourly_gap_is_rejected(self):
        candles = self.make_candles(48)
        candles[-1]["timestamp"] += 3_600_000
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with self.assertRaisesRegex(ValueError, "gap"):
            validate_hourly_feed(candles, now)

    def test_invalid_ohlcv_values_are_rejected(self):
        mutations = [
            ("close", float("nan"), "finite number"),
            ("volume", -1.0, "volume cannot be negative"),
            ("high", 1.0, "high is inconsistent"),
            ("low", 999999.0, "low is inconsistent"),
            ("open", True, "finite number"),
            ("imputed", "false", "imputed flag must be boolean"),
        ]
        for field, value, message in mutations:
            with self.subTest(field=field):
                candles = self.make_candles(48)
                candles[-1][field] = value
                now = candles[-1]["timestamp"] / 1000 + 3600 + 60
                with self.assertRaisesRegex(ValueError, message):
                    validate_hourly_feed(candles, now)

    def test_non_integer_or_boolean_timestamp_is_rejected(self):
        for value in (True, 1.5, float("inf")):
            with self.subTest(timestamp=value):
                candles = self.make_candles(48)
                candles[-1]["timestamp"] = value
                with self.assertRaisesRegex(ValueError, "timestamp"):
                    validate_hourly_feed(candles, 1_800_000_000)

    def test_non_finite_current_time_is_rejected(self):
        candles = self.make_candles(48)
        with self.assertRaisesRegex(ValueError, "Current timestamp must be finite"):
            validate_hourly_feed(candles, float("nan"))

    def test_stale_or_imputed_feed_is_rejected(self):
        candles = self.make_candles(48)
        last_close = candles[-1]["timestamp"] / 1000 + 3600
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_hourly_feed(candles, last_close + 3 * 3600)
        candles[-3]["imputed"] = True
        with self.assertRaisesRegex(ValueError, "imputed"):
            validate_hourly_feed(candles, last_close + 60)


if __name__ == "__main__":
    unittest.main()
