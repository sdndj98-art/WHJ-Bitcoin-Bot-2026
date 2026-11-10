"""Research-only price/open-interest flow classification.

Inputs must be matched observations from the same venue, instrument and interval.
This module does not fetch data, generate calibrated probabilities, or execute trades.
"""
from datetime import datetime, timezone
import math


def _parse_time(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be an ISO-8601 timestamp".format(label))
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("{} must be an ISO-8601 timestamp".format(label)) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("{} must include a timezone".format(label))
    return parsed.astimezone(timezone.utc)


def _finite_pct(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be numeric".format(label))
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("{} must be finite".format(label))
    return result


def _blocked(reason):
    return {
        "status": "DATA_BLOCKED",
        "classification": "UNAVAILABLE",
        "direction": "UNKNOWN",
        "signal_strength_score": None,
        "score_type": "HEURISTIC_MAGNITUDE_NOT_PROBABILITY",
        "reason": reason,
        "research_only": True,
        "execution_enabled": False,
    }


def classify_derivatives_flow(
    price_snapshot,
    open_interest_snapshot,
    as_of=None,
    max_age_seconds=300,
    max_timestamp_skew_seconds=5,
    min_abs_change_pct=0.05,
):
    """Classify the four conventional price/OI regimes from aligned snapshots.

    Each snapshot requires source, symbol, interval_start, interval_end,
    observed_at and change_pct. Timestamps must be timezone-aware ISO-8601.
    """
    if as_of is None:
        now = datetime.now(timezone.utc)
    else:
        now = _parse_time(as_of, "as_of")
    for name, value in (
        ("max_age_seconds", max_age_seconds),
        ("max_timestamp_skew_seconds", max_timestamp_skew_seconds),
        ("min_abs_change_pct", min_abs_change_pct),
    ):
        invalid_bound = value <= 0 if name == "min_abs_change_pct" else value < 0
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or invalid_bound):
            qualifier = "positive" if name == "min_abs_change_pct" else "non-negative"
            raise ValueError("{} must be a finite {}".format(name, qualifier))

    if not isinstance(price_snapshot, dict) or not isinstance(open_interest_snapshot, dict):
        return _blocked("Price and open-interest snapshots are both required")

    required = ("source", "symbol", "interval_start", "interval_end", "observed_at", "change_pct")
    for label, snapshot in (("price", price_snapshot), ("open_interest", open_interest_snapshot)):
        if any(key not in snapshot for key in required):
            return _blocked("{} snapshot is incomplete".format(label))
        for key in ("source", "symbol"):
            if not isinstance(snapshot[key], str) or not snapshot[key].strip():
                return _blocked("{} snapshot has invalid {}".format(label, key))

    if price_snapshot["source"].strip().lower() != open_interest_snapshot["source"].strip().lower():
        return _blocked("Price and open interest must come from the same venue/source")
    if price_snapshot["symbol"].strip().upper() != open_interest_snapshot["symbol"].strip().upper():
        return _blocked("Price and open interest symbols do not match")

    try:
        price_start = _parse_time(price_snapshot["interval_start"], "price interval_start")
        oi_start = _parse_time(open_interest_snapshot["interval_start"], "open_interest interval_start")
        price_end = _parse_time(price_snapshot["interval_end"], "price interval_end")
        oi_end = _parse_time(open_interest_snapshot["interval_end"], "open_interest interval_end")
        price_observed = _parse_time(price_snapshot["observed_at"], "price observed_at")
        oi_observed = _parse_time(open_interest_snapshot["observed_at"], "open_interest observed_at")
        price_change = _finite_pct(price_snapshot["change_pct"], "price change_pct")
        oi_change = _finite_pct(open_interest_snapshot["change_pct"], "open_interest change_pct")
    except ValueError as exc:
        return _blocked(str(exc))

    if price_start != oi_start or price_end != oi_end:
        return _blocked("Price and open-interest measurement intervals are not aligned")
    if price_end <= price_start or oi_end <= oi_start:
        return _blocked("Measurement intervals must have positive duration")
    if price_end > now or oi_end > now or price_observed > now or oi_observed > now:
        return _blocked("Future-dated market observations are not accepted")
    if abs((price_observed - oi_observed).total_seconds()) > max_timestamp_skew_seconds:
        return _blocked("Price and open-interest observation timestamps are too far apart")
    age = (now - min(price_observed, oi_observed)).total_seconds()
    if age > max_age_seconds:
        return _blocked("Market observations are stale")

    price_active = abs(price_change) >= min_abs_change_pct
    oi_active = abs(oi_change) >= min_abs_change_pct
    if not price_active or not oi_active:
        classification = "NO_CLEAR_BUILDUP"
        direction = "NEUTRAL"
        explanation = "One or both changes are below the configured noise threshold"
    elif price_change > 0 and oi_change > 0:
        classification = "LONG_BUILDUP"
        direction = "BULLISH"
        explanation = "Price and open interest both increased"
    elif price_change < 0 and oi_change > 0:
        classification = "SHORT_BUILDUP"
        direction = "BEARISH"
        explanation = "Price decreased while open interest increased"
    elif price_change > 0 and oi_change < 0:
        classification = "SHORT_COVERING"
        direction = "BULLISH"
        explanation = "Price increased while open interest decreased"
    else:
        classification = "LONG_UNWINDING"
        direction = "BEARISH"
        explanation = "Price and open interest both decreased"

    magnitude = min(abs(price_change), abs(oi_change))
    strength = round(min(100.0, magnitude / 1.0 * 100.0), 2) if classification != "NO_CLEAR_BUILDUP" else 0.0
    return {
        "status": "OK",
        "classification": classification,
        "direction": direction,
        "price_change_pct": round(price_change, 6),
        "open_interest_change_pct": round(oi_change, 6),
        "signal_strength_score": strength,
        "score_type": "HEURISTIC_MAGNITUDE_NOT_PROBABILITY",
        "explanation": explanation,
        "source": price_snapshot["source"],
        "symbol": price_snapshot["symbol"],
        "interval_start": price_snapshot["interval_start"],
        "interval_end": price_snapshot["interval_end"],
        "observation_age_seconds": round(age, 3),
        "thresholds": {
            "max_age_seconds": max_age_seconds,
            "max_timestamp_skew_seconds": max_timestamp_skew_seconds,
            "min_abs_change_pct": min_abs_change_pct,
        },
        "limitations": [
            "Open-interest regimes are heuristics, not proof of trader intent or position direction.",
            "The magnitude score is not a probability or calibrated conviction estimate.",
            "Use funding, volume, liquidations and price structure as separate confirmations.",
        ],
        "research_only": True,
        "execution_enabled": False,
    }
