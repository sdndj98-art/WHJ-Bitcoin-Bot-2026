"""Conservative, close-only strategy comparison with a chronological holdout.

Signals use only completed candles. Orders are simulated at the following close.
This module is research-only and never connects to an exchange.
"""
import math


def _ema(values, period):
    alpha = 2.0 / (period + 1)
    out = []
    current = float(values[0])
    for value in values:
        current = alpha * float(value) + (1 - alpha) * current
        out.append(current)
    return out


def _rsi(values, period=14):
    result = [None] * len(values)
    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    if avg_loss == 0:
        result[period] = 100.0 if avg_gain else 50.0
    else:
        result[period] = 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def _signals(prices):
    ema_fast = _ema(prices, 12)
    ema_slow = _ema(prices, 26)
    ema50 = _ema(prices, 50)
    ema200 = _ema(prices, 200)
    rsi = _rsi(prices, 14)
    rsi2 = _rsi(prices, 2)
    sma20 = [None] * len(prices)
    sma50 = [None] * len(prices)
    sma200 = [None] * len(prices)
    for i in range(19, len(prices)):
        sma20[i] = sum(prices[i - 19:i + 1]) / 20
    for i in range(49, len(prices)):
        sma50[i] = sum(prices[i - 49:i + 1]) / 50
    for i in range(199, len(prices)):
        sma200[i] = sum(prices[i - 199:i + 1]) / 200

    result = {
        "sma_trend": [],
        "ema_trend": [],
        "rsi_momentum": [],
        "sma200_regime": [],
        "ema50_200_regime": [],
        "sma200_filter": [],
        "ema200_filter": [],
        "sma50_200_cross": [],
        "donchian_55_20": [],
        "rsi2_mean_reversion": [],
        "rsi14_mean_reversion": [],
        "bollinger_mean_reversion": [],
        "ema_pullback_trend": [],
        "donchian_20_10_breakout": [],
        "macd_trend_confirmation": [],
        "rsi_trend_pullback": [],
    }
    donchian_position = False
    rsi2_position = False
    rsi2_holding = 0
    rsi14_position = False
    rsi14_holding = 0
    bollinger_position = False
    bollinger_holding = 0
    ema_pullback_position = False
    donchian_20_10_position = False
    macd_trend_position = False
    rsi_pullback_position = False
    for i, price in enumerate(prices):
        result["sma_trend"].append(
            bool(sma20[i] is not None and sma50[i] is not None
                 and price > sma20[i] > sma50[i])
        )
        result["ema_trend"].append(bool(ema_fast[i] > ema_slow[i] and price > ema_slow[i]))
        result["rsi_momentum"].append(
            bool(rsi[i] is not None and 50 < rsi[i] < 70 and price > ema_slow[i])
        )
        result["sma200_regime"].append(
            bool(sma20[i] is not None and sma50[i] is not None
                 and sma200[i] is not None and price > sma20[i] > sma50[i] > 0
                 and price > sma200[i])
        )
        result["ema50_200_regime"].append(
            bool(i >= 199 and ema50[i] > ema200[i] and price > ema200[i])
        )
        result["sma200_filter"].append(bool(sma200[i] is not None and price > sma200[i]))
        result["ema200_filter"].append(bool(i >= 199 and price > ema200[i]))
        result["sma50_200_cross"].append(
            bool(sma50[i] is not None and sma200[i] is not None and sma50[i] > sma200[i])
        )
        if i >= 55 and not donchian_position and price > max(prices[i - 55:i]):
            donchian_position = True
        elif i >= 20 and donchian_position and price < min(prices[i - 20:i]):
            donchian_position = False
        result["donchian_55_20"].append(donchian_position)

        if i >= 199 and sma200[i] is not None:
            if not rsi2_position and rsi2[i] is not None and rsi2[i] < 10 and price > sma200[i]:
                rsi2_position = True
                rsi2_holding = 0
            elif rsi2_position:
                rsi2_holding += 1
                if (rsi2[i] is not None and rsi2[i] > 70) or price < sma200[i] or rsi2_holding >= 5:
                    rsi2_position = False
                    rsi2_holding = 0
            if not rsi14_position and rsi[i] is not None and rsi[i] < 30 and price > sma200[i]:
                rsi14_position = True
                rsi14_holding = 0
            elif rsi14_position:
                rsi14_holding += 1
                if (rsi[i] is not None and rsi[i] > 55) or price < sma200[i] or rsi14_holding >= 10:
                    rsi14_position = False
                    rsi14_holding = 0
            if sma20[i] is not None:
                window = prices[i - 19:i + 1]
                variance = sum((value - sma20[i]) ** 2 for value in window) / 20
                lower_band = sma20[i] - 2 * math.sqrt(variance)
                if not bollinger_position and price < lower_band and price > sma200[i]:
                    bollinger_position = True
                    bollinger_holding = 0
                elif bollinger_position:
                    bollinger_holding += 1
                    if price >= sma20[i] or price < sma200[i] or bollinger_holding >= 10:
                        bollinger_position = False
                        bollinger_holding = 0
        result["rsi2_mean_reversion"].append(rsi2_position)
        result["rsi14_mean_reversion"].append(rsi14_position)
        result["bollinger_mean_reversion"].append(bollinger_position)
        # Fixed-rule long-only candidates; signals use completed closes only.
        ema20_now = _ema(prices[:i + 1], 20)[-1]
        if i >= 199:
            if not ema_pullback_position and price > ema200[i] and ema20_now > ema50[i] and price > ema20_now:
                ema_pullback_position = True
            elif ema_pullback_position and (price < ema50[i] or price < ema200[i]):
                ema_pullback_position = False
            if not donchian_20_10_position and i >= 20 and price > max(prices[i - 20:i]):
                donchian_20_10_position = True
            elif donchian_20_10_position and i >= 10 and price < min(prices[i - 10:i]):
                donchian_20_10_position = False
            macd_now = ema_fast[i] - ema_slow[i]
            macd_prior = ema_fast[i - 1] - ema_slow[i - 1]
            if not macd_trend_position and macd_now > macd_prior and ema_fast[i] > ema_slow[i] and price > ema50[i]:
                macd_trend_position = True
            elif macd_trend_position and (ema_fast[i] < ema_slow[i] or price < ema50[i]):
                macd_trend_position = False
            previous_rsi = rsi[i - 1]
            if (not rsi_pullback_position and rsi[i] is not None and previous_rsi is not None
                    and previous_rsi <= 40 < rsi[i] and price > sma200[i] and ema50[i] > ema200[i]):
                rsi_pullback_position = True
            elif rsi_pullback_position and ((rsi[i] is not None and rsi[i] >= 68) or price < sma50[i]):
                rsi_pullback_position = False
        result["ema_pullback_trend"].append(ema_pullback_position)
        result["donchian_20_10_breakout"].append(donchian_20_10_position)
        result["macd_trend_confirmation"].append(macd_trend_position)
        result["rsi_trend_pullback"].append(rsi_pullback_position)
    return result


