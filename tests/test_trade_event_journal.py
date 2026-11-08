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


if __name__ == "__main__":
    unittest.main()
