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

    def test_future_rows_do_not_change_prior_signals(self):
        candles = self.candles()
        baseline = build_strategy_signals(candles)
        changed = [list(row) for row in candles]
        for row in changed[180:]:
            row[1] *= 1.7
            row[2] *= 1.7
            row[3] *= 1.7
            row[4] *= 1.7
        altered = build_strategy_signals(changed)
        for name in baseline:
            self.assertEqual(baseline[name][:180], altered[name][:180])

    def test_invalid_candle_fails_closed(self):
        candles = self.candles()
        candles[20][2] = 1.0
        with self.assertRaises(ValueError):
            build_strategy_signals(candles)

    def test_strategy_universe_labels_unimplemented_data_families(self):
        universe = strategy_universe()
        self.assertEqual(universe["promotion_status"], "RESEARCH_ONLY_NOT_EVALUATED")
        self.assertIn("funding_rate_carry", universe["deferred_data_families"]["derivatives"])

if __name__ == "__main__":
    unittest.main()