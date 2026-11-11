import unittest

from cusum_event_strategy_lab import (
    FEATURE_NAMES,
    _features_by_index,
    _fit_logistic,
    _matched_buy_hold,
    _purged_training_labels,
    _resolve_barrier_exit,
    _validate_bars,
)
from cusum_triple_barrier_lab import trailing_volatility


def bars(count=400):
    result = []
    price = 100.0
    for i in range(count):
        price *= 1.0005 if i % 3 else 0.999
        result.append({
            "timestamp": i * 3600000,
            "open": price * 0.999,
            "high": price * 1.003,
            "low": price * 0.997,
            "close": price,
            "volume": 1.0,
        })
    return result


class CusumEventStrategyLabTests(unittest.TestCase):
    def test_feature_values_are_prefix_causal(self):
        source = bars(700)
        closes = [row["close"] for row in source]
        sigma = trailing_volatility(closes, lookback=24)
        before = _features_by_index(closes, sigma)
        altered = closes[:500] + [value * (1.0 + 0.02 * (i - 499)) for i, value in enumerate(closes[500:], 500)]
        altered_sigma = trailing_volatility(altered, lookback=24)
        after = _features_by_index(altered, altered_sigma)
        self.assertEqual(before[:500], after[:500])

    def test_same_bar_stop_and_target_collision_is_stop_first(self):
        source = bars(400)
        source[251]["open"] = 100.0
        source[251]["high"] = 110.0
        source[251]["low"] = 90.0
        outcome = _resolve_barrier_exit(source, 250, 0.01)
        self.assertEqual(outcome["label"], -1)
        self.assertEqual(outcome["reason"], "stop_first_collision")
        self.assertEqual(outcome["entry_index"], 251)

    def test_training_labels_are_purged_with_embargo(self):
        labeled = [
            {"index": 100, "end_index": 200, "label": 1},
            {"index": 150, "end_index": 275, "label": -1},
            {"index": 180, "end_index": 276, "label": 1},
            {"index": 290, "end_index": 300, "label": 1},
            {"index": 100, "end_index": 200, "label": 0},
        ]
        selected = _purged_training_labels(labeled, 300)
        self.assertEqual(selected, [labeled[0], labeled[1]])

    def test_logistic_fit_is_deterministic_and_separates_simple_fixture(self):
        rows, labels = [], []
        for i in range(100):
            value = -1.0 if i < 50 else 1.0
            rows.append([value * (j + 1) for j in range(len(FEATURE_NAMES))])
            labels.append(-1 if i < 50 else 1)
        first = _fit_logistic(rows, labels)
        second = _fit_logistic(rows, labels)
        self.assertEqual(first["weights"], second["weights"])
        from cusum_event_strategy_lab import _predict_probability
        self.assertLess(_predict_probability(first, rows[0]), 0.5)
        self.assertGreater(_predict_probability(first, rows[-1]), 0.5)

    def test_buy_hold_uses_same_25_percent_allocation(self):
        source = bars(400)
        result = _matched_buy_hold(source, 300, 390, fee=0.0, slippage=0.0)
        self.assertEqual(result["allocation_fraction"], 0.25)
        self.assertEqual(result["uninvested_cash_usd"], 750.0)
        self.assertEqual(result["return_pct"], round(
            (source[389]["close"] / source[301]["open"] - 1.0) * 25.0, 4
        ))

    def test_hourly_timestamp_gaps_fail_closed(self):
        source = bars(400)
        source[200]["timestamp"] += 3600000
        with self.assertRaises(ValueError):
            _validate_bars(source)


if __name__ == "__main__":
    unittest.main()
