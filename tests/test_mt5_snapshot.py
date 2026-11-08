import tempfile
import unittest
from pathlib import Path

from mt5_snapshot import build_mt5_snapshot, write_snapshot


def candles(interval, count=70):
    rows = []
    anchor = 1700000000 - (1700000000 % 43200)
    start = anchor - count * interval
    price = 100.0
    for index in range(count):
        ts = start + index * interval
        price *= 1.001
        rows.append({
            "timestamp": ts,
            "open": price - 0.2,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "tick_volume": 100 + index,
            "spread": 2,
            "real_volume": 0,
        })
    return rows


class FakeAdapter:
    def __init__(self):
        self.connected = False
        self.requested = []

    def connect(self):
        self.connected = True
        # Deliberately includes private data to prove snapshot does not copy it.
        return {"account_balance": 987654.0, "account_equity": 999999.0, "login": 123}

    def get_quote(self, symbol):
        return {"symbol": symbol, "bid": 101.0, "ask": 101.2, "time": 1699987260}

    def fetch_closed_rates(self, symbol, timeframe, count):
        self.requested.append((symbol, timeframe, count))
        seconds = {"TIMEFRAME_H1": 3600, "TIMEFRAME_H4": 14400, "TIMEFRAME_H6": 21600}[timeframe]
        return candles(seconds, count=70)


class MT5SnapshotTests(unittest.TestCase):
    def test_snapshot_includes_three_timeframes_and_excludes_private_account_fields(self):
        adapter = FakeAdapter()
        snapshot = build_mt5_snapshot(adapter, "BTCUSD", 70, now_timestamp=1700000000 - (1700000000 % 43200) + 60)
        self.assertTrue(adapter.connected)
        self.assertEqual(set(snapshot["timeframes"]), {"1h", "4h", "6h"})
        self.assertEqual(snapshot["quote"]["spread"], 0.2)
        self.assertEqual(snapshot["timeframes"]["1h"]["scanner"]["market"], "BTCUSD")
        serialized = str(snapshot)
        self.assertNotIn("account_balance", serialized)
        self.assertNotIn("account_equity", serialized)
        self.assertNotIn("account_login", serialized)
        self.assertFalse(snapshot["safety"]["orders_sent"])
        self.assertFalse(snapshot["safety"]["live_trading_enabled"])
        self.assertEqual(len(adapter.requested), 3)

    def test_rejects_non_btc_paper_ledger_without_writing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "BTC/XBT"):
                build_mt5_snapshot(
                    FakeAdapter(), "XAUUSD", 70, now_timestamp=1700000000 - (1700000000 % 43200) + 60,
                    update_paper_ledger=True, state_dir=directory
                )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_write_snapshot_is_valid_json_and_atomic_target_exists(self):
        snapshot = build_mt5_snapshot(
            FakeAdapter(), "BTCUSD", 70, now_timestamp=1700000000 + 70 * 21600
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "snapshot.json"
            write_snapshot(snapshot, target)
            import json
            loaded = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schema_version"], 1)
            self.assertFalse(loaded["safety"]["orders_sent"])


if __name__ == "__main__":
    unittest.main()
