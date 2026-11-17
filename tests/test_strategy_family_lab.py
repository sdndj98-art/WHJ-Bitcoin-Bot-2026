import unittest

from strategy_family_lab import build_strategy_signals, strategy_universe

class StrategyFamilyLabTests(unittest.TestCase):
    def candles(self, count=260):
        rows = []
        price = 100.0
        for i in range(count):
            price *= 1.001 if i % 17 else 0.997
            rows.append([i, price*0.999, price*1.01, price*0.99, price, 1000.0 + (i%9)*10])
        return rows

    def test_all_declared_implemented_signals_return_aligned_boolean_series(self):
        candles = self.candles()
        signals = build_strategy_signals(candles)
        declared = [name for names in strategy_universe()["implemented_signal_families"].values() for name in names]
        self.assertEqual(set(declared), set(signals))
        for values in signals.values():
            self.assertEqual(len(candles), len(values))
            self.assertTrue(all(type(value) is bool for value in values))

    def test_future_rows_do_not_change_prior_signals_at_multiple_cutoffs(self):
        candles = self.candles()
        baseline = build_strategy_signals(candles)
        for cutoff in (60, 120, 180, 220):
            changed = [list(row) for row in candles]
            for index, row in enumerate(changed[cutoff:], start=cutoff):
                row[0] += 1_000_000
                row[1] *= 1.7
                row[2] *= 1.7
                row[3] *= 1.7
                row[4] *= 1.7
                row[5] *= 3.0
            altered = build_strategy_signals(changed)
            for name in baseline:
                self.assertEqual(
                    baseline[name][:cutoff],
                    altered[name][:cutoff],
                    msg=f"{name} changed before perturbed future cutoff {cutoff}",
                )

    def test_zscore_candidate_is_distinct_from_bollinger_threshold(self):
        import math
        import random

        rng = random.Random(1234)
        rows = []
        price = 100.0
        for index in range(500):
            price *= math.exp(rng.gauss(0.0002, 0.012))
            rows.append([
                index, price, price * 1.005, price * 0.995,
                price, 1000.0,
            ])
        signals = build_strategy_signals(rows)
        # At this fixed deterministic bar, z=-1.7404: the -1.5 z-score
        # candidate enters while the stricter -2.0 Bollinger candidate stays flat.
        self.assertTrue(signals["zscore20_mean_reversion"][259])
        self.assertFalse(signals["bollinger_mean_reversion"][259])

    def test_invalid_candle_fails_closed(self):
        candles = self.candles()
        candles[20][2] = 1.0
        with self.assertRaises(ValueError):
            build_strategy_signals(candles)

    def test_duplicate_and_out_of_order_timestamps_are_rejected(self):
        duplicate = self.candles()
        duplicate[100][0] = duplicate[99][0]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            build_strategy_signals(duplicate)

        out_of_order = self.candles()
        out_of_order[100][0] = out_of_order[99][0] - 1
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            build_strategy_signals(out_of_order)

    def test_timestamp_values_must_be_finite_numeric_and_consistent(self):
        import math

        for invalid in (True, "100", math.nan, math.inf, -math.inf):
            rows = self.candles()
            rows[10][0] = invalid
            with self.subTest(timestamp=invalid):
                with self.assertRaisesRegex(ValueError, "timestamps must be finite numeric"):
                    build_strategy_signals(rows)

        rows = self.candles()
        rows[10] = rows[10][1:]
        with self.assertRaisesRegex(ValueError, "timestamps must be present"):
            build_strategy_signals(rows)

    def test_dictionary_timestamps_are_validated_when_supplied(self):
        rows = [
            {
                "timestamp": index,
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.5 + index,
                "volume": 1000.0,
            }
            for index in range(260)
        ]
        self.assertEqual(len(build_strategy_signals(rows)["sma200_regime"]), 260)
        rows[200]["timestamp"] = rows[199]["timestamp"]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            build_strategy_signals(rows)

    def test_dictionary_timestamps_may_be_omitted_consistently(self):
        rows = [
            {
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.5 + index,
                "volume": 1000.0,
            }
            for index in range(260)
        ]
        self.assertEqual(len(build_strategy_signals(rows)["sma200_regime"]), 260)

    def test_strategy_universe_labels_unimplemented_data_families(self):
        universe = strategy_universe()
        self.assertEqual(universe["promotion_status"], "RESEARCH_ONLY_NOT_EVALUATED")
        self.assertIn("funding_rate_carry", universe["deferred_data_families"]["derivatives"])

if __name__ == "__main__":
    unittest.main()