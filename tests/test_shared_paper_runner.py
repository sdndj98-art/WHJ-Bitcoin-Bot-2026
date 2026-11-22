import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from shared_paper_portfolio import SharedPaperPortfolio, SUPPORTED_STRATEGIES
from shared_paper_runner import (
    _make_snapshot, _new_strategy_state, _ensure_strategy_state, liquidation_equity, strategy_signal,
)


class SharedPaperRunnerTests(unittest.TestCase):
    def test_eight_strategies_are_seeded_from_same_forward_cursor(self):
        rows = [[i * 3600, 1, 1, 1, 100 + i, 0] for i in range(220)]
        state = _new_strategy_state(rows)
        self.assertEqual(set(state), set(SUPPORTED_STRATEGIES))
        self.assertEqual({item["last_timestamp"] for item in state.values()}, {rows[-1][0]})
        self.assertTrue(all(len(item["recent_closes"]) == 200 for item in state.values()))

    def test_short_daily_sma_has_20_bar_warmup_while_other_strategies_wait(self):
        history = [100.0] * 29 + [101.0]
        want_long, want_flat = strategy_signal("sma_trend", history)
        self.assertTrue(want_long)
        self.assertFalse(want_flat)
        for strategy in (name for name in SUPPORTED_STRATEGIES if name != "sma_trend"):
            want_long, want_flat = strategy_signal(strategy, history)
            self.assertFalse(want_long)
            self.assertFalse(want_flat)

    def test_mean_reversion_strategies_use_indicator_specific_warmups(self):
        falling_15 = [100.0] * 14 + [80.0]
        rsi_entry, _ = strategy_signal("rsi14_mean_reversion", falling_15)
        self.assertTrue(rsi_entry)
        bollinger_entry, _ = strategy_signal("bollinger_mean_reversion", falling_15)
        self.assertFalse(bollinger_entry)

        falling_20 = [100.0] * 19 + [80.0]
        bollinger_entry, _ = strategy_signal("bollinger_mean_reversion", falling_20)
        self.assertTrue(bollinger_entry)
        rsi_entry, _ = strategy_signal("rsi14_mean_reversion", falling_20)
        self.assertTrue(rsi_entry)

        for strategy in ("ema_trend", "rsi_momentum", "sma200_regime",
                         "ema50_200_regime"):
            want_long, want_flat = strategy_signal(strategy, falling_20)
            self.assertFalse(want_long)
            self.assertFalse(want_flat)

    def test_mean_reversion_exits_have_defined_paper_conditions(self):
        falling = [100.0] * 19 + [80.0]
        _, bollinger_exit = strategy_signal("bollinger_mean_reversion", falling, holding_bars=10)
        _, rsi_exit = strategy_signal("rsi14_mean_reversion", falling, holding_bars=1)
        self.assertTrue(bollinger_exit)
        self.assertTrue(rsi_exit)

    def test_trend_signals_are_boolean_and_use_prior_completed_history(self):
        rising = [100.0 + i for i in range(220)]
        for strategy in ("sma_trend", "ema_trend", "sma200_regime", "ema50_200_regime"):
            want_long, want_flat = strategy_signal(strategy, rising)
            self.assertIsInstance(want_long, bool)
            self.assertIsInstance(want_flat, bool)
            self.assertTrue(want_long)
            self.assertFalse(want_flat)

    def test_compound_momentum_requires_trend_and_moderate_rsi(self):
        import math
        rising_with_pullbacks = [100 + i * 0.15 + math.sin(i * 0.7) for i in range(100)]
        want_long, want_flat = strategy_signal("compound_momentum", rising_with_pullbacks)
        self.assertTrue(want_long)
        self.assertFalse(want_flat)

        overheated = [100.0 + i for i in range(100)]
        want_long, _ = strategy_signal("compound_momentum", overheated)
        self.assertFalse(want_long)

        falling = [150.0 - i * 0.5 for i in range(100)]
        want_long, want_flat = strategy_signal("compound_momentum", falling)
        self.assertFalse(want_long)
        self.assertTrue(want_flat)

    def test_compound_momentum_allows_mild_pullback_without_chasing(self):
        import math
        rising = [100 + i * 0.2 + math.sin(i * 0.7) * 0.5 for i in range(100)]
        start = rising[-8]
        rising[-8:] = [start - j * 0.3 for j in range(8)]
        want_long, want_flat = strategy_signal("compound_momentum", rising)
        self.assertTrue(want_long)
        self.assertFalse(want_flat)

        overheated = [100.0 + i for i in range(100)]
        want_long, _ = strategy_signal("compound_momentum", overheated)
        self.assertFalse(want_long)

    def test_existing_strategy_state_migrates_without_resetting_cursors(self):
        rows = [[i * 3600, 1, 1, 1, 100 + i, 0] for i in range(220)]
        state = _new_strategy_state(rows)
        state["sma_trend"]["last_timestamp"] = 12345
        del state["compound_momentum"]
        added = _ensure_strategy_state(state, rows)
        self.assertEqual(added, ["compound_momentum"])
        self.assertEqual(state["sma_trend"]["last_timestamp"], 12345)
        self.assertEqual(state["compound_momentum"]["last_timestamp"], rows[-1][0])

    def test_strategy_equity_attribution_matches_shared_portfolio_equity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = SharedPaperPortfolio(root / "ledger.json", 100)
            book.open_position("sma_trend", "BTC/USD", 100.0, 10.0, "open-sma")
            book.open_position("ema_trend", "BTC/USD", 100.0, 10.0, "closed-ema")
            book.close_position("closed-ema", 110.0, reason="TEST_PROFIT")
            rows = [[i * 3600, 1, 1, 1, 100 + i, 0] for i in range(220)]
            with patch("shared_paper_runner.SNAPSHOT", root / "dual_portfolio.json"):
                output = _make_snapshot(
                    book, _new_strategy_state(rows), 110.0,
                    {"quality": "HEALTHY"}, "PAPER_RUNNING",
                )
            strategy_rows = output["strategies"]
            strategy_equity = sum(item["equity_usd"] for item in strategy_rows)
            shared_equity = output["shared_portfolio"]["equity_usd"]
            self.assertAlmostEqual(strategy_equity, shared_equity, places=6)
            by_name = {item["strategy"]: item for item in strategy_rows}
            self.assertGreater(by_name["ema_trend"]["realized_pnl_usd"], 0)
            self.assertGreater(by_name["sma_trend"]["unrealized_pnl_usd"], 0)
            self.assertGreaterEqual(by_name["sma_trend"]["max_drawdown_pct"], 0)
            self.assertGreaterEqual(by_name["sma_trend"]["current_drawdown_pct"], 0)
            self.assertAlmostEqual(
                by_name["ema_trend"]["equity_usd"],
                by_name["ema_trend"]["initial_equity_usd"]
                + by_name["ema_trend"]["net_pnl_usd"],
                places=6,
            )

    def test_strategy_drawdown_peak_is_persisted_and_sampled_per_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = SharedPaperPortfolio(root / "ledger.json", 100)
            book.open_position("sma_trend", "BTC/USD", 100.0, 10.0, "open-sma")
            rows = [[i * 3600, 1, 1, 1, 100 + i, 0] for i in range(220)]
            state = _new_strategy_state(rows)
            with patch("shared_paper_runner.SNAPSHOT", root / "dual_portfolio.json"):
                first = _make_snapshot(
                    book, state, 110.0, {"quality": "HEALTHY"}, "PAPER_RUNNING"
                )
                second = _make_snapshot(
                    book, state, 90.0, {"quality": "HEALTHY"}, "PAPER_RUNNING"
                )
            first_row = next(x for x in first["strategies"] if x["strategy"] == "sma_trend")
            second_row = next(x for x in second["strategies"] if x["strategy"] == "sma_trend")
            self.assertGreater(first_row["equity_usd"], second_row["equity_usd"])
            self.assertGreater(second_row["max_drawdown_pct"], 0)
            self.assertEqual(
                state["sma_trend"]["max_strategy_drawdown_pct"],
                second_row["max_drawdown_pct"],
            )
            self.assertEqual(
                second_row["drawdown_observation"],
                "COMPLETED_CANDLE_SNAPSHOT_SAMPLED",
            )

    def test_btc_runner_marks_other_shared_assets_from_fresh_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = SharedPaperPortfolio(root / "ledger.json", 100)
            book.open_position("sma_trend", "ETH/USD", 2000.0, 2.0, "multi-ETH")
            book.open_position("sma_trend", "BTC/USD", 50000.0, 2.0, "btc-sma")
            prior = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "shared_portfolio": {
                    "open_positions": [
                        {"position_id": "multi-ETH", "asset": "ETH/USD",
                         "mark_price": 2100.0},
                    ],
                },
            }
            snapshot_path = root / "dual_portfolio.json"
            snapshot_path.write_text(json.dumps(prior), encoding="utf-8")
            rows = [[i * 3600, 1, 1, 1, 100 + i, 0] for i in range(220)]
            with patch("shared_paper_runner.SNAPSHOT", snapshot_path):
                equity = liquidation_equity(book, 51000.0)
                output = _make_snapshot(
                    book, _new_strategy_state(rows), 51000.0,
                    {"quality": "HEALTHY"}, "PAPER_RUNNING",
                )
            self.assertGreater(equity, 95.0)
            positions = {p["asset"]: p for p in output["shared_portfolio"]["open_positions"]}
            self.assertEqual(positions["ETH/USD"]["mark_price"], 2100.0)
            self.assertEqual(positions["BTC/USD"]["mark_price"], 51000.0)
            self.assertAlmostEqual(output["shared_portfolio"]["equity_usd"], equity, places=6)

    def test_btc_runner_fails_closed_when_non_btc_mark_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = SharedPaperPortfolio(root / "ledger.json", 100)
            book.open_position("sma_trend", "ETH/USD", 2000.0, 2.0, "multi-ETH")
            stale = {
                "updated_at": "2020-01-01T00:00:00+00:00",
                "shared_portfolio": {
                    "open_positions": [
                        {"position_id": "multi-ETH", "asset": "ETH/USD",
                         "mark_price": 2100.0},
                    ],
                },
            }
            snapshot_path = root / "dual_portfolio.json"
            snapshot_path.write_text(json.dumps(stale), encoding="utf-8")
            with patch("shared_paper_runner.SNAPSHOT", snapshot_path):
                with self.assertRaises(RuntimeError):
                    liquidation_equity(book, 51000.0)

    def test_shared_strategy_cursor_persists_with_same_100_dollar_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared.json"
            book = SharedPaperPortfolio(path, 100)
            cursor = {"sma_trend": {"last_timestamp": 123, "recent_closes": [1.0]}}
            book.save_strategy_state(cursor)
            restored = SharedPaperPortfolio(path, 100)
            self.assertEqual(restored.state["strategy_state"], cursor)
            self.assertEqual(restored.state["cash_usd"], 100.0)
            self.assertFalse(restored.state["live_trading_enabled"])


if __name__ == "__main__":
    unittest.main()
