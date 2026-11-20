import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from whj_hyperliquid_monitor import (
    build_liquidation_zones, load_wallets, fetch_wallet, fetch_market_data
)


class HyperliquidMonitorTests(unittest.TestCase):
    def test_wallet_config_validates_and_deduplicates_addresses(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "wallets.json"
            address = "0x" + "a" * 40
            path.write_text(
                '{"wallets":[{"address":"' + address + '","label":"A"},'
                '{"address":"' + address.upper().replace("0X", "0x") + '","label":"duplicate"},'
                '{"address":"bad","label":"invalid"}]}',
                encoding="utf-8",
            )
            rows = load_wallets(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["label"], "A")

    def test_market_data_parses_public_meta_and_contexts(self):
        def fake(_):
            return [
                {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
                [{"markPx": "60000", "funding": "0.0001", "openInterest": "10"},
                 {"markPx": "3000", "funding": "0.0002", "openInterest": "20"}],
            ]
        markets = fetch_market_data(fake)
        self.assertEqual(markets["BTC"]["mark_price"], 60000)
        self.assertEqual(markets["ETH"]["open_interest"], 20)

    def test_wallet_reads_positions_without_trading(self):
        def fake(payload):
            self.assertEqual(payload["type"], "clearinghouseState")
            self.assertIn("user", payload)
            return {
                "marginSummary": {"accountValue": "1000", "totalNtlPos": "500"},
                "assetPositions": [{"position": {
                    "coin": "BTC", "szi": "0.01", "entryPx": "59000",
                    "liquidationPx": "50000", "positionValue": "600",
                    "unrealizedPnl": "10", "leverage": {"value": "2"},
                }}],
            }
        result = fetch_wallet({"address": "0x" + "a" * 40, "label": "Test"}, fake)
        self.assertEqual(result["positions"][0]["side"], "LONG")
        self.assertEqual(result["positions"][0]["liquidation_price"], 50000)

    def test_liquidation_zones_group_by_coin_side_and_half_percent(self):
        wallets = [
            {"label": "A", "positions": [{
                "coin": "BTC", "side": "LONG", "liquidation_price": 59700,
                "position_value_usd": 1000,
            }]},
            {"label": "B", "positions": [{
                "coin": "BTC", "side": "LONG", "liquidation_price": 59800,
                "position_value_usd": 2000,
            }]},
        ]
        zones = build_liquidation_zones(wallets, {"BTC": {"mark_price": 60000}})
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["wallet_count"], 2)
        self.assertEqual(zones[0]["estimated_position_value_usd"], 3000)

    def test_empty_wallets_produce_markets_without_fake_leaderboard(self):
        from whj_hyperliquid_monitor import build_report
        def fake(_):
            return [{"universe": [{"name": "BTC"}]}, [{"markPx": "60000"}]]
        with TemporaryDirectory() as temp:
            path = Path(temp) / "empty.json"
            path.write_text('{"wallets":[]}', encoding="utf-8")
            report = build_report(path, request_fn=fake, sleep_fn=lambda _: None)
        self.assertEqual(report["wallets_scanned"], 0)
        self.assertEqual(report["wallet_ranking"], "NOT_AVAILABLE_FROM_THIS_PUBLIC_INFO_QUERY")
        self.assertEqual(report["markets"]["BTC"]["mark_price"], 60000)


if __name__ == "__main__":
    unittest.main()
