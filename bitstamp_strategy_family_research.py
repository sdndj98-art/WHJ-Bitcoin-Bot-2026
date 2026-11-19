"""Independent Bitstamp evaluation of the 17 predeclared BTC signal-state candidates.

Research only. Reuses the public Bitstamp OHLC loader and the exact same
candidate/evaluator definitions as the Coinbase experiment. Fixed costs are
held constant to isolate venue-price-series sensitivity; they are not a
Bitstamp fee quote or a broker execution model.
"""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from ema_adx_cross_exchange_lab import fetch_bitstamp_hourly_candles
from research_governance import (
    build_trial_manifest,
    cscv_probability_of_backtest_overfitting_with_tail_trim,
    moving_block_bootstrap_return_ci,
)
from research_snapshot import canonical_json_bytes, gzip_snapshot_bytes, sha256_bytes
from rolling_walk_forward import evaluate_rolling_walk_forward
from strategy_ranking import rank_fixed_candidate_walk_forward
from strategy_family_lab import build_strategy_signals
from strategy_family_runner import run_strategy_universe

SOURCE = "Bitstamp public BTCUSD spot OHLC"
SYMBOL = "BTCUSD"
INTERVAL_MS = 60 * 60 * 1000
ALLOCATION_FRACTION = 0.25
BASE_FEE_PER_SIDE = 0.001
BASE_SLIPPAGE_PER_SIDE = 0.0005
BARS_PER_YEAR = 24 * 365
COINBASE_REFERENCE_WINDOW = {
    "run_id": "44631838327",
    "code_commit_sha": "3406a98eca240a628dabb760debac4982ab2a904",
    "dataset_sha256": "25a2ebdce5893d499759b6d990bbe628ee36e52bf22a04277b79e4f9b1f202d1",
    "first_oos_open_timestamp_utc": "2025-08-26T22:00:00+00:00",
    "last_candle_timestamp_utc": "2026-11-19T21:00:00+00:00",
    "open_to_open_returns": 10799,
}


def _validate_gap_free_hourly_candles(candles):
    if not isinstance(candles, (list, tuple)) or len(candles) < 1000:
        raise ValueError("At least 1000 hourly Bitstamp candles are required")
    previous = None
    for index, row in enumerate(candles):
        if not isinstance(row, dict):
            raise ValueError("Bitstamp candles must be dictionaries")
        try:
            timestamp = row["timestamp"]
            values = [row[key] for key in ("open", "high", "low", "close", "volume")]
        except (KeyError, TypeError) as exc:
            raise ValueError("Bitstamp candle is missing a required field") from exc
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise ValueError("Bitstamp timestamps must be non-negative integer milliseconds")
        if timestamp % INTERVAL_MS:
            raise ValueError("Bitstamp timestamps must align to UTC hourly boundaries")
        if previous is not None and timestamp - previous != INTERVAL_MS:
            raise ValueError("Bitstamp dataset must be strictly ordered and gap-free")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise ValueError("Bitstamp OHLCV values must be finite numbers")
        open_price, high, low, close, volume = map(float, values)
        if min(open_price, high, low, close) <= 0 or volume < 0:
            raise ValueError("Bitstamp prices must be positive and volume non-negative")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Invalid Bitstamp OHLC relationship")
        previous = timestamp
    return True


def _market_regimes(candles):
    """Classify each completed close using only its own/past 200-SMA and slope."""
    closes = [float(row["close"]) for row in candles]
    sma = [None] * len(closes)
    rolling_sum = 0.0
    for index, value in enumerate(closes):
        rolling_sum += value
        if index >= 200:
            rolling_sum -= closes[index - 200]
        if index >= 199:
            sma[index] = rolling_sum / 200.0

    labels = ["unclassified"] * len(closes)
    for index, close in enumerate(closes):
        if index < 219 or sma[index] is None or sma[index - 20] is None:
            continue
        if close > sma[index] and sma[index] > sma[index - 20]:
            labels[index] = "bullish"
        elif close < sma[index] and sma[index] < sma[index - 20]:
            labels[index] = "bearish"
        else:
            labels[index] = "sideways_transition"
    return labels


