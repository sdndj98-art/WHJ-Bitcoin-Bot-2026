"""Conservative BTC/USD hourly setup scanner; diagnostics only, never executes orders."""
import math


def scan_btc_market(candles, market_data_quality=None, volume_lookback=20,
                    volume_spike_multiple=1.5):
    """Flag a close above the prior lookback high with elevated volume.

    The current candle must be a completed candle supplied by the caller.
    This scanner is BTC/USD-only; it does not discover other token pairs,
    perform on-chain rug checks, or place orders.
    """
    if isinstance(volume_lookback, bool) or not isinstance(volume_lookback, int) or volume_lookback < 2:
        raise ValueError("volume_lookback must be an integer of at least 2")
    if (isinstance(volume_spike_multiple, bool)
            or not isinstance(volume_spike_multiple, (int, float))
            or not math.isfinite(volume_spike_multiple)
            or volume_spike_multiple <= 0):
        raise ValueError("volume_spike_multiple must be finite and positive")
    if not isinstance(candles, list) or len(candles) < volume_lookback + 1:
        raise ValueError("Not enough completed candles for scanner lookback")

    normalized = []
    for row in candles[-(volume_lookback + 1):]:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            raise ValueError("Each scanner candle must contain OHLCV and trade count")
        try:
            timestamp, open_price, high, low, close, volume = (
                float(row[0]), float(row[1]), float(row[2]),
                float(row[3]), float(row[4]), float(row[6])
            )
            trades = float(row[7])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Scanner candle fields must be numeric") from exc
        values = (timestamp, open_price, high, low, close, volume, trades)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Scanner candle fields must be finite")
        if timestamp < 0 or min(open_price, high, low, close) <= 0 or volume < 0 or trades < 0:
            raise ValueError("Scanner candle contains invalid price or activity values")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Scanner candle has inconsistent OHLC bounds")
        normalized.append((high, close, volume))

    previous = normalized[:-1]
    current_high, current_close, current_volume = normalized[-1]
    average_volume = sum(item[2] for item in previous) / volume_lookback
    volume_spike = average_volume > 0 and current_volume >= average_volume * volume_spike_multiple
    prior_high = max(item[0] for item in previous)
    breakout = current_close > prior_high
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
        "paper_only": True,
        "live_execution_enabled": False,
    }
    candidate = quality_ok and volume_spike and breakout
    reasons = []
    if not quality_ok:
        reasons.append("market_data_quality_blocked_or_unknown")
    if not volume_spike:
        reasons.append("volume_spike_not_confirmed")
    if not breakout:
        reasons.append("close_not_above_prior_20_high")
    if candidate:
        reasons.append("paper_candidate_only_all_scanner_checks_passed")

    return {
        "market": "BTC/USD",
        "timeframe": "1h",
        "status": "PAPER_CANDIDATE" if candidate else ("WATCH" if volume_spike or breakout else "NO_SETUP"),
        "lookback_candles": volume_lookback,
        "volume_spike_multiple_required": volume_spike_multiple,
        "current_volume": round(current_volume, 8),
        "prior_average_volume": round(average_volume, 8),
        "prior_lookback_high": round(prior_high, 2),
        "current_close": round(current_close, 2),
        "checks": checks,
        "reasons": reasons,
        "paper_candidate_only": True,
        "live_orders_placed": False,
        "limitations": [
            "BTC/USD only; no new-token discovery or on-chain rug-pull assessment.",
            "A scanner candidate is not a validated profitable strategy or an order instruction.",
            "No stop-loss, take-profit, or live execution is performed by this scanner.",
        ],
    }
