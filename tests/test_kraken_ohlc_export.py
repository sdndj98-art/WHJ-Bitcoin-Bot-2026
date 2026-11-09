import unittest
from unittest.mock import patch

import kraken_ohlc_export


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        import json
        return json.dumps(self.payload).encode("utf-8")


class KrakenOhlcExportTests(unittest.TestCase):
    def _payload(self, rows):
        return {"error": [], "result": {"XXBTZUSD": rows, "last": "cursor"}}

    def _rows(self, count=500):
        rows = []
        for index in range(count):
            start = index * 3600
            rows.append([
                str(start), "100", "102", "99", "101", "100.5", "12.5", "42"
            ])
        return rows

    def test_exports_only_completed_candles(self):
        rows = self._rows()
        with patch.object(
            kraken_ohlc_export.urllib.request, "urlopen",
            return_value=_Response(self._payload(self._rows(501))),
        ):
            candles = kraken_ohlc_export.fetch_completed_ohlc(
                as_of_timestamp=500 * 3600
            )
        self.assertEqual(len(candles), 500)
        self.assertEqual(candles[-1][0], 499 * 3600)
        self.assertEqual(len(candles[-1]), 8)

    def test_rejects_fewer_than_500_completed_rows(self):
        with patch.object(
            kraken_ohlc_export.urllib.request, "urlopen",
            return_value=_Response(self._payload(self._rows(500))),
        ):
            with self.assertRaisesRegex(ValueError, "at least 500"):
                kraken_ohlc_export.fetch_completed_ohlc(
                    as_of_timestamp=499 * 3600
                )

    def test_rejects_timestamp_gaps(self):
        rows = self._rows()
        rows[250][0] = str(251 * 3600)
        with patch.object(
            kraken_ohlc_export.urllib.request, "urlopen",
            return_value=_Response(self._payload(rows)),
        ):
            with self.assertRaisesRegex(ValueError, "contains a gap"):
                kraken_ohlc_export.fetch_completed_ohlc(
                    as_of_timestamp=500 * 3600
                )

    def test_rejects_kraken_api_errors(self):
        with patch.object(
            kraken_ohlc_export.urllib.request, "urlopen",
            return_value=_Response({"error": ["EAPI:Invalid key"], "result": {}}),
        ):
            with self.assertRaisesRegex(RuntimeError, "Kraken OHLC error"):
                kraken_ohlc_export.fetch_completed_ohlc()


if __name__ == "__main__":
    unittest.main()
