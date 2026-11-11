import unittest

from cusum_triple_barrier_lab import (
    cusum_event_indices,
    purged_past_event_indices,
    trailing_volatility,
    triple_barrier_labels,
)


class CusumTripleBarrierLabTests(unittest.TestCase):
    def test_cusum_uses_past_volatility_and_finds_large_move(self):
        closes = [100.0] * 25 + [102.0, 104.0, 106.0]
        events = cusum_event_indices(closes, volatility_lookback=10, threshold_multiplier=1.0)
        self.assertTrue(events)
        self.assertGreaterEqual(events[0], 11)

    def test_future_prices_do_not_change_prior_cusum_events(self):
        closes = [100.0 + 0.03 * i for i in range(40)]
        original = cusum_event_indices(closes, volatility_lookback=10)
        changed = closes[:30] + [value * 1.5 for value in closes[30:]]
        altered = cusum_event_indices(changed, volatility_lookback=10)
        self.assertEqual(
            [i for i in original if i < 30],
            [i for i in altered if i < 30],
        )

    def test_triple_barrier_enters_after_event_and_stops_on_first_touch(self):
        closes = [100.0, 100.0, 100.0, 103.0, 104.0, 105.0]
        volatility = [None, None, 0.01, 0.01, 0.01, 0.01]
        labels = triple_barrier_labels(
            closes, [1], volatility, profit_take=2.0, stop_loss=2.0, max_holding=3
        )
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0]["entry_index"], 2)
        self.assertEqual(labels[0]["end_index"], 3)
        self.assertEqual(labels[0]["label"], 1)

    def test_purge_removes_overlapping_and_embargoed_labels(self):
        labels = [
            {"event_index": 2, "end_index": 8},
            {"event_index": 3, "end_index": 9},
            {"event_index": 4, "end_index": 10},
            {"event_index": 12, "end_index": 13},
        ]
        self.assertEqual(purged_past_event_indices(labels, 10, embargo_bars=2), [])
        self.assertEqual(purged_past_event_indices(labels, 12, embargo_bars=2), [0, 1])

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            cusum_event_indices([100.0] * 10, volatility_lookback=20)
        with self.assertRaises(ValueError):
            triple_barrier_labels([100.0, 101.0, 102.0], [0], [None, None, None])
        with self.assertRaises(ValueError):
            purged_past_event_indices([], 10, embargo_bars=-1)


if __name__ == "__main__":
    unittest.main()