def _regime_return_attribution(candles, signals, evaluation_start_index, base_report):
    """Attribute each open-to-open net return to the regime known at its signal close.

    Log-return contributions are additive across regimes and reproduce the
    full-period compounded return. This is an attribution, not an independent
    regime-specific portfolio or a causal regime-switching strategy.
    """
    labels = _market_regimes(candles)
    result = {}
    for name, candidate in base_report["results"].items():
        returns = candidate["net_returns"]
        benchmark = candidate["benchmark_net_returns"]
        signal_series = signals[name]
        if len(returns) != len(benchmark):
            raise ValueError("Candidate and benchmark return streams are not aligned")
        buckets = {}
        for offset, (net_return, benchmark_return) in enumerate(zip(returns, benchmark)):
            signal_index = evaluation_start_index - 1 + offset
            regime = labels[signal_index]
            bucket = buckets.setdefault(regime, {
                "bars": 0,
                "active_signal_bars": 0,
                "strategy_log_return": 0.0,
                "benchmark_log_return": 0.0,
                "positive_net_return_bars": 0,
                "net_return_sum": 0.0,
            })
            if net_return <= -1 or benchmark_return <= -1:
                raise ValueError("Periodic return cannot be <= -100%")
            bucket["bars"] += 1
            bucket["active_signal_bars"] += int(signal_series[signal_index])
            bucket["strategy_log_return"] += math.log1p(net_return)
            bucket["benchmark_log_return"] += math.log1p(benchmark_return)
            bucket["positive_net_return_bars"] += int(net_return > 0)
            bucket["net_return_sum"] += net_return

        attribution = {}
        for regime, bucket in buckets.items():
            count = bucket["bars"]
            strategy_log = bucket["strategy_log_return"]
            benchmark_log = bucket["benchmark_log_return"]
            attribution[regime] = {
                "bars": count,
                "active_signal_bars": bucket["active_signal_bars"],
                "strategy_log_growth": round(strategy_log, 12),
                "benchmark_log_growth": round(benchmark_log, 12),
                "strategy_attributed_compounded_return_pct": round(math.expm1(strategy_log) * 100, 4),
                "matched_benchmark_attributed_compounded_return_pct": round(math.expm1(benchmark_log) * 100, 4),
                "excess_log_growth_percentage_points": round((strategy_log - benchmark_log) * 100, 4),
                "mean_net_return_bps": round(bucket["net_return_sum"] / count * 10000, 4),
                "positive_net_return_bar_pct": round(bucket["positive_net_return_bars"] / count * 100, 4),
                "interpretation": "Bar-level attribution by regime known at the prior close; not a standalone regime portfolio.",
            }
        total_log = sum(item["strategy_log_return"] for item in buckets.values())
        total_return = math.expm1(total_log)
        reported_return = candidate["strategy"]["net_return"]
        if not math.isclose(total_return, reported_return, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("Regime log-return attribution does not reconcile to candidate OOS equity")
        result[name] = attribution
    return {
        "classification": "bullish: close > 200-SMA and 200-SMA rising over 20 bars; bearish: close < 200-SMA and 200-SMA falling over 20 bars; otherwise sideways/transition",
        "measurement": "Each net open-to-open return is attributed to the regime known at the prior completed close. Regime log contributions reconcile exactly to total OOS log growth; these are not separate regime portfolios.",
        "candidate_attribution": result,
    }


def _ranking_rows(base_report, cost_reports):
    rows = []
    ordered = sorted(
        base_report["results"],
        key=lambda name: (
            base_report["results"][name]["strategy"]["net_return"],
            name,
        ),
        reverse=True,
    )
    for rank, name in enumerate(ordered, start=1):
        result = base_report["results"][name]
        strategy = result["strategy"]
        benchmark = result["buy_and_hold"]
        rows.append({
            "rank_by_net_return": rank,
            "candidate": name,
            "net_return_pct": round(strategy["net_return"] * 100, 4),
            "matched_buy_and_hold_pct": round(benchmark["net_return"] * 100, 4),
            "excess_vs_buy_and_hold_pp": round((strategy["net_return"] - benchmark["net_return"]) * 100, 4),
            "max_open_to_open_drawdown_pct": round(abs(strategy["max_drawdown"]) * 100, 4),
            "periodic_profit_factor": strategy["profit_factor"],
            "period_sharpe": strategy["period_sharpe"],
            "closed_trades": strategy["closed_trades"],
            "exposure_pct": round(strategy["exposure"] * 100, 4),
            "open_position_at_end": strategy["open_position_at_end"],
            "return_2x_pct": round(cost_reports["2x"]["results"][name]["strategy"]["net_return"] * 100, 4),
            "return_3x_pct": round(cost_reports["3x"]["results"][name]["strategy"]["net_return"] * 100, 4),
        })
    return rows


def build_matched_calendar_overlap_report(
    candles,
    reference_window,
    run_id,
    code_commit_sha,
    generated_at_utc,
    bootstrap_samples=1000,
):
    """Evaluate Bitstamp over the exact pinned Coinbase OOS calendar window.

    The first OOS signal is the completed candle immediately before the
    reference first-open timestamp; the last candle is the reference endpoint.
    Only the Bitstamp prefix through that endpoint is used, preventing future
    rows from influencing this matched-date comparison.
    """
    _validate_gap_free_hourly_candles(candles)
    if not isinstance(reference_window, dict):
        raise ValueError("reference_window must be a mapping")
    required = (
        "run_id", "code_commit_sha", "dataset_sha256",
        "first_oos_open_timestamp_utc", "last_candle_timestamp_utc",
        "open_to_open_returns",
    )
    if any(key not in reference_window for key in required):
        raise ValueError("reference_window is missing required provenance fields")
    if isinstance(reference_window["open_to_open_returns"], bool) or not isinstance(
        reference_window["open_to_open_returns"], int
    ) or reference_window["open_to_open_returns"] < 8:
        raise ValueError("reference open-to-open return count must be an integer >= 8")

    def to_timestamp_ms(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("reference timestamps must be non-empty ISO strings")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("reference timestamps must include a timezone")
        return int(parsed.timestamp() * 1000)

    timestamp_index = {row["timestamp"]: index for index, row in enumerate(candles)}
    first_ms = to_timestamp_ms(reference_window["first_oos_open_timestamp_utc"])
    last_ms = to_timestamp_ms(reference_window["last_candle_timestamp_utc"])
    if first_ms not in timestamp_index or last_ms not in timestamp_index:
        raise ValueError("Bitstamp history does not contain both exact reference timestamps")
    start_index = timestamp_index[first_ms]
    end_index = timestamp_index[last_ms]
    expected_returns = reference_window["open_to_open_returns"]
    if start_index < 1 or end_index - start_index != expected_returns:
        raise ValueError("Bitstamp reference timestamps do not span the exact reference return count")

    matched_candles = candles[:end_index + 1]
    matched_oos_slice = candles[start_index - 1:end_index + 1]
    matched_slice_sha256 = sha256_bytes(canonical_json_bytes(matched_oos_slice))
    cost_levels = {
        "1x": (BASE_FEE_PER_SIDE, BASE_SLIPPAGE_PER_SIDE),
        "2x": (BASE_FEE_PER_SIDE * 2, BASE_SLIPPAGE_PER_SIDE * 2),
        "3x": (BASE_FEE_PER_SIDE * 3, BASE_SLIPPAGE_PER_SIDE * 3),
    }
    cost_reports = {
        level: run_strategy_universe(
            matched_candles,
            fee_rate=fee,
            slippage_rate=slippage,
            bars_per_year=BARS_PER_YEAR,
            evaluation_start_index=start_index,
            allocation_fraction=ALLOCATION_FRACTION,
        )
        for level, (fee, slippage) in cost_levels.items()
    }
    base = cost_reports["1x"]
    return_matrix = {
        name: item["net_returns"]
        for name, item in base["results"].items()
    }
    return_count = len(next(iter(return_matrix.values())))
    if return_count != expected_returns:
        raise ValueError("Matched Bitstamp OOS return count does not equal the Coinbase reference")
    pbo = None
    pbo_status = "INSUFFICIENT_OOS_OBSERVATIONS"
    if return_count >= 800:
        pbo = cscv_probability_of_backtest_overfitting_with_tail_trim(
            return_matrix, partitions=8
        )
        pbo_status = "COMPUTED_DIAGNOSTIC_ONLY"

    ranking = _ranking_rows(base, cost_reports)
    bootstrap_ci = {}
    for index, row in enumerate(ranking[:5]):
        bootstrap_ci[row["candidate"]] = moving_block_bootstrap_return_ci(
            base["results"][row["candidate"]]["net_returns"],
            block_length=min(24, return_count),
            bootstrap_samples=bootstrap_samples,
            confidence_level=0.95,
            seed=20261121 + index,
        )
    matched_signals = build_strategy_signals(matched_candles)
    return {
        "status": "COMPUTED_EXACT_CALENDAR_OVERLAP",
        "source": SOURCE,
        "symbol": SYMBOL,
        "reference": {
            "source": "Coinbase public BTC-USD hourly spot",
            "run_id": reference_window["run_id"],
            "code_commit_sha": reference_window["code_commit_sha"],
            "dataset_sha256": reference_window["dataset_sha256"],
            "first_oos_open_timestamp_utc": reference_window["first_oos_open_timestamp_utc"],
            "last_candle_timestamp_utc": reference_window["last_candle_timestamp_utc"],
            "open_to_open_returns": expected_returns,
        },
        "bitstamp": {
            "code_commit_sha": code_commit_sha,
            "run_id": run_id,
            "start_index": start_index,
            "end_index_inclusive": end_index,
            "first_oos_open_timestamp_utc": datetime.fromtimestamp(first_ms / 1000, timezone.utc).isoformat(),
            "last_candle_timestamp_utc": datetime.fromtimestamp(last_ms / 1000, timezone.utc).isoformat(),
            "matched_oos_candle_count_including_prior_signal_and_endpoint": len(matched_oos_slice),
            "open_to_open_returns": return_count,
            "matched_oos_slice_sha256": matched_slice_sha256,
        },
        "protocol": {
            "allocation_fraction": ALLOCATION_FRACTION,
            "fee_per_side_1x": BASE_FEE_PER_SIDE,
            "slippage_per_side_1x": BASE_SLIPPAGE_PER_SIDE,
            "cost_multipliers": ["1x", "2x", "3x"],
            "signal_timing": "completed close; position changes at next open",
            "return_interval": "next open to following open",
            "benchmark": "matched 25% buy-and-hold on the exact same calendar intervals",
            "cost_warning": "The fixed fee/slippage assumptions match the Coinbase experiment for controlled comparison; they are not actual Bitstamp fees, spread, or measured execution costs.",
        },
        "candidate_count": len(base["results"]),
        "ranking_by_net_return": ranking,
        "cost_stress": {
            level: {
                name: {
                    "strategy": result["strategy"],
                    "buy_and_hold": result["buy_and_hold"],
                    "excess_return": result["excess_return"],
                }
                for name, result in report["results"].items()
            }
            for level, report in cost_reports.items()
        },
        "cscv_pbo": pbo,
        "cscv_pbo_status": pbo_status,
        "cscv_pbo_scope_warning": "Diagnostic across only these 17 fixed signal-state proxies on this exact matched calendar segment; not a future-profit probability or a global experiment census.",
        "top_five_conditional_moving_block_bootstrap_95pct_ci": bootstrap_ci,
        "market_regime_attribution": _regime_return_attribution(
            matched_candles, matched_signals, start_index, base
        ),
        "candidate_semantics": "Same predeclared boolean long/flat signal-state proxies as the Coinbase reference; no rules or parameters were changed.",
        "promotion_status": "NO_CANDIDATE_PROMOTED",
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "execution_enabled": False,
    }


def build_bitstamp_strategy_report(
    candles,
    run_id,
    code_commit_sha,
    generated_at_utc=None,
    bootstrap_samples=1000,
    reference_window=COINBASE_REFERENCE_WINDOW,
):
    """Build a complete independent-venue report for all 17 existing BTC proxies."""
    _validate_gap_free_hourly_candles(candles)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(code_commit_sha, str) or len(code_commit_sha) != 40:
        raise ValueError("code_commit_sha must be a 40-character commit SHA")
    generated = generated_at_utc or datetime.now(timezone.utc).isoformat()
    dataset_payload = canonical_json_bytes(candles)
    dataset_sha256 = sha256_bytes(dataset_payload)
    split_index = int(len(candles) * 0.70)
    if split_index < 250 or len(candles) - split_index < 32:
        raise ValueError("Insufficient chronological training or OOS observations")

    cost_levels = {
        "1x": (BASE_FEE_PER_SIDE, BASE_SLIPPAGE_PER_SIDE),
        "2x": (BASE_FEE_PER_SIDE * 2, BASE_SLIPPAGE_PER_SIDE * 2),
        "3x": (BASE_FEE_PER_SIDE * 3, BASE_SLIPPAGE_PER_SIDE * 3),
    }
    cost_reports = {
        level: run_strategy_universe(
            candles,
            fee_rate=fee,
            slippage_rate=slippage,
            bars_per_year=BARS_PER_YEAR,
            evaluation_start_index=split_index,
            allocation_fraction=ALLOCATION_FRACTION,
        )
        for level, (fee, slippage) in cost_levels.items()
    }
    base = cost_reports["1x"]
    matched_calendar_overlap = None
    if reference_window is not None:
        matched_calendar_overlap = build_matched_calendar_overlap_report(
            candles,
            reference_window,
            run_id=run_id,
            code_commit_sha=code_commit_sha,
            generated_at_utc=generated,
            bootstrap_samples=bootstrap_samples,
        )
    signals = build_strategy_signals(candles)
    initial_train_bars = int(len(candles) * 0.55)
    test_bars = max(32, int(len(candles) * 0.10))
    walk_forward = evaluate_rolling_walk_forward(
        candles,
        signals,
        initial_train_bars=initial_train_bars,
        test_bars=test_bars,
        fee_rate=BASE_FEE_PER_SIDE,
        slippage_rate=BASE_SLIPPAGE_PER_SIDE,
        bars_per_year=BARS_PER_YEAR,
        allocation_fraction=ALLOCATION_FRACTION,
        max_folds=3,
    )
    walk_forward_candidate_ranking = rank_fixed_candidate_walk_forward(
        walk_forward["fixed_candidate_walk_forward"]["candidates"]
    )

    return_matrix = {
        name: item["net_returns"]
        for name, item in base["results"].items()
    }
    return_count = len(next(iter(return_matrix.values())))
    pbo = None
    pbo_status = "INSUFFICIENT_OOS_OBSERVATIONS"
    if return_count >= 800:
        pbo = cscv_probability_of_backtest_overfitting_with_tail_trim(
            return_matrix, partitions=8
        )
        pbo_status = "COMPUTED_DIAGNOSTIC_ONLY"

    ranking = _ranking_rows(base, cost_reports)
    bootstrap_ci = {}
    for index, row in enumerate(ranking[:5]):
        candidate_returns = base["results"][row["candidate"]]["net_returns"]
        bootstrap_ci[row["candidate"]] = moving_block_bootstrap_return_ci(
            candidate_returns,
            block_length=min(24, len(candidate_returns)),
            bootstrap_samples=bootstrap_samples,
            confidence_level=0.95,
            seed=20261117 + index,
        )

    manifests = [
        build_trial_manifest(
            trial_id=f"bitstamp-btc-family-{name}-{run_id}",
            candidate_id=name,
            parameters={
                "fee_rate_per_side": BASE_FEE_PER_SIDE,
                "slippage_rate_per_side": BASE_SLIPPAGE_PER_SIDE,
                "allocation_fraction": ALLOCATION_FRACTION,
                "bars_per_year": BARS_PER_YEAR,
                "signal_semantics": "predeclared long_flat_signal_state_proxy",
            },
            dataset_sha256=dataset_sha256,
            data_source=SOURCE,
            code_commit_sha=code_commit_sha,
            run_id=run_id,
            created_utc=generated,
            evaluation_protocol="70/30 chronological split; completed-close signal; next-open exposure; open-to-open net returns; matched 25% buy-and-hold; 1x/2x/3x fixed cost stress.",
        )
        for name in base["results"]
    ]
    walk_forward_manifests = []
    selection_margins = []
    for fold in walk_forward["folds"]:
        ordered_scores = sorted(
            fold["training_excess_returns"].items(),
            key=lambda item: (-item[1], item[0]),
        )
        margin = (
            ordered_scores[0][1] - ordered_scores[1][1]
            if len(ordered_scores) > 1 else None
        )
        selection_margins.append({
            "fold": fold["fold"],
            "selected_candidate": fold["selected_candidate"],
            "best_training_excess_return": ordered_scores[0][1],
            "runner_up_candidate": ordered_scores[1][0] if len(ordered_scores) > 1 else None,
            "selection_margin": margin,
            "selection_rule": fold["selection_rule"],
        })
        walk_forward_manifests.append(
            build_trial_manifest(
                trial_id=f"bitstamp-wf-fold-{fold['fold']}-{fold['selected_candidate']}-{run_id}",
                candidate_id=fold["selected_candidate"],
                parameters={
                    "fold": fold["fold"],
                    "initial_train_bars": initial_train_bars,
                    "test_bars": test_bars,
                    "selection_rule": fold["selection_rule"],
                    "fee_rate_per_side": BASE_FEE_PER_SIDE,
                    "slippage_rate_per_side": BASE_SLIPPAGE_PER_SIDE,
                    "allocation_fraction": ALLOCATION_FRACTION,
                },
                dataset_sha256=dataset_sha256,
                data_source=SOURCE,
                code_commit_sha=code_commit_sha,
                run_id=run_id,
                created_utc=generated,
                evaluation_protocol="Expanding-window selection on past data only; selected signal frozen for contiguous next-open OOS block; no parameter retuning.",
            )
        )

    report = {
        "mode": "INDEPENDENT_BITSTAMP_CROSS_EXCHANGE_17_CANDIDATE_RESEARCH",
        "generated_at_utc": generated,
        "run_id": run_id,
        "code_commit_sha": code_commit_sha,
        "source": SOURCE,
        "symbol": SYMBOL,
        "timeframe": "1h",
        "candle_count": len(candles),
        "first_timestamp_utc": datetime.fromtimestamp(candles[0]["timestamp"] / 1000, timezone.utc).isoformat(),
        "last_timestamp_utc": datetime.fromtimestamp(candles[-1]["timestamp"] / 1000, timezone.utc).isoformat(),
        "data_quality": {
            "hourly_gap_policy": "reject_any_gap",
            "imputed_hourly_candles": 0,
            "duplicate_timestamps": 0,
            "dataset_sha256": dataset_sha256,
            "snapshot_file": "btc_bitstamp_hourly_dataset.json.gz",
        },
        "candidate_count": len(base["results"]),
        "candidate_semantics": "The 17 candidates are the exact predeclared boolean long/flat signal-state proxies in strategy_family_lab.py. This is not a canonical textbook entry/exit implementation for every named family; see F14 in the adversarial audit. No rule was changed for this independent venue replication.",
        "signal_semantics": base["signal_semantics"],
        "protocol": {
            "train_fraction": 0.70,
            "out_of_sample_fraction": 0.30,
            "oos_start_index": split_index,
            "oos_candles": len(candles) - split_index,
            "oos_open_to_open_returns": return_count,
            "allocation_fraction": ALLOCATION_FRACTION,
            "allocation_cap_fraction": ALLOCATION_FRACTION,
            "bars_per_year_for_sharpe": BARS_PER_YEAR,
            "signal_timing": "completed close; position changes at next open",
            "return_interval": "next open to following open",
            "cost_assumption_warning": "Fixed fee/slippage rates deliberately match the Coinbase experiment to isolate venue-series differences. They are not Bitstamp's account-specific fee schedule, actual spread, market impact, or measured slippage.",
            "costs_per_side": {
                level: {"fee": values[0], "slippage": values[1]}
                for level, values in cost_levels.items()
            },
            "benchmark": "matched 25% buy-and-hold on identical OOS open-to-open intervals; periodic benchmark PF/Sharpe are reported separately",
        },
        "cost_stress": cost_reports,
        "ranking_by_net_return": ranking,
        "top_five_conditional_moving_block_bootstrap_95pct_ci": bootstrap_ci,
        "market_regime_attribution": _regime_return_attribution(candles, signals, split_index, base),
        "rolling_walk_forward": walk_forward,
        "walk_forward_tail_scope_warning": "The final 15% is excluded from this three-fold walk-forward selector only. It is not an untouched holdout because earlier 70/30 historical OOS reports already included this interval.",
        "walk_forward_candidate_ranking": walk_forward_candidate_ranking,
        "rolling_walk_forward_selection_margins": selection_margins,
        "matched_calendar_overlap": matched_calendar_overlap,
        "cscv_pbo": pbo,
        "cscv_pbo_status": pbo_status,
        "cscv_pbo_scope_warning": "CSCV/PBO covers only these 17 predeclared signal-state proxies on this Bitstamp OOS segment. It is a selection-bias diagnostic, not a future-profit probability, not a global experiment census, and not an untouched final holdout.",
        "trial_manifest": manifests,
        "rolling_walk_forward_trial_manifest": walk_forward_manifests,
        "promotion_status": "NO_CANDIDATE_PROMOTED",
        "research_only": True,
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "execution_enabled": False,
        "limitations": [
            "Signal-state proxy semantics are not canonical entry/exit systems for every family; F14 remains open.",
            "Fixed costs match the Coinbase experiment for controlled price-series comparison and are not Bitstamp account-specific costs.",
            "OHLCV does not model bid/ask spread, depth, market impact, latency, partial fills, or intrabar tick paths.",
            "Cross-exchange historical replication is not forward paper trading and is not an untouched final holdout.",
            "The expanding-window selector uses maximum training excess return without an abstention/stability rule; selection margins are reported but not used to alter the frozen rule.",
            "Bootstrap intervals are conditional on the OOS ranking and are not selection-adjusted.",
        ],
    }
    # Verify that higher fixed costs never improve any candidate's net return.
    for name in base["results"]:
        returns = [
            cost_reports[level]["results"][name]["strategy"]["net_return"]
            for level in ("1x", "2x", "3x")
        ]
        if not (returns[0] + 1e-12 >= returns[1] >= returns[2] - 1e-12):
            raise ValueError(f"Cost stress is not monotonic for {name}: {returns}")
    return report


def render_markdown_report(report):
    lines = [
        "# WHJ independent Bitstamp BTC 17-candidate research",
        "",
        f"- Generated UTC: {report['generated_at_utc']}",
        f"- Code commit: `{report['code_commit_sha']}`",
        f"- Run ID: `{report['run_id']}`",
        f"- Source: {report['source']} ({report['symbol']}, {report['timeframe']})",
        f"- Candles: {report['candle_count']} ({report['first_timestamp_utc']} to {report['last_timestamp_utc']})",
        f"- Dataset SHA-256: `{report['data_quality']['dataset_sha256']}`",
        f"- OOS open-to-open returns: {report['protocol']['oos_open_to_open_returns']}",
        f"- Candidate count: {report['candidate_count']}",
        "- Candidate semantics: predeclared long/flat signal-state proxies; F14 remains open.",
        "- Costs: 0.10% fee + 0.05% slippage per side at 1x; 2x/3x multiply both. These are controlled-comparison assumptions, not Bitstamp fee quotes.",
        f"- CSCV/PBO: {report['cscv_pbo']['pbo_estimate'] if report['cscv_pbo'] else 'not computed'} ({report['cscv_pbo_status']})",
        "- Status: RESEARCH ONLY — NO CANDIDATE PROMOTED",
        "",
        "| Rank | Candidate | 1x net | Matched B&H | Excess | Max DD | Period PF | Sharpe | Trades | 2x | 3x |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["ranking_by_net_return"]:
        pf = row["periodic_profit_factor"]
        pf_text = pf if isinstance(pf, str) else (f"{pf:.3f}" if pf is not None else "—")
        sharpe = row["period_sharpe"]
        sharpe_text = f"{sharpe:.3f}" if sharpe is not None else "—"
        lines.append(
            f"| {row['rank_by_net_return']} | {row['candidate']} | {row['net_return_pct']:.2f}% | "
            f"{row['matched_buy_and_hold_pct']:.2f}% | {row['excess_vs_buy_and_hold_pp']:+.2f} pp | "
            f"{row['max_open_to_open_drawdown_pct']:.2f}% | {pf_text} | {sharpe_text} | "
            f"{row['closed_trades']} | {row['return_2x_pct']:.2f}% | {row['return_3x_pct']:.2f}% |"
        )
    semantics = report["signal_semantics"]
    lines.extend([
        "",
        "## Candidate rules V1 — explicit entry/exit semantics",
        "",
        f"- Version: `{semantics['candidate_rules_version']}`",
        "- These are long/flat signal-state proxies, not canonical textbook systems or order instructions.",
        "",
        "| Candidate | Kind | Entry condition | Exit condition | Known limitations |",
        "|---|---|---|---|---|",
    ])
    for candidate_name, rule in semantics["candidate_rules_v1"].items():
        entry = rule["entry_condition"].replace("|", "/")
        exit_rule = rule["exit_condition"].replace("|", "/")
        limitations = "; ".join(rule["known_limitations"]).replace("|", "/")
        lines.append(
            f"| {candidate_name} | {rule['signal_kind']} | {entry} | {exit_rule} | {limitations} |"
        )
    lines.extend([
        "",
        "Historical V1 metrics remain attached to these exact proxy definitions. Canonical V2 rules require new candidate IDs and a fresh predeclared evaluation.",
        "",
    ])
    matched = report.get("matched_calendar_overlap")
    if matched:
        reference = matched["reference"]
        lines.extend([
            "",
            "## Exact calendar overlap with Coinbase",
            "",
            f"- Reference: Coinbase run {reference['run_id']} ({reference['first_oos_open_timestamp_utc']} through {reference['last_candle_timestamp_utc']}).",
            f"- Reference dataset SHA-256: `{reference['dataset_sha256']}`.",
            f"- Bitstamp matched returns: {matched['bitstamp']['open_to_open_returns']}; matched slice SHA-256: `{matched['bitstamp']['matched_oos_slice_sha256']}`.",
            f"- CSCV/PBO: {matched['cscv_pbo']['pbo_estimate'] if matched['cscv_pbo'] else 'not computed'} ({matched['cscv_pbo_status']}).",
            "",
            "| Rank | Candidate | 1x net | Matched B&H | Excess | Max DD | Period PF | Sharpe | Trades | 2x | 3x |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for row in matched["ranking_by_net_return"]:
            pf = row["periodic_profit_factor"]
            pf_text = pf if isinstance(pf, str) else (f"{pf:.3f}" if pf is not None else "—")
            sharpe = row["period_sharpe"]
            sharpe_text = f"{sharpe:.3f}" if sharpe is not None else "—"
            lines.append(
                f"| {row['rank_by_net_return']} | {row['candidate']} | {row['net_return_pct']:.2f}% | "
                f"{row['matched_buy_and_hold_pct']:.2f}% | {row['excess_vs_buy_and_hold_pp']:+.2f} pp | "
                f"{row['max_open_to_open_drawdown_pct']:.2f}% | {pf_text} | {sharpe_text} | "
                f"{row['closed_trades']} | {row['return_2x_pct']:.2f}% | {row['return_3x_pct']:.2f}% |"
            )
        lines.extend([
            "",
            "This segment exactly matches the referenced Coinbase OOS calendar and return count. It isolates the venue price series more cleanly than the separate full-history 70/30 split; costs are still fixed proxies, not actual Bitstamp fees or spread.",
        ])
    lines.extend(["", "## Expanding-window walk-forward", ""])
    walk_forward = report["rolling_walk_forward"]
    lines.append(
        f"- Protocol: {walk_forward['protocol']}; folds: {walk_forward['fold_count']}; "
        f"initial training bars: {walk_forward['initial_train_bars']}; test bars/fold: {walk_forward['test_bars']}."
    )
    lines.append(
        f"- Unused trailing bars: {walk_forward['unused_tail_bars']} "
        f"({walk_forward['unused_tail_fraction']:.1%}), excluded from this walk-forward selector only."
    )
    lines.append(f"- Holdout scope: {report['walk_forward_tail_scope_warning']}")
    for level, metrics in walk_forward["aggregate_oos_cost_scenarios"].items():
        strategy = metrics["strategy"]
        benchmark = metrics["buy_and_hold"]
        sharpe = strategy["period_sharpe"]
        sharpe_text = f"{sharpe:.3f}" if sharpe is not None else "—"
        lines.append(
            f"- {level}: strategy {strategy['net_return']*100:.2f}%, matched B&H "
            f"{benchmark['net_return']*100:.2f}%, DD {abs(strategy['max_open_to_open_drawdown'])*100:.2f}%, "
            f"Sharpe {sharpe_text}, closed trades {strategy['closed_trades']}."
        )
    lines.extend(["", "## Fold selections", ""])
    for fold in report["rolling_walk_forward_selection_margins"]:
        lines.append(
            f"- Fold {fold['fold']}: {fold['selected_candidate']}; training excess margin "
            f"{fold['selection_margin']*100:.3f} pp over {fold['runner_up_candidate']}."
        )
    ranking = report["walk_forward_candidate_ranking"]
    lines.extend([
        "", "## Fixed-candidate walk-forward ranking (all 17)", "",
        f"- Method: {ranking['method']}; weights: {ranking['weights_pct']}",
        f"- Each fixed candidate is evaluated across the same {report['rolling_walk_forward']['fold_count']} contiguous OOS folds; this is separate from the adaptive selector.",
        "| Rank | Candidate | Score | Screen | 1x | DD | PF | Sharpe | Trades | 2x | 3x | Positive folds | Regimes covered |",
        "|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for item in ranking["ranked_candidates"]:
        m = item["metrics"]
        pf = m["profit_factor"]
        pf_text = pf if isinstance(pf, str) else (f"{pf:.3f}" if pf is not None else "—")
        sharpe = m["period_sharpe"]
        sharpe_text = f"{sharpe:.3f}" if sharpe is not None else "—"
        lines.append(
            f"| {item['rank']} | {item['candidate']} | {item['score']:.2f} | {item['screening_status']} | "
            f"{m['net_return_1x_pct']:.2f}% | {m['max_drawdown_pct']:.2f}% | {pf_text} | {sharpe_text} | "
            f"{m['closed_trades']} | {m['net_return_2x_pct']:.2f}% | {m['net_return_3x_pct']:.2f}% | "
            f"{m['positive_folds']}/{len(m['fold_returns_pct'])} | {m['regime_coverage_count']}/3 |"
        )
    lines.extend([
        "",
        f"- Research screen passed: {ranking['passed_count']}/{ranking['candidate_count']}; no candidate is automatically promoted.",
        "- Regime contributions are conditional log-growth attribution by the regime known at signal close, not standalone regime portfolios.",
    ])
    lines.extend([
        "",
        "## Interpretation",
        "",
        "This is an independent venue-price-series replication of the same 17 signal-state proxies, not a canonical entry/exit retest. The fixed cost schedule is held equal to the Coinbase experiment to isolate price-series differences; it is not a Bitstamp-specific fee/spread estimate. Regime values are bar-level log-return attribution by the regime known at the prior close, not separate regime portfolios. Historical cross-exchange results do not establish forward-paper or live profitability.",
        "",
        "**NO CANDIDATE PROMOTED.**",
    ])
    return "\n".join(lines) + "\n"


def main():
    candles = fetch_bitstamp_hourly_candles(days=3000)
    report = build_bitstamp_strategy_report(
        candles,
        run_id=os.environ["GITHUB_RUN_ID"],
        code_commit_sha=os.environ["GITHUB_SHA"],
    )
    payload = canonical_json_bytes(candles)
    Path("btc_bitstamp_hourly_dataset.json.gz").write_bytes(gzip_snapshot_bytes(payload))
    Path("btc_bitstamp_strategy_universe_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    Path("btc_bitstamp_strategy_universe_report.md").write_text(
        render_markdown_report(report), encoding="utf-8"
    )
    print(json.dumps({
        "run_id": report["run_id"],
        "code_commit_sha": report["code_commit_sha"],
        "candle_count": report["candle_count"],
        "dataset_sha256": report["data_quality"]["dataset_sha256"],
        "candidate_count": report["candidate_count"],
        "oos_returns": report["protocol"]["oos_open_to_open_returns"],
        "pbo_status": report["cscv_pbo_status"],
        "promotion_status": report["promotion_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
