import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import multi_market_opportunity_scan as multi_scan

from multi_market_opportunity_scan import (
    discover_kraken_universe,
    normalize_kraken_ohlc,
)
from market_scanner import scan_btc_market


class MultiMarketScannerTests(unittest.TestCase):
    def test_fetch_json_retries_transient_http_429(self):
        throttled = HTTPError(
            "https://provider.example/markets", 429, "Too Many Requests",
            {"Retry-After": "1"}, None,
        )
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b'{"result":{"PAIR":{"ok":true}}}'
        with patch.object(multi_scan, "urlopen", side_effect=[throttled, response]) as request, \
             patch.object(multi_scan.time, "sleep") as sleep:
            result = multi_scan.fetch_json("https://provider.example/markets")
        self.assertEqual(result, {"PAIR": {"ok": True}})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_fetch_json_does_not_retry_permanent_http_400(self):
        invalid_request = HTTPError(
            "https://provider.example/markets", 400, "Bad Request", {}, None,
        )
        with patch.object(multi_scan, "urlopen", side_effect=invalid_request) as request, \
             patch.object(multi_scan.time, "sleep") as sleep:
            with self.assertRaises(HTTPError):
                multi_scan.fetch_json("https://provider.example/markets")
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()
    def test_ranker_excludes_stablecoin_and_fiat_base_pairs(self):
        pairs = [
            {"base": "USDG", "quote": "USDC", "pair_key": "USDGUSDC", "altname": "USDGUSDC", "symbol": "USDG/USDC"},
            {"base": "EUR", "quote": "USD", "pair_key": "EURUSD", "altname": "EURUSD", "symbol": "EUR/USD"},
            {"base": "ETH", "quote": "USD", "pair_key": "ETHUSD", "altname": "ETHUSD", "symbol": "ETH/USD"},
        ]
        tickers = {
            "USDGUSDC": {"v": ["1", "1000"], "c": ["1.0006"]},
            "EURUSD": {"v": ["1", "1000"], "c": ["1.1"]},
            "ETHUSD": {"v": ["1", "100"], "c": ["2000"]},
        }
        with patch.object(multi_scan, "fetch_json", return_value=tickers):
            ranked, missing = multi_scan.rank_kraken_pairs(pairs)
        self.assertEqual([p["symbol"] for p in ranked], ["ETH/USD"])
        self.assertEqual(missing, [])

    def test_copper_spot_is_watch_only_when_daily_history_is_plan_gated(self):
        quote = {
            "price_usd": 4.25, "price_unit": "pound", "provider": "Gold-API",
            "quote_age_seconds": 20, "expected_delay_minutes": 0,
            "computed_at": "2026-11-21T11:00:00+00:00",
        }
        with patch.object(multi_scan, "fetch_spot", return_value=quote), \
             patch.object(multi_scan, "fetch_daily_bars") as bars:
            result = multi_scan.normalize_biquote_metals("XCUUSD", 1795262400)
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(result["directional_research"], "WATCH")
        self.assertIn("plan_gated", result["data_quality"]["reason"])
        bars.assert_not_called()

    def test_failed_universe_discovery_is_never_reported_complete(self):
        with TemporaryDirectory() as temp_dir:
            with patch.object(multi_scan, "OUTPUT_DIR", __import__("pathlib").Path(temp_dir)), \
                 patch.object(multi_scan, "discover_kraken_universe", side_effect=RuntimeError("provider down")), \
                 patch.object(multi_scan, "normalize_biquote_metals", side_effect=RuntimeError("feed down")):
                report = multi_scan.build_report()
        self.assertEqual(report["scan_status"], "PARTIAL")
        self.assertFalse(report["scan_complete"])
        self.assertFalse(report["universe_discovery_succeeded"])
        self.assertEqual(report["crypto_pairs_remaining"], 0)

    def test_kraken_normalizer_uses_closed_hourly_candles(self):
        now = datetime(2026, 11, 21, 12, 30, tzinfo=timezone.utc).timestamp()
        rows = []
        start = int(now // 3600) * 3600 - 80 * 3600
        for index in range(81):
            timestamp = start + index * 3600
            price = 100.0 + index * 0.25
            rows.append([
                timestamp, str(price), str(price + 1), str(price - 1),
                str(price + 0.2), str(price), "120.0", "10",
            ])
        candles, quality = normalize_kraken_ohlc({"rows": rows}, now)
        self.assertEqual(len(candles), 80)  # forming candle is excluded
        self.assertEqual(quality["quality_status"], "HEALTHY")
        self.assertTrue(quality["recent_51_hour_gap_free"])

    def test_kraken_normalizer_rejects_recent_missing_hour(self):
        now = datetime(2026, 11, 21, 12, 30, tzinfo=timezone.utc).timestamp()
        rows = []
        start = int(now // 3600) * 3600 - 80 * 3600
        for index in range(81):
            if index == 50:
                continue
            timestamp = start + index * 3600
            price = 100.0 + index * 0.25
            rows.append([
                timestamp, price, price + 1, price - 1, price + 0.2,
                price, 120.0, 10,
            ])
        with self.assertRaisesRegex(ValueError, "missing hourly interval"):
            normalize_kraken_ohlc({"rows": rows}, now)

    def test_session_gap_is_opt_in_and_bounded(self):
        candles = []
        start = 1_700_000_000 // 3600 * 3600
        for index in range(55):
            timestamp = start + index * 3600
            if index >= 35:
                timestamp += 2 * 3600
            price = 100.0 + index
            candles.append([
                timestamp, price, price + 1, price - 1, price + 0.5,
                0.0, 100.0, 10,
            ])
        quality = {"quality_status": "HEALTHY", "paper_execution_allowed": True}
        with self.assertRaisesRegex(ValueError, "contiguous"):
            scan_btc_market(candles, quality, market_label="TEST/USD")
        result = scan_btc_market(
            candles, quality, market_label="TEST/USD",
            allow_session_gaps=True, max_session_gap_hours=4,
        )
        self.assertEqual(result["market"], "TEST/USD")

    def test_session_gap_over_limit_is_rejected(self):
        candles = []
        start = 1_700_000_000 // 3600 * 3600
        for index in range(55):
            timestamp = start + index * 3600
            if index >= 35:
                timestamp += 6 * 3600
            price = 100.0 + index
            candles.append([
                timestamp, price, price + 1, price - 1, price + 0.5,
                0.0, 100.0, 10,
            ])
        quality = {"quality_status": "HEALTHY", "paper_execution_allowed": True}
        with self.assertRaisesRegex(ValueError, "session gap exceeds"):
            scan_btc_market(
                candles, quality, market_label="TEST/USD",
                allow_session_gaps=True, max_session_gap_hours=4,
            )


if __name__ == "__main__":
    unittest.main()
