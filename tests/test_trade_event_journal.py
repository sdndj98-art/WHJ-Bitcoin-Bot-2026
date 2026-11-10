import json
import os
import tempfile
import unittest

from trade_event_journal import JsonlTradeJournal, TradeJournalError


def event(trade_id, timestamp=None):
    return {
        "trade_id": trade_id,
        "timestamp": timestamp if timestamp is not None else 1000 + trade_id,
        "price": 100 + trade_id,
        "qty": 0.1,
        "side": "buy" if trade_id % 2 else "sell",
        "symbol": "BTC/USD",
    }


class TradeEventJournalTests(unittest.TestCase):
    def test_appends_contiguous_events_and_restores_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            journal = JsonlTradeJournal(path)
            result = journal.append([event(500), event(501)])
            self.assertEqual(result["appended"], 2)
            restored = JsonlTradeJournal(path)
            self.assertEqual(restored.last_trade_id, 501)
            self.assertEqual(restored.append([event(501), event(502)])["appended"], 1)
            with open(path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            self.assertEqual([row["trade_id"] for row in rows], [500, 501, 502])

    def test_rejects_trade_id_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = JsonlTradeJournal(os.path.join(directory, "trades.jsonl"))
            journal.append([event(10)])
            with self.assertRaisesRegex(TradeJournalError, "gap"):
                journal.append([event(12)])
            self.assertEqual(journal.last_trade_id, 10)

    def test_rejects_mixed_symbols_in_one_append_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = JsonlTradeJournal(os.path.join(directory, "trades.jsonl"))
            other = event(11)
            other["symbol"] = "ETH/USD"
            with self.assertRaisesRegex(TradeJournalError, "mixed symbols"):
                journal.append([event(10), other])
            self.assertIsNone(journal.last_trade_id)
            self.assertFalse(os.path.exists(journal.path))

    def test_rejects_symbol_change_after_journal_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = JsonlTradeJournal(os.path.join(directory, "trades.jsonl"))
            journal.append([event(10)])
            other = event(11)
            other["symbol"] = "ETH/USD"
            with self.assertRaisesRegex(TradeJournalError, "does not match journal"):
                journal.append([other])
            self.assertEqual(journal.last_trade_id, 10)

    def test_restore_rejects_mixed_symbol_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(event(10)) + "\n")
                other = event(11)
                other["symbol"] = "ETH/USD"
                handle.write(json.dumps(other) + "\n")
            with self.assertRaisesRegex(TradeJournalError, "mixed symbols"):
                JsonlTradeJournal(path)

    def test_rejects_missing_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = JsonlTradeJournal(os.path.join(directory, "trades.jsonl"))
            invalid = event(10)
            invalid.pop("symbol")
            with self.assertRaisesRegex(ValueError, "symbol"):
                journal.append([invalid])

    def test_rejects_timestamp_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = JsonlTradeJournal(os.path.join(directory, "trades.jsonl"))
            journal.append([event(10, 1010)])
            with self.assertRaisesRegex(TradeJournalError, "backwards"):
                journal.append([event(11, 1009)])

    def test_rejects_corrupt_or_incomplete_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            with open(path, "wb") as handle:
                handle.write(b'{"trade_id": 1}')
            with self.assertRaisesRegex(TradeJournalError, "incomplete"):
                JsonlTradeJournal(path)

    def test_enforces_maximum_size_without_advancing_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            journal = JsonlTradeJournal(path, max_bytes=1)
            with self.assertRaisesRegex(TradeJournalError, "size limit"):
                journal.append([event(1)])
            self.assertIsNone(journal.last_trade_id)
            self.assertFalse(os.path.exists(path))


    def test_restore_rejects_invalid_trade_payload_fields(self):
        invalid_cases = (
            ("price", 0),
            ("price", -1),
            ("price", float("nan")),
            ("price", float("inf")),
            ("price", True),
            ("qty", 0),
            ("qty", -1),
            ("qty", float("nan")),
            ("qty", float("inf")),
            ("qty", True),
            ("side", "hold"),
            ("side", "BUY"),
        )
        for field, value in invalid_cases:
            with self.subTest(field=field, value=value):
                with tempfile.TemporaryDirectory() as directory:
                    path = os.path.join(directory, "trades.jsonl")
                    row = event(10)
                    row[field] = value
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(json.dumps(row) + "\n")
                    with self.assertRaises(TradeJournalError):
                        JsonlTradeJournal(path)

    def test_append_rejects_boolean_and_non_finite_price_or_qty(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = JsonlTradeJournal(os.path.join(directory, "trades.jsonl"))
            for field, value in (
                ("price", True), ("price", float("nan")),
                ("qty", False), ("qty", float("inf")),
            ):
                row = event(10)
                row[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        journal.append([row])
            self.assertIsNone(journal.last_trade_id)

    def test_accepts_mixed_iso_and_unix_timestamps_with_equal_times(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            journal = JsonlTradeJournal(path)
            first = event(10, "2026-11-10T03:29:27.161334Z")
            second = event(11, 1794281367.6102128)
            third = event(12, 1794281367.6102128)
            self.assertEqual(journal.append([first, second, third])["appended"], 3)
            restored = JsonlTradeJournal(path)
            self.assertEqual(restored.last_trade_id, 12)
            self.assertEqual(restored.last_timestamp_ns, 1794281367610212800)

    def test_persists_feed_source_for_websocket_and_rest_trades(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            journal = JsonlTradeJournal(path)
            ws = event(10)
            ws["source"] = "websocket_v2"
            rest = event(11)
            rest["source"] = "rest_trades"
            journal.append([ws, rest])
            with open(path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            self.assertEqual([row["source"] for row in rows], ["websocket_v2", "rest_trades"])
            restored = JsonlTradeJournal(path)
            self.assertEqual(restored.last_trade_id, 11)

    def test_legacy_event_without_source_remains_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            journal = JsonlTradeJournal(path)
            journal.append([event(10)])
            restored = JsonlTradeJournal(path)
            self.assertEqual(restored.last_trade_id, 10)

if __name__ == "__main__":
    unittest.main()
