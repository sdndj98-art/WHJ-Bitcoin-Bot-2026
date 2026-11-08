"""Advanced OHLCV confluence diagnostics; research-only and non-executing.

Input rows may use the repository's 8-column candle schema
(timestamp, open, high, low, close, unused, volume, trades), or the
scanner's normalized 6-column schema (timestamp, open, high, low, close, volume).
All rolling references exclude the current candle where appropriate.
"""
import math


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric, not boolean")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _ema(values, period):
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _rsi(values, period=14):
    """Wilder RSI using an initial SMA seed and recursive Wilder smoothing."""
    if len(values) <= period:
        raise ValueError("Not enough values for RSI")
    changes = [b - a for a, b in zip(values, values[1:])]
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
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _efficiency_ratio(values, lookback=20):
    """Return Kaufman-style directional efficiency over completed closes."""
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
        raise ValueError("Efficiency lookback must be an integer >= 2")
    if len(values) <= lookback:
        raise ValueError("Not enough values for efficiency ratio")
    window = [float(value) for value in values[-(lookback + 1):]]
    path = sum(abs(current - previous)
               for previous, current in zip(window, window[1:]))
    net_change = window[-1] - window[0]
    if path <= 0:
        return 0.0, 0.0
    return abs(net_change) / path, net_change / path


