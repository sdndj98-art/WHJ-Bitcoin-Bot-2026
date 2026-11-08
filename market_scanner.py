"""Multi-factor BTC/USD hourly scanner; diagnostics only, never executes orders."""
import math


def _ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough values for EMA")
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _rsi(values, period=14):
    if len(values) <= period:
        raise ValueError("Not enough values for RSI")
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    if average_gain == 0:
        return 0.0
    return 100.0 - (100.0 / (1.0 + average_gain / average_loss))


def _atr(rows, period=14):
    true_ranges = []
    for index, row in enumerate(rows):
        high, low, close = row[2], row[3], row[4]
        previous_close = rows[index - 1][4] if index else close
        true_ranges.append(max(high - low, abs(high - previous_close),
                               abs(low - previous_close)))
    if len(true_ranges) < period:
        raise ValueError("Not enough values for ATR")
    value = sum(true_ranges[:period]) / period
    for current in true_ranges[period:]:
        value = ((value * (period - 1)) + current) / period
    return value


def _adx(rows, period=14):
    """Return Wilder ADX, +DI and -DI from normalized OHLC rows."""
    if len(rows) < (2 * period + 1):
        raise ValueError("Not enough values for ADX")
    true_ranges = []
    plus_moves = []
    minus_moves = []
    for index, row in enumerate(rows):
        high, low = row[2], row[3]
        previous_close = rows[index - 1][4] if index else row[4]
        previous_high = rows[index - 1][2] if index else high
        previous_low = rows[index - 1][3] if index else low
        true_ranges.append(max(
            high - low, abs(high - previous_close), abs(low - previous_close)
        ))
        up_move = high - previous_high
        down_move = previous_low - low
        plus_moves.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_moves.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    smooth_tr = sum(true_ranges[1:period + 1])
    smooth_plus = sum(plus_moves[1:period + 1])
    smooth_minus = sum(minus_moves[1:period + 1])
    dx_values = []
    for index in range(period, len(rows)):
        if index > period:
            smooth_tr = smooth_tr - (smooth_tr / period) + true_ranges[index]
            smooth_plus = smooth_plus - (smooth_plus / period) + plus_moves[index]
            smooth_minus = smooth_minus - (smooth_minus / period) + minus_moves[index]
        if smooth_tr <= 0:
            plus_di = minus_di = dx = 0.0
        else:
            plus_di = 100.0 * smooth_plus / smooth_tr
            minus_di = 100.0 * smooth_minus / smooth_tr
            denominator = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / denominator if denominator else 0.0
        dx_values.append((dx, plus_di, minus_di))

    if len(dx_values) < period:
        raise ValueError("Not enough values for ADX")
    adx_value = sum(item[0] for item in dx_values[:period]) / period
    for dx, _, _ in dx_values[period:]:
        adx_value = ((adx_value * (period - 1)) + dx) / period
    return adx_value, dx_values[-1][1], dx_values[-1][2]


