import unittest

from xauusd_broker_data import (
    parse_xauusd_bid_ask_csv,
    estimate_xauusd_round_trip,
    validate_xauusd_cost_model,
)

SESSION = {
    "weekly_open_weekday": 6,
    "weekly_open_minute_utc": 22 * 60,
    "weekly_close_weekday": 4,
    "weekly_close_minute_utc": 21 * 60,
    "daily_breaks_utc": [{"start_minute_utc": 21 * 60, "end_minute_utc": 22 * 60}],
    "closed_dates_utc": [],
}

COSTS = {
    "contract_size_oz_per_lot": 100.0,
    "commission_usd_per_lot_per_side": 7.0,
    "slippage_bps_per_side": 1.0,
    "swap_long_usd_per_oz_per_rollover": -0.10,
    "swap_short_usd_per_oz_per_rollover": -0.05,
    "triple_swap_weekday": 2,
    "quote_currency": "USD",
}


def csv_row(stamp="2026-11-09T10:00:00Z", symbol="XAUUSD", timeframe=60,
            bid=2000.0, ask=2000.5):
    return (
        f"{symbol},{timeframe},{stamp},"
        f"{bid},{bid+2},{bid-2},{bid+0.2},"
        f"{ask},{ask+2},{ask-2},{ask+0.2}"
    )


def csv_text(*rows):
    return (
        "symbol,timeframe_minutes,timestamp_utc,"
        "bid_open,bid_high,bid_low,bid_close,"
        "ask_open,ask_high,ask_low,ask_close\n"
        + "\n".join(rows) + "\n"
    )


class XAUUSDBrokerDataTests(unittest.TestCase):
    def parse(self, value):
        return parse_xauusd_bid_ask_csv(
            value, expected_timeframe_minutes=60,
            session_config=SESSION, source_id="broker-demo-export-v1",
        )

    def test_parses_bid_ask_and_preserves_spread_and_hash(self):
        result = self.parse(csv_text(csv_row(), csv_row("2026-11-09T11:00:00Z")))
        self.assertEqual(result["symbol"], "XAUUSD")
        self.assertEqual(result["bar_count"], 2)
        self.assertEqual(result["imputed_bar_count"], 0)
        self.assertEqual(result["observed_timestamp_gap_count_including_scheduled_closures"], 0)
        self.assertEqual(len(result["dataset_sha256"]), 64)
        self.assertAlmostEqual(result["bars"][0]["spread_open_bps"], 2.4997, places=3)
        self.assertEqual(result["source_id"], "broker-demo-export-v1")

    def test_reports_gaps_without_imputing_them(self):
        result = self.parse(csv_text(csv_row(), csv_row("2026-11-09T12:00:00Z")))
        self.assertEqual(result["observed_timestamp_gap_count_including_scheduled_closures"], 1)
        self.assertEqual(result["imputed_bar_count"], 0)

    def test_rejects_non_xauusd_symbol_and_timeframe_mismatch(self):
        with self.assertRaisesRegex(ValueError, "expected XAUUSD"):
            self.parse(csv_text(csv_row(symbol="GC=F")))
        with self.assertRaisesRegex(ValueError, "timeframe"):
            self.parse(csv_text(csv_row(timeframe=15)))

    def test_rejects_naive_duplicate_or_out_of_order_timestamps(self):
        with self.assertRaisesRegex(ValueError, "explicit UTC offset"):
            self.parse(csv_text(csv_row("2026-11-09T10:00:00")))
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            self.parse(csv_text(csv_row(), csv_row()))
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            self.parse(csv_text(csv_row("2026-11-09T11:00:00Z"), csv_row()))

    def test_rejects_invalid_ohlc_or_crossed_quotes(self):
        crossed = csv_row(ask=1999.0)
        with self.assertRaisesRegex(ValueError, "ask open is below bid"):
            self.parse(csv_text(crossed))
        impossible = csv_row().replace("2002.0", "1990.0", 1)
        with self.assertRaises(ValueError):
            self.parse(csv_text(impossible))

    def test_rejects_bars_overlapping_daily_break_or_weekly_close(self):
        with self.assertRaisesRegex(ValueError, "rollover/break"):
            self.parse(csv_text(csv_row("2026-11-09T20:30:00Z")))
        with self.assertRaisesRegex(ValueError, "weekly session boundary"):
            self.parse(csv_text(csv_row("2026-11-13T20:30:00Z")))

    def test_requires_explicit_session_and_cost_assumptions(self):
        with self.assertRaisesRegex(ValueError, "session_config"):
            parse_xauusd_bid_ask_csv(
                csv_text(csv_row()), expected_timeframe_minutes=60,
                session_config=None, source_id="broker",
            )
        with self.assertRaisesRegex(ValueError, "cost_model missing"):
            validate_xauusd_cost_model({"quote_currency": "USD"})

    def test_rejects_non_usd_quote_and_negative_execution_costs(self):
        non_usd = dict(COSTS, quote_currency="EUR")
        with self.assertRaisesRegex(ValueError, "USD-quoted"):
            validate_xauusd_cost_model(non_usd)

        negative_commission = dict(COSTS, commission_usd_per_lot_per_side=-0.01)
        with self.assertRaisesRegex(ValueError, "non-negative"):
            validate_xauusd_cost_model(negative_commission)

        negative_slippage = dict(COSTS, slippage_bps_per_side=-0.1)
        with self.assertRaisesRegex(ValueError, "non-negative"):
            validate_xauusd_cost_model(negative_slippage)

    def test_round_trip_costs_include_spread_slippage_commission_and_triple_swap(self):
        result = estimate_xauusd_round_trip(
            side="long", lots=1.0,
            entry_bid=2000.0, entry_ask=2000.5,
            exit_bid=2010.0, exit_ask=2010.5,
            rollover_dates=["2026-11-11", "2026-11-12"],
            cost_model=COSTS,
        )
        self.assertAlmostEqual(result["quantity_oz"], 100.0)
        self.assertAlmostEqual(result["spread_cost_usd_diagnostic_only"], 50.0, places=6)
        self.assertAlmostEqual(result["commission_cost_usd"], 14.0, places=6)
        self.assertAlmostEqual(result["swap_pnl_usd"], -40.0, places=6)
        self.assertGreater(result["slippage_cost_usd"], 0)
        self.assertAlmostEqual(result["net_pnl_usd"], 855.895, places=3)
        self.assertFalse(result["live_orders"])

    def test_short_side_uses_bid_entry_ask_exit_and_short_swap(self):
        result = estimate_xauusd_round_trip(
            side="short", lots=0.1,
            entry_bid=2000.0, entry_ask=2000.5,
            exit_bid=1990.0, exit_ask=1990.5,
            rollover_dates=["2026-11-12"],
            cost_model=COSTS,
        )
        self.assertAlmostEqual(result["quantity_oz"], 10.0)
        self.assertAlmostEqual(result["swap_pnl_usd"], -0.5, places=6)
        self.assertGreater(result["spread_cost_usd_diagnostic_only"], 0)

    def test_rejects_unsorted_rollover_dates(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            estimate_xauusd_round_trip(
                side="long", lots=1,
                entry_bid=2000, entry_ask=2000.5,
                exit_bid=2010, exit_ask=2010.5,
                rollover_dates=["2026-11-12", "2026-11-11"],
                cost_model=COSTS,
            )


if __name__ == "__main__":
    unittest.main()
