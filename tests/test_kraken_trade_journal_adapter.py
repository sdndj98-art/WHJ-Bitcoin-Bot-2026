import unittest
from unittest.mock import patch

from kraken_order_flow import (
    KrakenSpotTradeFeedAdapter,
    PersistentCvdLedger,
    TradeJournalPersistenceError,
)


class AdapterTradeJournalTests(unittest.TestCase):
    def test_persists_only_newly_accepted_websocket_events(self):
        captured = []
        adapter = KrakenSpotTradeFeedAdapter(
            PersistentCvdLedger(symbol="BTC/USD"),
            "BTC/USD",
            on_accepted_trades=lambda events: captured.extend(events),
        )
        message = {
            "channel": "trade", "type": "snapshot",
            "data": [
                {"symbol": "BTC/USD", "trade_id": 100, "price": 100,
                 "qty": 1, "side": "buy", "timestamp": "1970-01-01T00:16:40Z"},
                {"symbol": "BTC/USD", "trade_id": 101, "price": 101,
                 "qty": 1, "side": "sell", "timestamp": "1970-01-01T00:16:41Z"},
            ],
        }
        adapter.handle_message(message)
        adapter.handle_message(message)
        self.assertEqual([item["trade_id"] for item in captured], [100, 101])

    @patch("kraken_order_flow.fetch_recent_trades")
    def test_persists_backfilled_events_before_new_websocket_event(self, fetch):
        captured = []
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        ledger.process([{
            "trade_id": 10, "price": 100, "qty": 1,
            "side": "buy", "timestamp": 100,
        }])
        fetch.return_value = {
            "trades": [
                ["101", "1", 101.0, "b", "m", "", "11"],
                ["102", "1", 102.0, "s", "m", "", "12"],
            ],
            "last": "102000000000",
        }
        adapter = KrakenSpotTradeFeedAdapter(
            ledger, "BTC/USD",
            on_accepted_trades=lambda events: captured.extend(events),
        )
        adapter.handle_message({
            "channel": "trade", "type": "update",
            "data": [{
                "symbol": "BTC/USD", "trade_id": 12, "price": 102,
                "qty": 1, "side": "sell", "timestamp": "1970-01-01T00:01:42Z",
            }],
        })
        self.assertEqual([item["trade_id"] for item in captured], ["11", "12"])

    def test_fresh_checkpointed_adapter_requires_initial_snapshot(self):
        adapter = KrakenSpotTradeFeedAdapter(
            PersistentCvdLedger(symbol="BTC/USD"),
            "BTC/USD",
            on_accepted_trades=lambda events: None,
            require_initial_snapshot=True,
        )
        update = {
            "channel": "trade", "type": "update",
            "data": [{
                "symbol": "BTC/USD", "trade_id": 100, "price": 100,
                "qty": 1, "side": "buy", "timestamp": "1970-01-01T00:01:40Z",
            }],
        }
        with self.assertRaisesRegex(Exception, "initial trade snapshot"):
            adapter.handle_message(update)
        self.assertEqual(adapter.ledger.last_trade_id, 0)
        snapshot = dict(update, type="snapshot")
        adapter.handle_message(snapshot)
        self.assertEqual(adapter.continuity_start_trade_id, 100)

    def test_journal_failure_is_fatal_and_not_silently_reconnected(self):
        adapter = KrakenSpotTradeFeedAdapter(
            PersistentCvdLedger(symbol="BTC/USD"),
            "BTC/USD",
            on_accepted_trades=lambda events: (_ for _ in ()).throw(OSError("disk full")),
        )
        with self.assertRaises(TradeJournalPersistenceError):
            adapter.handle_message({
                "channel": "trade", "type": "snapshot",
                "data": [{
                    "symbol": "BTC/USD", "trade_id": 1, "price": 100,
                    "qty": 1, "side": "buy", "timestamp": "1970-01-01T00:00:01Z",
                }],
            })


if __name__ == "__main__":
    unittest.main()
