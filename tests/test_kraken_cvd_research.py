import json
import tempfile
import unittest
from pathlib import Path

from kraken_cvd_research import (
    load_normalized_trade_journal,
    analyze_trade_journal,
)
from trade_journal_checkpoint import build_continuity_checkpoint


class KrakenCvdResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "trades.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def event(self, trade_id, timestamp, symbol="BTC/USD"):
        return {
            "trade_id": trade_id,
            "timestamp": timestamp,
            "price": 100 + trade_id,
            "qty": 1.0,
            "side": "buy" if trade_id % 2 else "sell",
            "symbol": symbol,
        }

    def write_events(self, events, newline=True):
        content = "".join(json.dumps(event) + "\n" for event in events)
        if not newline:
            content = content.rstrip("\n")
        self.path.write_text(content, encoding="utf-8")

    def checkpoint(self, last_trade_id=103, symbol="BTC/USD"):
        checkpoint = build_continuity_checkpoint(
            self.path, "BTC/USD", 103
        )
        checkpoint["last_trade_id"] = last_trade_id
        checkpoint["symbol"] = symbol
        return checkpoint

    def valid_events(self):
        return [
            self.event(100, 10),
            self.event(101, 61),
            self.event(102, 121),
            self.event(103, 181),
        ]

    def test_loads_valid_contiguous_journal(self):
        self.write_events([self.event(100, 10), self.event(101, 20)])
        result = load_normalized_trade_journal(self.path)
        self.assertEqual(result["trade_count"], 2)
        self.assertEqual(result["first_trade_id"], 100)
        self.assertEqual(result["last_trade_id"], 101)
        self.assertTrue(result["continuity_from_first_recorded_trade"])
        self.assertFalse(result["feed_continuity_verified"])

    def test_rejects_trade_id_gap(self):
        self.write_events([self.event(100, 10), self.event(102, 20)])
        with self.assertRaisesRegex(ValueError, "trade ID gap"):
            load_normalized_trade_journal(self.path)

    def test_rejects_incomplete_final_line(self):
        self.write_events([self.event(100, 10)], newline=False)
        with self.assertRaisesRegex(ValueError, "incomplete journal line"):
            load_normalized_trade_journal(self.path)

    def test_rejects_mixed_symbols(self):
        self.write_events([
            self.event(100, 10, "BTC/USD"),
            self.event(101, 20, "ETH/USD"),
        ])
        with self.assertRaisesRegex(ValueError, "mixed symbols"):
            load_normalized_trade_journal(self.path)

    def test_rejects_backward_timestamps(self):
        self.write_events([self.event(100, 20), self.event(101, 10)])
        with self.assertRaisesRegex(ValueError, "timestamp moved backwards"):
            load_normalized_trade_journal(self.path)

    def test_rejects_invalid_timestamps(self):
        for value in (float("nan"), float("inf"), float("-inf"), -1, True, None):
            with self.subTest(timestamp=value):
                self.write_events([self.event(100, value)])
                with self.assertRaisesRegex(ValueError, "timestamp"):
                    load_normalized_trade_journal(self.path)

    def test_rejects_naive_iso_timestamp(self):
        self.write_events([self.event(100, "2026-11-08T12:00:00")])
        with self.assertRaisesRegex(ValueError, "timezone"):
            load_normalized_trade_journal(self.path)

    def test_rejects_invalid_prices(self):
        for value in (0, -1, "bad", float("nan"), float("inf"), True):
            with self.subTest(price=value):
                event = self.event(100, 10)
                event["price"] = value
                self.write_events([event])
                with self.assertRaisesRegex(ValueError, "invalid price"):
                    load_normalized_trade_journal(self.path)

    def test_rejects_invalid_quantities(self):
        for value in (0, -1, "bad", float("nan"), float("inf"), True):
            with self.subTest(qty=value):
                event = self.event(100, 10)
                event["qty"] = value
                self.write_events([event])
                with self.assertRaisesRegex(ValueError, "invalid qty"):
                    load_normalized_trade_journal(self.path)

    def test_rejects_unknown_trade_side(self):
        for value in ("BUY", "SELL", "hold", "", None, 1):
            with self.subTest(side=value):
                event = self.event(100, 10)
                event["side"] = value
                self.write_events([event])
                with self.assertRaisesRegex(ValueError, "invalid side"):
                    load_normalized_trade_journal(self.path)

    def test_rejects_empty_journal(self):
        self.path.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "trade journal is empty"):
            load_normalized_trade_journal(self.path)

    def test_rejects_duplicate_trade_ids(self):
        self.write_events([self.event(100, 10), self.event(100, 20)])
        with self.assertRaisesRegex(ValueError, "trade ID gap"):
            load_normalized_trade_journal(self.path)

    def test_timeframes_must_be_list_or_tuple(self):
        self.write_events(self.valid_events())
        for value in ("1m", [1], [""], []):
            with self.subTest(timeframes=value):
                with self.assertRaises(ValueError):
                    analyze_trade_journal(
                        self.path, now_timestamp=240, timeframes=value
                    )

    def test_excludes_initial_partial_candle_but_does_not_assume_feed_continuity(self):
        self.write_events(self.valid_events())
        result = analyze_trade_journal(
            self.path, now_timestamp=240, timeframes=["1m"]
        )
        diagnostic = result["timeframe_diagnostics"]["1m"]
        self.assertEqual(diagnostic["status"], "CONTINUITY_UNVERIFIED")
        self.assertTrue(diagnostic["excluded_initial_partial_candle"])
        self.assertEqual(diagnostic["closed_candles"], 3)
        self.assertEqual(diagnostic["first_candle_timestamp"], 60)
        self.assertEqual(diagnostic["trade_count"], 3)
        self.assertFalse(result["feed_continuity_verified"])
        self.assertEqual(
            result["multi_timeframe_cvd"]["consensus"]["bias"], "UNAVAILABLE"
        )
        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_enabled"])

    def test_matching_verified_checkpoint_enables_analysis(self):
        self.write_events(self.valid_events())
        result = analyze_trade_journal(
            self.path,
            now_timestamp=240,
            timeframes=["1m"],
            continuity_checkpoint=self.checkpoint(),
        )
        diagnostic = result["timeframe_diagnostics"]["1m"]
        self.assertEqual(diagnostic["status"], "READY_FOR_CVD_ANALYSIS")
        self.assertTrue(diagnostic["feed_continuity_verified"])
        self.assertTrue(result["feed_continuity_verified"])

    def test_rejects_checkpoint_with_wrong_last_trade_id(self):
        self.write_events(self.valid_events())
        with self.assertRaisesRegex(ValueError, "last trade ID"):
            analyze_trade_journal(
                self.path,
                now_timestamp=240,
                timeframes=["1m"],
                continuity_checkpoint=self.checkpoint(last_trade_id=102),
            )

    def test_rejects_checkpoint_with_wrong_symbol(self):
        self.write_events(self.valid_events())
        with self.assertRaisesRegex(ValueError, "symbol"):
            analyze_trade_journal(
                self.path,
                now_timestamp=240,
                timeframes=["1m"],
                continuity_checkpoint=self.checkpoint(symbol="ETH/USD"),
            )

    def test_rejects_unverified_or_untrusted_checkpoint(self):
        self.write_events(self.valid_events())
        for patch in (
            {"feed_continuity_verified": False},
            {"source": "local_file"},
            {"feed_continuity_verified": 1},
        ):
            checkpoint = self.checkpoint()
            checkpoint.update(patch)
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    analyze_trade_journal(
                        self.path,
                        now_timestamp=240,
                        timeframes=["1m"],
                        continuity_checkpoint=checkpoint,
                    )

    def test_rejects_checkpoint_when_journal_bytes_change(self):
        self.write_events(self.valid_events())
        checkpoint = self.checkpoint()
        original = self.path.read_text(encoding="utf-8")
        self.path.write_text(original.replace('{"trade_id"', '{ "trade_id"', 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "journal_size_bytes|journal_sha256"):
            analyze_trade_journal(
                self.path,
                now_timestamp=240,
                timeframes=["1m"],
                continuity_checkpoint=checkpoint,
            )

    def test_rejects_checkpoint_with_wrong_first_trade_id(self):
        self.write_events(self.valid_events())
        checkpoint = self.checkpoint()
        checkpoint["first_trade_id"] = 99
        with self.assertRaisesRegex(ValueError, "first_trade_id"):
            analyze_trade_journal(
                self.path,
                now_timestamp=240,
                timeframes=["1m"],
                continuity_checkpoint=checkpoint,
            )

    def test_analysis_does_not_modify_journal(self):
        self.write_events(self.valid_events())
        before = self.path.read_bytes()
        analyze_trade_journal(
            self.path, now_timestamp=240, timeframes=["1m"]
        )
        after = self.path.read_bytes()
        self.assertEqual(before, after)


    def test_checkpoint_inspector_rejects_invalid_trade_payload(self):
        from trade_journal_checkpoint import inspect_trade_journal
        for field, value in (
            ("price", 0), ("price", float("nan")), ("price", True),
            ("qty", -1), ("qty", float("inf")), ("qty", False),
            ("side", "hold"),
        ):
            with self.subTest(field=field, value=value):
                row = self.event(100, 10)
                row[field] = value
                self.write_events([row])
                with self.assertRaises(ValueError):
                    inspect_trade_journal(self.path)

    def test_checkpoint_inspector_rejects_backward_timestamp(self):
        from trade_journal_checkpoint import inspect_trade_journal
        self.write_events([self.event(100, 20), self.event(101, 10)])
        with self.assertRaisesRegex(ValueError, "timestamp moved backwards"):
            inspect_trade_journal(self.path)

if __name__ == "__main__":
    unittest.main()