def _simulate(prices, signals, start, end, fee=0.001, slippage=0.0005):
    cash = 1000.0
    units = 0.0
    entry_value = 0.0
    trades = []
    peak = cash
    max_dd = 0.0
    for i in range(max(start, 1), end):
        # signal[i-1] only; fill at current close, with 25% of available equity.
        want_long = signals[i - 1]
        if want_long and units == 0:
            allocation = cash * 0.25
            fill = prices[i] * (1 + slippage)
            fee_paid = allocation * fee
            units = (allocation - fee_paid) / fill
            cash -= allocation
            entry_value = allocation
        elif not want_long and units > 0:
            fill = prices[i] * (1 - slippage)
            proceeds = units * fill
            proceeds -= proceeds * fee
            pnl = proceeds - entry_value
            cash += proceeds
            trades.append(pnl)
            units = 0.0
            entry_value = 0.0
        # Measure drawdown on net liquidation value, not a frictionless mark.
        # This includes the estimated exit slippage and fee while a position is open.
        if units > 0:
            liquidation = units * prices[i] * (1 - slippage)
            liquidation -= liquidation * fee
            equity = cash + liquidation
        else:
            equity = cash
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0.0)
    # Report net liquidation value, including estimated exit fee and slippage
    # for any position still open at the end of this evaluation window.
    if units > 0:
        estimated_exit = units * prices[end - 1] * (1 - slippage)
        estimated_exit -= estimated_exit * fee
        final_equity = cash + estimated_exit
    else:
        final_equity = cash
    wins = sum(1 for x in trades if x > 0)
    gp = sum(x for x in trades if x > 0)
    gl = -sum(x for x in trades if x < 0)
    return {
        "return_pct": round((final_equity / 1000 - 1) * 100, 2),
        "final_equity_usd": round(final_equity, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "closed_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(gp / gl, 2) if gl else (None if gp else 0.0),
        "open_position": units > 0,
    }




def _consensus_signals(signals):
    """Build an equal-weight, three-family long-only consensus from completed-bar rules."""
    trend_names = (
        "sma_trend", "ema_trend", "sma200_regime", "ema50_200_regime",
        "sma200_filter", "ema200_filter", "sma50_200_cross", "donchian_55_20",
    )
    reversion_names = (
        "rsi2_mean_reversion", "rsi14_mean_reversion",
        "bollinger_mean_reversion",
    )
    required = set(trend_names + ("rsi_momentum",) + reversion_names)
    missing = sorted(required.difference(signals))
    if missing:
        raise ValueError("Missing consensus signal families: " + ", ".join(missing))
    lengths = {len(signals[name]) for name in required}
    if len(lengths) != 1:
        raise ValueError("Consensus input signal series must have equal lengths")
    count = lengths.pop()
    consensus = []
    for index in range(count):
        trend_votes = sum(bool(signals[name][index]) for name in trend_names)
        momentum_vote = bool(signals["rsi_momentum"][index])
        reversion_votes = sum(bool(signals[name][index]) for name in reversion_names)
        family_votes = int(trend_votes >= 4) + int(momentum_vote) + int(reversion_votes >= 2)
        consensus.append(family_votes >= 2)
    return consensus



def _wilson_interval(successes, total, z=1.96):
    """Return a two-sided Wilson score interval for a binomial proportion."""
    if (isinstance(successes, bool) or isinstance(total, bool)
            or not isinstance(successes, int) or not isinstance(total, int)
            or total < 0 or successes < 0 or successes > total):
        raise ValueError("Wilson interval counts must be integers with 0 <= successes <= total")
    if total == 0:
        return None
    proportion = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    margin = (z * math.sqrt(
        proportion * (1.0 - proportion) / total + z2 / (4.0 * total * total)
    ) / denominator)
    return {
        "lower_pct": round(max(0.0, center - margin) * 100.0, 2),
        "upper_pct": round(min(1.0, center + margin) * 100.0, 2),
        "method": "wilson_95",
    }


def _market_regime_diagnostics(prices, signals, start_index):
    """Describe OOS market regimes using only information available at each close.

    The forward market return is an outcome measured after classification; it is
    never used to decide the regime. Strategy exposure is descriptive, not PnL.
    """
    count = len(prices)
    if any(len(values) != count for values in signals.values()):
        raise ValueError("Every strategy signal series must match the price series length")

    sma200 = [None] * count
    if count >= 200:
        rolling = sum(float(value) for value in prices[:200])
        sma200[199] = rolling / 200
        for index in range(200, count):
            rolling += float(prices[index]) - float(prices[index - 200])
            sma200[index] = rolling / 200

    names = ("bullish", "bearish", "sideways_or_transition")
    buckets = {
        name: {
            "bars": 0,
            "growth_factor": 1.0,
            "positive_forward_bars": 0,
            "absolute_return_sum_pct": 0.0,
            "strategy_active_bars": {strategy: 0 for strategy in signals},
            "strategy_signal_growth": {strategy: 1.0 for strategy in signals},
            "strategy_signal_positive_bars": {strategy: 0 for strategy in signals},
            "strategy_signal_returns": {strategy: [] for strategy in signals},
        }
        for name in names
    }
    first_index = max(int(start_index), 219)
    for index in range(first_index, count - 1):
        average = sma200[index]
        prior_average = sma200[index - 20]
        if average is None or prior_average is None:
            continue
        if prices[index] > average and average > prior_average:
            regime = "bullish"
        elif prices[index] < average and average < prior_average:
            regime = "bearish"
        else:
            regime = "sideways_or_transition"

        forward_return = (float(prices[index + 1]) / float(prices[index]) - 1.0) * 100.0
        bucket = buckets[regime]
        bucket["bars"] += 1
        bucket["growth_factor"] *= 1.0 + forward_return / 100.0
        bucket["positive_forward_bars"] += int(forward_return > 0)
        bucket["absolute_return_sum_pct"] += abs(forward_return)
        for strategy, values in signals.items():
            if bool(values[index]):
                bucket["strategy_active_bars"][strategy] += 1
                bucket["strategy_signal_growth"][strategy] *= 1.0 + forward_return / 100.0
                bucket["strategy_signal_positive_bars"][strategy] += int(forward_return > 0)
                bucket["strategy_signal_returns"][strategy].append(forward_return)

    result = {}
    for regime, bucket in buckets.items():
        bars = bucket["bars"]
        strategy_diagnostics = {}
        for strategy in signals:
            active = bucket["strategy_active_bars"][strategy]
            strategy_diagnostics[strategy] = {
                "active_signal_bars": active,
                "active_forward_return_pct": (
                    round((bucket["strategy_signal_growth"][strategy] - 1.0) * 100.0, 2)
                    if active else None
                ),
                "positive_active_forward_bar_pct": (
                    round(bucket["strategy_signal_positive_bars"][strategy] / active * 100.0, 2)
                    if active else None
                ),
                "positive_active_forward_bar_ci95_pct": _wilson_interval(
                    bucket["strategy_signal_positive_bars"][strategy], active
                ),
                "mean_active_forward_bar_return_pct": (
                    round(sum(bucket["strategy_signal_returns"][strategy]) / active, 4)
                    if active else None
                ),
                "evidence_status": "INSUFFICIENT_SAMPLE" if active < 30 else "DESCRIPTIVE_ONLY",
            }
        result[regime] = {
            "bars": bars,
            "evidence_status": "INSUFFICIENT_SAMPLE" if bars < 30 else "DESCRIPTIVE_ONLY",
            "strategy_signal_diagnostics": strategy_diagnostics,
            "market_forward_return_pct": (
                round((bucket["growth_factor"] - 1.0) * 100.0, 2) if bars else None
            ),
            "positive_forward_bar_pct": (
                round(bucket["positive_forward_bars"] / bars * 100.0, 2) if bars else None
            ),
            "positive_forward_bar_ci95_pct": _wilson_interval(
                bucket["positive_forward_bars"], bars
            ),
            "mean_absolute_forward_bar_return_pct": (
                round(bucket["absolute_return_sum_pct"] / bars, 4) if bars else None
            ),
            "strategy_exposure_pct": {
                strategy: round(active / bars * 100.0, 2) if bars else None
                for strategy, active in bucket["strategy_active_bars"].items()
            },
        }
    return {
        "classification": (
            "Bullish: close above 200-SMA and 200-SMA above its value 20 bars earlier; "
            "bearish: close below 200-SMA and 200-SMA below its value 20 bars earlier; "
            "otherwise sideways/transition."
        ),
        "measurement": (
            "OOS next-bar market returns are grouped by the regime known at the prior close. "
            "Per-strategy active-signal forward returns are descriptive conditional bar returns, "
            "not strategy PnL, not trade-level PnL, net returns, or a deployable strategy backtest. "
            "INSUFFICIENT_SAMPLE is used below 30 active signal bars."
        ),
        "out_of_sample_start_index": first_index,
        "regimes": result,
    }

def run_strategy_lab(prices, fee=0.001, slippage=0.0005):
    if len(prices) < 120:
        raise ValueError("At least 120 prices are required for strategy holdout testing")
    if any(isinstance(p, bool) or not isinstance(p, (int, float))
           or not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError("Prices must be finite positive numbers")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    split = int(len(prices) * 0.7)
    signals = _signals(prices)
    signals["regime_aware_consensus"] = _consensus_signals(signals)
    results = {}
    # Three chronological evaluation windows after the initial warm-up.
    # These are fixed-rule rolling windows, not parameter re-optimization.
    # Split the 30% holdout into three sequential, non-overlapping test windows.
    walk_start = split
    window_edges = [
        walk_start + ((len(prices) - walk_start) * k) // 3
        for k in range(4)
    ]
    for name, values in signals.items():
        windows = []
        for fold in range(3):
            start = window_edges[fold]
            end = window_edges[fold + 1]
            if end > start:
                windows.append({
                    "window": fold + 1,
                    "start_index": start,
                    "end_index_exclusive": end,
                    "metrics": _simulate(prices, values, start, end, fee, slippage),
                })
        returns = [item["metrics"]["return_pct"] for item in windows]
        results[name] = {
            "in_sample": _simulate(prices, values, 50, split, fee, slippage),
            "out_of_sample": _simulate(prices, values, split, len(prices), fee, slippage),
            "walk_forward_windows": windows,
            "worst_window_return_pct": min(returns) if returns else None,
        }

    # Buy-and-hold benchmark over exactly the same out-of-sample window.
    # Mark-to-market drawdown uses spot value; final return includes exit costs.
    # Match the 25% strategy allocation for a fair risk/exposure comparison.
    benchmark_allocation = 250.0
    benchmark_cash = 1000.0 - benchmark_allocation
    start_price = float(prices[split]) * (1 + slippage)
    entry_fee = benchmark_allocation * fee
    benchmark_units = (benchmark_allocation - entry_fee) / start_price
    benchmark_peak = 1000.0
    benchmark_max_dd = 0.0
    for price in prices[split:]:
        # Compare drawdown on the same net-liquidation basis as strategies:
        # estimate exit slippage and fee at every observation, not only at the end.
        liquidation = benchmark_units * float(price) * (1 - slippage)
        liquidation -= liquidation * fee
        marked_equity = benchmark_cash + liquidation
        benchmark_peak = max(benchmark_peak, marked_equity)
        if benchmark_peak > 0:
            benchmark_max_dd = max(
                benchmark_max_dd,
                (benchmark_peak - marked_equity) / benchmark_peak * 100,
            )
    benchmark_exit = benchmark_units * float(prices[-1]) * (1 - slippage)
    benchmark_exit -= benchmark_exit * fee
    benchmark_equity = benchmark_cash + benchmark_exit
    benchmark_pnl = benchmark_equity - 1000.0
    results["buy_and_hold"] = {
        "out_of_sample": {
            "return_pct": round((benchmark_equity / 1000.0 - 1) * 100, 2),
            "final_equity_usd": round(benchmark_equity, 2),
            "max_drawdown_pct": round(benchmark_max_dd, 2),
            "closed_trades": 1,
            "win_rate_pct": 100.0 if benchmark_pnl > 0 else 0.0,
            "profit_factor": None,
            "open_position": False,
            "fees_and_slippage_included": True,
            "allocation_fraction": benchmark_allocation / 1000.0,
        }
    }
    regime_diagnostics = _market_regime_diagnostics(prices, signals, split)
    return {
        "mode": "FIXED_RULE_CHRONOLOGICAL_HOLDOUT",
        "market_regime_diagnostics": regime_diagnostics,
        "sample_count": len(prices),
        "split_index": split,
        "in_sample_fraction_pct": 70,
        "out_of_sample_fraction_pct": 30,
        "execution": "Previous completed close signal; next close fill; 25% equity allocation; fee and slippage applied.",
        "benchmark_note": "Buy-and-hold benchmark uses the same 25% initial allocation as strategy entries; remaining cash stays uninvested for an exposure-matched comparison.",
        "walk_forward_note": "The 30% out-of-sample holdout is split into three sequential non-overlapping windows; parameters are fixed and not retuned.",
        "ensemble_methodology": {
            "name": "regime_aware_consensus",
            "families": {
                "trend": {"indicators": 8, "family_vote_threshold": "at least 4 of 8"},
                "momentum": {"indicators": 1, "family_vote_threshold": "RSI momentum confirmation active"},
                "mean_reversion": {"indicators": 3, "family_vote_threshold": "at least 2 of 3"},
            },
            "entry_rule": "At least two of the three equally weighted strategy families must agree.",
            "execution": "Same prior completed close signal, next close fill, 25% allocation, fees, slippage, chronological holdout, and walk-forward windows as component strategies.",
            "safety": "Research candidate only; it must independently pass the same out-of-sample and elevated-cost qualification gates.",
        },
        "candidate_strategy_rules": {
            "ema_pullback_trend": "Long above EMA200 with EMA20 > EMA50 and close > EMA20; exit below EMA50 or EMA200.",
            "donchian_20_10_breakout": "Enter above the prior 20 closes; exit below the prior 10 closes.",
            "macd_trend_confirmation": "Enter on rising MACD spread with EMA12 > EMA26 and close > EMA50; exit on bearish cross or below EMA50.",
            "rsi_trend_pullback": "Enter on RSI crossing above 40 in an EMA50/EMA200 uptrend; exit at RSI 68 or below SMA50.",
            "safety": "Long-only research candidates; next-close fills; same holdout and transaction-cost assumptions."
        },
        "selection_warning": "No strategy is declared a winner from these tests alone. Require positive out-of-sample evidence across multiple market regimes and longer periods before considering deployment.",
        "strategies": results,
    }