def scan_btc_market(candles, market_data_quality=None, volume_lookback=20,
                    volume_spike_multiple=1.5, interval_hours=1, market_label="BTC/USD"):
    """Score a completed hourly candle against eight independent confirmation checks.

    Uses 50 prior candles for EMA trend context, 20 prior candles for breakout
    and volume context, and 14 periods for RSI/ATR/ADX. A candidate is a research
    label for paper review only, not a trade instruction.
    """
    if not isinstance(market_label, str) or not market_label.strip() or len(market_label) > 64:
        raise ValueError("market_label must be a non-empty string of at most 64 characters")
    if isinstance(interval_hours, bool) or not isinstance(interval_hours, int) or interval_hours not in (1, 4, 6):
        raise ValueError("interval_hours must be one of 1, 4, or 6")
    interval_seconds = interval_hours * 3600
    timeframe = f"{interval_hours}h"
    if isinstance(volume_lookback, bool) or not isinstance(volume_lookback, int) or volume_lookback < 2:
        raise ValueError("volume_lookback must be an integer of at least 2")
    if (isinstance(volume_spike_multiple, bool)
            or not isinstance(volume_spike_multiple, (int, float))
            or not math.isfinite(volume_spike_multiple)
            or volume_spike_multiple <= 0):
        raise ValueError("volume_spike_multiple must be finite and positive")
    required_history = max(volume_lookback, 50, 14) + 1
    if not isinstance(candles, list) or len(candles) < required_history:
        raise ValueError("Not enough completed candles for 50-period trend and scanner lookbacks")

    normalized = []
    for row in candles[-required_history:]:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            raise ValueError("Each scanner candle must contain OHLCV and trade count")
        raw_fields = (row[0], row[1], row[2], row[3], row[4], row[6], row[7])
        if any(isinstance(value, bool) for value in raw_fields):
            raise ValueError("Scanner candle fields cannot be booleans")
        try:
            timestamp, open_price, high, low, close, volume, trades = (
                float(value) for value in raw_fields
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Scanner candle fields must be numeric") from exc
        values = (timestamp, open_price, high, low, close, volume, trades)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Scanner candle fields must be finite")
        if not timestamp.is_integer() or timestamp < 0:
            raise ValueError("Scanner candle timestamp must be a non-negative integer")
        if not trades.is_integer():
            raise ValueError("Scanner trade count must be an integer")
        if min(open_price, high, low, close) <= 0 or volume < 0 or trades < 0:
            raise ValueError("Scanner candle contains invalid price or activity values")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Scanner candle has inconsistent OHLC bounds")
        normalized.append((int(timestamp), open_price, high, low, close, volume))

    timestamps = [item[0] for item in normalized]
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("Scanner candle timestamps must be strictly increasing")
    if any(current - previous != interval_seconds for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError(f"Scanner requires contiguous completed {timeframe} candles")
    if any(timestamp % interval_seconds != 0 for timestamp in timestamps):
        if interval_hours == 1:
            raise ValueError("Scanner hourly candle timestamps must align to UTC hour boundaries")
        raise ValueError(f"Scanner {timeframe} candle timestamps must align to UTC boundaries")

    closes = [item[4] for item in normalized]
    previous = normalized[:-1]
    current = normalized[-1]
    current_open, current_high, current_low, current_close, current_volume = current[1:]
    average_volume = sum(item[5] for item in previous[-volume_lookback:]) / volume_lookback
    volume_ratio = current_volume / average_volume if average_volume > 0 else 0.0
    volume_spike = average_volume > 0 and volume_ratio >= volume_spike_multiple
    prior_high = max(item[2] for item in previous[-volume_lookback:])
    breakout = current_close > prior_high

    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    trend_aligned = current_close > ema20 > ema50
    rsi14 = _rsi(closes, 14)
    rsi_healthy = 50.0 <= rsi14 <= 72.0
    atr14 = _atr(normalized, 14)
    adx14, plus_di14, minus_di14 = _adx(normalized, 14)
    adx_trend_strength = adx14 >= 20.0 and plus_di14 > minus_di14
    atr_pct = (atr14 / current_close) * 100.0
    # Hypothetical long-side risk map for research display only. These levels
    # are not orders, personalized advice, or evidence that a setup is profitable.
    hypothetical_stop_atr = 1.5
    hypothetical_target_atr = 3.0
    hypothetical_stop = current_close - (atr14 * hypothetical_stop_atr)
    hypothetical_target = current_close + (atr14 * hypothetical_target_atr)
    hypothetical_risk_pct = (atr14 * hypothetical_stop_atr / current_close) * 100.0
    hypothetical_reward_pct = (atr14 * hypothetical_target_atr / current_close) * 100.0
    hypothetical_reward_risk = (
        hypothetical_target_atr / hypothetical_stop_atr
        if hypothetical_stop_atr > 0 else 0.0
    )
    candle_range = current_high - current_low
    close_position = ((current_close - current_low) / candle_range
                      if candle_range > 0 else 0.5)
    upper_wick = max(0.0, current_high - max(current_open, current_close))
    upper_wick_pct = (upper_wick / candle_range * 100.0
                      if candle_range > 0 else 0.0)
    breakout_clearance_atr = (
        (current_close - prior_high) / atr14 if atr14 > 0 else 0.0
    )
    breakout_buffer_atr_required = 0.10
    max_breakout_upper_wick_pct = 35.0
    breakout_quality = (
        breakout
        and breakout_clearance_atr >= breakout_buffer_atr_required
        and upper_wick_pct <= max_breakout_upper_wick_pct
    )
    bullish_candle = current_close > current_open and close_position >= 0.65

    quality_ok = (
        isinstance(market_data_quality, dict)
        and market_data_quality.get("quality_status") == "HEALTHY"
        and market_data_quality.get("paper_execution_allowed") is True
    )
    checks = {
        "ohlcv_valid": True,
        "market_data_quality_pass": quality_ok,
        "volume_spike": volume_spike,
        "close_above_prior_high": breakout,
        "breakout_quality_confirmed": breakout_quality,
        "trend_alignment": trend_aligned,
        "rsi_momentum_healthy": rsi_healthy,
        "adx_trend_strength": adx_trend_strength,
        "bullish_close_confirmation": bullish_candle,
        "paper_only": True,
        "live_execution_enabled": False,
    }
    scored_checks = (
        quality_ok, volume_spike, breakout, breakout_quality,
        trend_aligned, rsi_healthy, adx_trend_strength, bullish_candle,
    )
    score = sum(scored_checks)
    candidate = score == len(scored_checks)
    status = "PAPER_CANDIDATE" if candidate else (
        "WATCH" if score >= 3 else "NO_SETUP"
    )

    reasons = []
    reason_checks = (
        (not quality_ok, "market_data_quality_blocked_or_unknown"),
        (not volume_spike, "volume_spike_not_confirmed"),
        (not breakout, "close_not_above_prior_lookback_high"),
        (breakout and breakout_clearance_atr < breakout_buffer_atr_required,
         "breakout_close_too_near_prior_high"),
        (breakout and upper_wick_pct > max_breakout_upper_wick_pct,
         "breakout_upper_wick_rejection_risk"),
        (not trend_aligned, "ema20_ema50_trend_not_aligned"),
        (not rsi_healthy, "rsi_outside_momentum_band"),
        (not adx_trend_strength, "adx_trend_strength_or_direction_missing"),
        (not bullish_candle, "bullish_candle_confirmation_missing"),
    )
    reasons.extend(code for failed, code in reason_checks if failed)
    if candidate:
        reasons.append("all_seven_scanner_checks_passed_paper_review_only")

    return {
        "market": market_label.strip(),
        "timeframe": timeframe,
        "status": status,
        "lookback_candles": volume_lookback,
        "trend_lookback_candles": 50,
        "volume_spike_multiple_required": volume_spike_multiple,
        "breakout_buffer_atr_required": breakout_buffer_atr_required,
        "max_breakout_upper_wick_pct": max_breakout_upper_wick_pct,
        "breakout_clearance_atr": round(breakout_clearance_atr, 4),
        "breakout_upper_wick_pct": round(upper_wick_pct, 2),
        "current_volume": round(current_volume, 8),
        "prior_average_volume": round(average_volume, 8),
        "volume_ratio": round(volume_ratio, 4),
        "prior_lookback_high": round(prior_high, 2),
        "current_close": round(current_close, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "rsi14": round(rsi14, 2),
        "adx14": round(adx14, 2),
        "plus_di14": round(plus_di14, 2),
        "minus_di14": round(minus_di14, 2),
        "adx_minimum_required": 20.0,
        "adx_trend_strength_confirmed": adx_trend_strength,
        "atr14": round(atr14, 2),
        "atr_pct": round(atr_pct, 4),
        "hypothetical_risk_map": {
            "research_only": True,
            "reference_price": round(current_close, 2),
            "atr_multiple_stop": hypothetical_stop_atr,
            "atr_multiple_target": hypothetical_target_atr,
            "stop_level": round(hypothetical_stop, 2),
            "target_level": round(hypothetical_target, 2),
            "risk_pct": round(hypothetical_risk_pct, 4),
            "reward_pct": round(hypothetical_reward_pct, 4),
            "reward_risk_ratio": round(hypothetical_reward_risk, 2),
            "execution_enabled": False,
        },
        "close_position_pct": round(close_position * 100.0, 2),
        "confluence_score": score,
        "confluence_total": len(scored_checks),
        "confluence_pct": round((score / len(scored_checks)) * 100.0, 2),
        "checks": checks,
        "reasons": reasons,
        "paper_candidate_only": True,
        "live_orders_placed": False,
        "limitations": [
            "BTC/USD only; no new-token discovery or on-chain rug-pull assessment.",
            "A scanner candidate is not a validated profitable strategy or an order instruction.",
            "ATR risk-map levels are hypothetical research references, not orders or validated trade parameters.",
            "No stop-loss, take-profit, or live execution is performed by this scanner.",
            "RSI, EMA, ATR and ADX are descriptive indicators, not predictive guarantees.",
            "ADX >= 20 and +DI > -DI is an experimental breakout-quality filter, not yet independently qualified.",
        ],
    }

def _aggregate_hourly_candles(candles, hours):
    """Build only complete UTC-aligned bars from closed hourly OHLCV candles."""
    if hours not in (4, 6):
        raise ValueError("Aggregation hours must be 4 or 6")
    if not isinstance(candles, list):
        raise ValueError("Hourly candles must be a list")
    interval_seconds = 3600
    span_seconds = hours * interval_seconds
    groups = {}
    previous_timestamp = None
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            raise ValueError("Each hourly candle must contain OHLCV and trade count")
        if isinstance(row[0], bool):
            raise ValueError("Hourly timestamps cannot be booleans")
        try:
            timestamp = int(row[0])
            if float(row[0]) != timestamp:
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid hourly candle timestamp") from exc
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError("Hourly timestamps must be strictly increasing")
        if timestamp % interval_seconds:
            raise ValueError("Hourly timestamps must align to UTC hour boundaries")
        previous_timestamp = timestamp
        bucket = timestamp // span_seconds
        groups.setdefault(bucket, []).append(row)

    aggregated = []
    for bucket in sorted(groups):
        group = sorted(groups[bucket], key=lambda item: int(item[0]))
        start = bucket * span_seconds
        if len(group) != hours:
            continue
        if any(int(group[i][0]) != start + i * interval_seconds for i in range(hours)):
            continue
        try:
            opens = [float(item[1]) for item in group]
            highs = [float(item[2]) for item in group]
            lows = [float(item[3]) for item in group]
            closes = [float(item[4]) for item in group]
            volumes = [float(item[6]) for item in group]
            trades = [int(item[7]) for item in group]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Hourly OHLCV values must be numeric") from exc
        values = opens + highs + lows + closes + volumes
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Hourly OHLCV values must be finite")
        if any(isinstance(item[7], bool) or float(item[7]) != int(item[7]) for item in group):
            raise ValueError("Hourly trade counts must be whole numbers")
        aggregated.append([
            start, opens[0], max(highs), min(lows), closes[-1],
            0.0, sum(volumes), sum(trades),
        ])
    return aggregated


def scan_btc_multi_timeframe(candles, market_data_quality=None):
    """Compare 1h, 4h and 6h scanner states using completed UTC bars only."""
    results = {"1h": scan_btc_market(candles, market_data_quality)}
    for hours in (4, 6):
        bars = _aggregate_hourly_candles(candles, hours)
        try:
            results[f"{hours}h"] = scan_btc_market(
                bars, market_data_quality, interval_hours=hours
            )
        except ValueError as exc:
            if "Not enough completed candles" not in str(exc):
                raise
            results[f"{hours}h"] = {
                "market": "BTC/USD",
                "timeframe": f"{hours}h",
                "status": "INSUFFICIENT_HISTORY",
                "confluence_score": 0,
                "confluence_total": 8,
                "paper_candidate_only": True,
                "live_orders_placed": False,
                "reason": str(exc),
            }
    candidate_count = sum(
        item.get("status") == "PAPER_CANDIDATE" for item in results.values()
    )
    evaluated = [
        item for item in results.values()
        if item.get("status") != "INSUFFICIENT_HISTORY"
        and isinstance(item.get("confluence_score"), int)
        and not isinstance(item.get("confluence_score"), bool)
        and isinstance(item.get("confluence_total"), int)
        and not isinstance(item.get("confluence_total"), bool)
        and item["confluence_total"] > 0
        and isinstance(item.get("checks"), dict)
    ]
    average_confluence_pct = (
        sum(item["confluence_score"] / item["confluence_total"] * 100.0
            for item in evaluated) / len(evaluated)
        if evaluated else 0.0
    )
    strongest_timeframe = max(
        evaluated,
        key=lambda item: (
            item["confluence_score"] / item["confluence_total"],
            item["timeframe"],
        ),
    )["timeframe"] if evaluated else None
    trend_aligned_count = sum(
        item.get("checks", {}).get("trend_alignment") is True
        for item in evaluated
    )
    breakout_quality_count = sum(
        item.get("checks", {}).get("breakout_quality_confirmed") is True
        for item in evaluated
    )
    return {
        "mode": "COMPLETED_CANDLE_MULTI_TIMEFRAME_DIAGNOSTICS",
        "timeframes": results,
        "consensus": {
            "status": "MULTI_TIMEFRAME_PAPER_CANDIDATE"
            if candidate_count == 3 else "NO_FULL_TIMEFRAME_CONSENSUS",
            "candidate_timeframes": candidate_count,
            "required_timeframes": 3,
            "evaluated_timeframes": len(evaluated),
            "average_confluence_pct": round(average_confluence_pct, 2),
            "strongest_timeframe": strongest_timeframe,
            "trend_aligned_timeframes": trend_aligned_count,
            "breakout_quality_timeframes": breakout_quality_count,
            "paper_review_only": True,
            "live_execution_enabled": False,
        },
        "limitations": [
            "Only fully closed UTC-aligned 1h, 4h and 6h candles are evaluated.",
            "The 4h and 6h bars are aggregated from the supplied hourly history.",
            "A multi-timeframe match is a research filter, not a validated profitable signal.",
            "No orders or account changes are performed.",
        ],
    }
