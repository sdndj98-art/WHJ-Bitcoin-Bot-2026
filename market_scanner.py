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


def scan_btc_market(candles, market_data_quality=None, volume_lookback=20,
                    volume_spike_multiple=1.5):
    """Score a completed hourly candle against six independent confirmation checks.

    Uses 50 prior candles for EMA trend context, 20 prior candles for breakout
    and volume context, and 14 periods for RSI/ATR. A candidate is a research
    label for paper review only, not a trade instruction.
    """
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
    if any(current - previous != 3600 for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("Scanner requires contiguous completed hourly candles")
    if any(timestamp % 3600 != 0 for timestamp in timestamps):
        raise ValueError("Scanner hourly candle timestamps must align to UTC hour boundaries")

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
    atr_pct = (atr14 / current_close) * 100.0
    candle_range = current_high - current_low
    close_position = ((current_close - current_low) / candle_range
                      if candle_range > 0 else 0.5)
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
        "trend_alignment": trend_aligned,
        "rsi_momentum_healthy": rsi_healthy,
        "bullish_close_confirmation": bullish_candle,
        "paper_only": True,
        "live_execution_enabled": False,
    }
    scored_checks = (
        quality_ok, volume_spike, breakout, trend_aligned,
        rsi_healthy, bullish_candle,
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
        (not trend_aligned, "ema20_ema50_trend_not_aligned"),
        (not rsi_healthy, "rsi_outside_momentum_band"),
        (not bullish_candle, "bullish_candle_confirmation_missing"),
    )
    reasons.extend(code for failed, code in reason_checks if failed)
    if candidate:
        reasons.append("all_six_scanner_checks_passed_paper_review_only")

    return {
        "market": "BTC/USD",
        "timeframe": "1h",
        "status": status,
        "lookback_candles": volume_lookback,
        "trend_lookback_candles": 50,
        "volume_spike_multiple_required": volume_spike_multiple,
        "current_volume": round(current_volume, 8),
        "prior_average_volume": round(average_volume, 8),
        "volume_ratio": round(volume_ratio, 4),
        "prior_lookback_high": round(prior_high, 2),
        "current_close": round(current_close, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "rsi14": round(rsi14, 2),
        "atr14": round(atr14, 2),
        "atr_pct": round(atr_pct, 4),
        "close_position_pct": round(close_position * 100.0, 2),
        "confluence_score": score,
        "confluence_total": len(scored_checks),
        "checks": checks,
        "reasons": reasons,
        "paper_candidate_only": True,
        "live_orders_placed": False,
        "limitations": [
            "BTC/USD only; no new-token discovery or on-chain rug-pull assessment.",
            "A scanner candidate is not a validated profitable strategy or an order instruction.",
            "No stop-loss, take-profit, or live execution is performed by this scanner.",
            "RSI, EMA and ATR are descriptive indicators, not predictive guarantees.",
        ],
    }
