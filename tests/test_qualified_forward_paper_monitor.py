import json
import tempfile
import unittest
from pathlib import Path

from qualified_forward_paper_monitor import (
    ATR_FILE,
    CANDIDATES,
    process_qualified_forward_candidates,
)


class QualifiedForwardPaperMonitorTests(unittest.TestCase):
    @staticmethod
    def candles(days=205):
        start = 1_704_067_200  # 2024-01-01 00:00:00 UTC
        rows = []
        for index in range(days * 24):
            timestamp = start + index * 3600
            close = 30_000.0 + index * 0.7 + (index % 17) * 1.3
            rows.append({
                "timestamp": timestamp * 1000,
                "open": close - 0.5,
                "high": close + 2.0,
                "low": close - 2.0,
                "close": close,
                "volume": 10.0,
                "imputed": False,
            })
        return rows

    @staticmethod
    def now_for(candles):
        return candles[-1]["timestamp"] / 1000 + 3600 + 60

    def test_all_four_ledgers_seed_without_historical_trades_and_are_idempotent(self):
        candles = self.candles()
        with tempfile.TemporaryDirectory() as folder:
            first = process_qualified_forward_candidates(
                candles, folder, self.now_for(candles)
            )
            second = process_qualified_forward_candidates(
                candles, folder, self.now_for(candles)
            )
            self.assertEqual(first["mode"], "FOUR_QUALIFIED_CANDIDATES_FORWARD_ONLY_PAPER")
            self.assertEqual(first["initial_cash_usd"], 1000.0)
            self.assertEqual(first["equity_usd"], 1000.0)
            self.assertEqual(first["completed_trades"], 0)
            self.assertEqual(first["total_processed_new_candles"], 0)
            self.assertEqual(first["cycle_status"], "WAITING_FOR_NEW_CLOSED_CANDLES")
            self.assertFalse(first["live_trading_eligible"])
            self.assertEqual(set(first["candidates"]), {
                "1d_sma_trend",
                "6h_ema50_200_regime",
                "6h_ema_pullback_trend",
                "4h_ema20_50_daily_sma200_atr3",
            })
            for candidate in first["candidates"].values():
                self.assertEqual(candidate["initial_cash_usd"], 250.0)
                self.assertEqual(candidate["equity_usd"], 250.0)
                self.assertEqual(candidate["completed_trades"], 0)
                self.assertEqual(candidate["processed_new_candles"], 0)
                self.assertEqual(candidate["fees_paid_usd"], 0.0)
            self.assertEqual(second["total_processed_new_candles"], 0)
            self.assertEqual(second["completed_trades"], 0)
            for config in CANDIDATES.values():
                state = json.loads(
                    (Path(folder) / config["file"]).read_text(encoding="utf-8")
                )
                self.assertEqual(state["trades"], [])
                self.assertEqual(state["cash"], 250.0)
            atr = json.loads((Path(folder) / ATR_FILE).read_text(encoding="utf-8"))
            self.assertEqual(atr["trades"], [])
            self.assertEqual(atr["cash"], 250.0)

    def test_only_new_native_timeframe_bars_are_processed(self):
        initial = self.candles()
        extended = initial + self.candles(days=1)
        # Rebase the appended day so it begins immediately after the seed feed.
        for index, row in enumerate(extended[len(initial):]):
            row["timestamp"] = initial[-1]["timestamp"] + (index + 1) * 3_600_000
        with tempfile.TemporaryDirectory() as folder:
            process_qualified_forward_candidates(
                initial, folder, self.now_for(initial)
            )
            updated = process_qualified_forward_candidates(
                extended, folder, self.now_for(extended)
            )
            self.assertEqual(
                updated["candidates"]["1d_sma_trend"]["processed_new_candles"], 1
            )
            self.assertEqual(
                updated["candidates"]["6h_ema50_200_regime"]["processed_new_candles"], 4
            )
            self.assertEqual(
                updated["candidates"]["6h_ema_pullback_trend"]["processed_new_candles"], 4
            )
            self.assertEqual(
                updated["candidates"]["4h_ema20_50_daily_sma200_atr3"]["processed_new_candles"], 6
            )
            self.assertEqual(updated["cycle_status"], "PROCESSED_NEW_CANDLES")
            repeated = process_qualified_forward_candidates(
                extended, folder, self.now_for(extended)
            )
            self.assertEqual(repeated["total_processed_new_candles"], 0)

    def test_synthetic_aggregate_bar_is_marked_non_executable(self):
        candles = self.candles()
        candles[200]["imputed"] = True
        with tempfile.TemporaryDirectory() as folder:
            report = process_qualified_forward_candidates(
                candles, folder, self.now_for(candles)
            )
            self.assertEqual(report["completed_trades"], 0)
            # The affected hourly interval is propagated into its native bars.
            from qualified_forward_paper_monitor import _native_bars
            four_hour = _native_bars(candles, 4)
            self.assertTrue(any(
                not row["execution_eligible"] for row in four_hour
            ))

    def test_insufficient_history_fails_before_creating_any_ledger(self):
        candles = self.candles(days=150)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(
                ValueError, "Insufficient native timeframe history"
            ):
                process_qualified_forward_candidates(
                    candles, folder, self.now_for(candles)
                )
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_corrupt_atr_counter_fails_before_any_qualified_ledger_is_created(self):
        candles = self.candles()
        with tempfile.TemporaryDirectory() as folder:
            atr_path = Path(folder) / ATR_FILE
            from qualified_forward_paper_monitor import _native_bars
            latest_completed_4h = _native_bars(candles, 4)[-1]["timestamp"]
            atr_path.write_text(json.dumps({
                "strategy": "ema20_50_daily_sma200_atr3_trailing",
                "last_timestamp": latest_completed_4h,
                "processed_new_candles": "not-an-integer",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "processing counter is invalid"):
                process_qualified_forward_candidates(
                    candles, folder, self.now_for(candles)
                )
            for config in CANDIDATES.values():
                self.assertFalse((Path(folder) / config["file"]).exists())
            self.assertEqual(
                json.loads(atr_path.read_text(encoding="utf-8"))["processed_new_candles"],
                "not-an-integer",
            )

    def test_existing_corrupt_ledger_is_never_silently_reseeded(self):
        candles = self.candles()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / CANDIDATES["1d_sma_trend"]["file"]
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unreadable"):
                process_qualified_forward_candidates(
                    candles, folder, self.now_for(candles)
                )
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