def analyze_advanced_market(candles, volume_lookback=20, swing_lookback=20):
    """Return independent long/short context, confluence and diagnostics.

    This is an experimental signal-quality layer, not an order instruction.
    A liquidity sweep is a wick through a prior rolling extreme followed by a
    close back inside. A BOS is a close beyond the prior rolling extreme.
    """
    for name, value in (("volume_lookback", volume_lookback),
                        ("swing_lookback", swing_lookback)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 5:
            raise ValueError(f"{name} must be an integer >= 5")
    needed = max(35, volume_lookback + 1, swing_lookback + 1)
    if not isinstance(candles, (list, tuple)) or len(candles) < needed:
        raise ValueError(f"At least {needed} candles are required")
    rows = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise ValueError("Each candle must contain timestamp, OHLC and volume")
        volume_index = 6 if len(row) >= 8 else 5
        timestamp, op, high, low, close, volume = (
            _number(row[i], "candle field")
            for i in (0, 1, 2, 3, 4, volume_index)
        )
        if timestamp < 0 or min(op, high, low, close) <= 0 or volume < 0:
            raise ValueError("Candle contains invalid timestamp, price or volume")
        if high < max(op, close, low) or low > min(op, close, high):
            raise ValueError("Candle OHLC bounds are inconsistent")
        rows.append((timestamp, op, high, low, close, volume))
    if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("Candle timestamps must be strictly increasing")

    closes = [r[4] for r in rows]
    current = rows[-1]
    prior = rows[:-1]
    op, high, low, close, volume = current[1:]
    prior_volumes = [r[5] for r in prior[-volume_lookback:]]
    avg_volume = sum(prior_volumes) / volume_lookback
    rvol = volume / avg_volume if avg_volume > 0 else 0.0

    # Chaikin Money Flow: volume-weighted close location within each range.
    cmf_rows = rows[-20:]
    mf_volume = 0.0
    cmf_volume = 0.0
    for _, o, h, l, c, v in cmf_rows:
        multiplier = ((2.0 * c - h - l) / (h - l)) if h > l else 0.0
        mf_volume += multiplier * v
        cmf_volume += v
    cmf20 = mf_volume / cmf_volume if cmf_volume > 0 else 0.0

    # OBV slope uses only recent completed observations and is scale-normalized.
    obv = [0.0]
    for a, b in zip(rows, rows[1:]):
        delta = 1.0 if b[4] > a[4] else (-1.0 if b[4] < a[4] else 0.0)
        obv.append(obv[-1] + delta * b[5])
    obv_recent = obv[-6:]
    obv_slope = (obv_recent[-1] - obv_recent[0]) / max(
        sum(r[5] for r in rows[-5:]), 1e-12
    )

    typical_volumes = [(r[2] + r[3] + r[4]) / 3.0 * r[5] for r in rows[-20:]]
    vwap_volume = sum(r[5] for r in rows[-20:])
    rolling_vwap20 = (sum(typical_volumes) / vwap_volume
                      if vwap_volume > 0 else close)

    prior_swing_high = max(r[2] for r in prior[-swing_lookback:])
    prior_swing_low = min(r[3] for r in prior[-swing_lookback:])
    bullish_sweep = low < prior_swing_low and close > prior_swing_low
    bearish_sweep = high > prior_swing_high and close < prior_swing_high
    bullish_bos = close > prior_swing_high
    bearish_bos = close < prior_swing_low

    # Wilder ATR(14) from true ranges.
    true_ranges = []
    for i, row in enumerate(rows):
        prev_close = rows[i - 1][4] if i else row[4]
        true_ranges.append(max(row[2] - row[3],
                               abs(row[2] - prev_close),
                               abs(row[3] - prev_close)))
    atr = sum(true_ranges[:14]) / 14.0
    for tr in true_ranges[14:]:
        atr = (atr * 13.0 + tr) / 14.0
    body_atr = abs(close - op) / atr if atr > 0 else 0.0
    close_location = (close - low) / (high - low) if high > low else 0.5
    bullish_displacement = close > op and body_atr >= 0.8 and close_location >= 0.70
    bearish_displacement = close < op and body_atr >= 0.8 and close_location <= 0.30

    fast = _ema(closes, 12)
    slow = _ema(closes, 26)
    macd_line = fast - slow
    # Signal line computed from the trailing MACD series, not future data.
    macd_series = []
    for end in range(26, len(closes) + 1):
        segment = closes[:end]
        macd_series.append(_ema(segment, 12) - _ema(segment, 26))
    macd_signal = _ema(macd_series, 9) if len(macd_series) >= 9 else macd_line
    macd_hist = macd_line - macd_signal
    rsi14 = _rsi(closes, 14)
    efficiency_ratio20, efficiency_direction20 = _efficiency_ratio(closes, 20)
    trend_efficiency_confirmed = (
        efficiency_ratio20 >= 0.35 and efficiency_direction20 > 0
    )
    bearish_efficiency_confirmed = (
        efficiency_ratio20 >= 0.35 and efficiency_direction20 < 0
    )

    checks = {
        "relative_volume_expansion": rvol >= 1.5,
        "cmf_buying_pressure": cmf20 > 0.05,
        "obv_accumulation": obv_slope > 0.05,
        "price_above_rolling_vwap": close > rolling_vwap20,
        "bullish_liquidity_sweep": bullish_sweep,
        "bullish_break_of_structure": bullish_bos,
        "bullish_displacement": bullish_displacement,
        "macd_momentum_positive": macd_hist > 0,
        "rsi_momentum_confirmed": 50.0 <= rsi14 <= 72.0,
        "trend_efficiency_confirmed": trend_efficiency_confirmed,
    }
    short_checks = {
        "relative_volume_expansion": rvol >= 1.5,
        "cmf_selling_pressure": cmf20 < -0.05,
        "obv_distribution": obv_slope < -0.05,
        "price_below_rolling_vwap": close < rolling_vwap20,
        "bearish_liquidity_sweep": bearish_sweep,
        "bearish_break_of_structure": bearish_bos,
        "bearish_displacement": bearish_displacement,
        "macd_momentum_negative": macd_hist < 0,
        "rsi_momentum_confirmed": 28.0 <= rsi14 <= 50.0,
        "trend_efficiency_confirmed": bearish_efficiency_confirmed,
    }
    bull_score = sum(checks.values())
    bear_score = sum(short_checks.values())
    # Keep sweep and structure as separate event types; do not require both
    # on the same candle to avoid making the layer structurally impossible.
    bull_candidate = bull_score >= 6 and trend_efficiency_confirmed and (
        bullish_sweep or bullish_bos
    ) and (checks["cmf_buying_pressure"] or checks["obv_accumulation"])
    bear_candidate = bear_score >= 6 and bearish_efficiency_confirmed and (
        bearish_sweep or bearish_bos
    ) and (short_checks["cmf_selling_pressure"] or short_checks["obv_distribution"])
    return {
        "version": "advanced_ohlcv_confluence_v2",
        "status": ("BULLISH_RESEARCH_CANDIDATE" if bull_candidate else
                   "BEARISH_RESEARCH_CANDIDATE" if bear_candidate else "WATCH"),
        "bullish_score": bull_score,
        "bearish_score": bear_score,
        "score_total": len(checks),
        "efficiency_ratio_20": round(efficiency_ratio20, 6),
        "efficiency_direction_20": round(efficiency_direction20, 6),
        "trend_efficiency_minimum": 0.35,
        "bullish_checks": checks,
        "bearish_checks": short_checks,
        "relative_volume": round(rvol, 4),
        "average_prior_volume": round(avg_volume, 8),
        "cmf20": round(cmf20, 6),
        "obv_slope_normalized": round(obv_slope, 6),
        "rolling_vwap20": round(rolling_vwap20, 8),
        "prior_swing_high": round(prior_swing_high, 8),
        "prior_swing_low": round(prior_swing_low, 8),
        "bullish_liquidity_sweep": bullish_sweep,
        "bearish_liquidity_sweep": bearish_sweep,
        "bullish_bos": bullish_bos,
        "bearish_bos": bearish_bos,
        "atr14": round(atr, 8),
        "body_atr": round(body_atr, 4),
        "close_location_pct": round(close_location * 100.0, 2),
        "rsi14": round(rsi14, 4),
        "macd_line": round(macd_line, 8),
        "macd_signal": round(macd_signal, 8),
        "macd_histogram": round(macd_hist, 8),
        "research_only": True,
        "execution_enabled": False,
        "live_orders_placed": False,
        "volume_semantics": "Input volume units are provider-dependent; MT5 may supply tick volume, not centralized traded volume.",
        "limitations": [
            "Rolling swing highs/lows are proxies for liquidity pools, not observed resting orders or order-book depth.",
            "A wick sweep and a close beyond a prior extreme are mutually exclusive on the same bar by construction.",
            "CMF, OBV, VWAP and volume ratios are only as reliable as the supplied provider volume.",
            "Signals use completed input bars only; callers must exclude the still-forming candle.",
            "Thresholds are experimental and require out-of-sample and forward paper validation.",
            "Kaufman efficiency ratio >= 0.35 is an experimental anti-chop confirmation, not a predictive guarantee.",
        ],
    }
