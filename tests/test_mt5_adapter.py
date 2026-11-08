"""Tests for the optional, read-only MetaTrader 5 adapter."""
import unittest
from types import SimpleNamespace

from mt5_adapter import MetaTrader5ReadOnly


def rate(timestamp, open_price=100.0, high=103.0, low=99.0, close=102.0):
    return {
        "time": timestamp, "open": open_price, "high": high, "low": low,
        "close": close, "tick_volume": 120, "spread": 8, "real_volume": 0,
    }


class FakeMT5:
    TIMEFRAME_H1 = 60

    def __init__(self):
        self.initialized = False
        self.shutdown_called = False
        self.start_positions = []
        self.rates = [rate(1000), rate(4600)]

    def initialize(self, **kwargs):
        self.initialized = True
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=True, company="Demo Broker")

    def account_info(self):
        return SimpleNamespace(
            trade_allowed=True, trade_expert=True, server="Demo-Server",
            currency="USD", leverage=100, balance=1000, equity=1010,
            margin=20, margin_free=990, profit=10, login=123456,
        )

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.start_positions.append((symbol, timeframe, start_pos, count))
        return self.rates

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=100.0, ask=100.2, time=4600)

    def last_error(self):
        return (1, "fake error")

    def shutdown(self):
        self.shutdown_called = True
        self.initialized = False


class MetaTrader5ReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeMT5()
        self.adapter = MetaTrader5ReadOnly(mt5_module=self.fake)

    def test_connect_reports_read_only_and_sanitized_account(self):
        status = self.adapter.connect()
        self.assertEqual(status["mode"], "READ_ONLY_PAPER_DATA")
        self.assertEqual(status["provider"], "MetaTrader 5")
        self.assertEqual(status["account_equity"], 1010.0)
        self.assertNotIn("login", status)
        self.assertTrue(self.adapter.connected)

    def test_fetches_completed_bars_starting_at_position_one(self):
        self.adapter.connect()
        rows = self.adapter.fetch_closed_rates("BTCUSD", "TIMEFRAME_H1", 2)
        self.assertEqual([row["timestamp"] for row in rows], [1000, 4600])
        self.assertEqual(self.fake.start_positions, [("BTCUSD", 60, 1, 2)])

    def test_rejects_invalid_symbol_timeframe_and_count(self):
        self.adapter.connect()
        for args in (("", "TIMEFRAME_H1", 2), ("BTCUSD", "H1", 2),
                     ("BTCUSD", "TIMEFRAME_H1", True), ("BTCUSD", "TIMEFRAME_H1", 10001)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.adapter.fetch_closed_rates(*args)

    def test_rejects_invalid_ohlc_and_out_of_order_bars(self):
        self.adapter.connect()
        self.fake.rates = [rate(1000, high=98)]
        with self.assertRaisesRegex(ValueError, "high is inconsistent"):
            self.adapter.fetch_closed_rates("BTCUSD")
        self.fake.rates = [rate(4600), rate(1000)]
        with self.assertRaisesRegex(ValueError, "chronological order"):
            self.adapter.fetch_closed_rates("BTCUSD")

    def test_quote_is_read_only_and_validated(self):
        self.adapter.connect()
        quote = self.adapter.get_quote("BTCUSD")
        self.assertEqual(quote["spread"], 0.2)
        self.assertEqual(quote["mode"], "READ_ONLY")
        self.assertFalse(hasattr(self.adapter, "order_send"))

    def test_rejects_invalid_quote(self):
        self.adapter.connect()
        self.fake.symbol_info_tick = lambda symbol: SimpleNamespace(
            bid=101, ask=100, time=4600
        )
        with self.assertRaisesRegex(ValueError, "invalid bid/ask"):
            self.adapter.get_quote("BTCUSD")

    def test_requires_connection_and_closes_cleanly(self):
        with self.assertRaisesRegex(RuntimeError, "Connect"):
            self.adapter.get_quote("BTCUSD")
        self.adapter.connect()
        self.adapter.close()
        self.assertFalse(self.adapter.connected)
        self.assertTrue(self.fake.shutdown_called)

    def test_initialization_failure_is_reported(self):
        self.fake.initialize = lambda **kwargs: False
        with self.assertRaisesRegex(RuntimeError, "Could not initialize"):
            self.adapter.connect()


if __name__ == "__main__":
    unittest.main()
