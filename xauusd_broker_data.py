"""Broker-exported XAUUSD bid/ask research data contract.

This module deliberately does not download data, connect to a broker, or place
orders. It accepts a broker-exported CSV with synchronized bid/ask OHLC bars,
requires an explicit UTC session calendar, and keeps spread, slippage,
commission, and rollover financing separate from BTC assumptions.

A static UTC session calendar is valid only for its broker/DST regime. Split
historical exports at broker daylight-saving transitions and pass the matching
UTC schedule for each segment; DST is never inferred by this module.
"""
import csv
import hashlib
import io
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

_REQUIRED_COLUMNS = {
    "symbol", "timeframe_minutes", "timestamp_utc",
    "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close",
}
_PRICE_FIELDS = ("open", "high", "low", "close")
_COST_FIELDS = {
    "contract_size_oz_per_lot",
    "commission_usd_per_lot_per_side",
    "slippage_bps_per_side",
    "swap_long_usd_per_oz_per_rollover",
    "swap_short_usd_per_oz_per_rollover",
    "triple_swap_weekday",
    "quote_currency",
}


def _finite_number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if positive and number <= 0:
        raise ValueError(f"{name} must be positive")
    if nonnegative and number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _parse_utc_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp_utc must be a timezone-aware ISO-8601 timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("timestamp_utc must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_utc must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def _minute_of_week(value):
    return value.weekday() * 1440 + value.hour * 60 + value.minute


def _validate_session_config(config):
    if not isinstance(config, dict):
        raise ValueError("an explicit broker session_config is required")
    required = {
        "weekly_open_weekday", "weekly_open_minute_utc",
        "weekly_close_weekday", "weekly_close_minute_utc",
        "daily_breaks_utc", "closed_dates_utc",
    }
    missing = required - set(config)
    if missing:
        raise ValueError("session_config missing: " + ", ".join(sorted(missing)))

    normalized = dict(config)
    for key in ("weekly_open_weekday", "weekly_close_weekday"):
        value = normalized[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 6:
            raise ValueError(f"{key} must be an integer weekday in [0, 6]")
    for key in ("weekly_open_minute_utc", "weekly_close_minute_utc"):
        value = normalized[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1440:
            raise ValueError(f"{key} must be an integer minute in [0, 1439]")

    open_minute = normalized["weekly_open_weekday"] * 1440 + normalized["weekly_open_minute_utc"]
    close_minute = normalized["weekly_close_weekday"] * 1440 + normalized["weekly_close_minute_utc"]
    if open_minute == close_minute:
        raise ValueError("weekly session open and close cannot be identical")

    breaks = normalized["daily_breaks_utc"]
    if not isinstance(breaks, list):
        raise ValueError("daily_breaks_utc must be a list; use [] when the broker has no daily break")
    clean_breaks = []
    for item in breaks:
        if not isinstance(item, dict):
            raise ValueError("each daily break must be an object")
        start = item.get("start_minute_utc")
        end = item.get("end_minute_utc")
        if any(isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < 1440 for x in (start, end)):
            raise ValueError("daily break minutes must be integers in [0, 1439]")
        if start == end:
            raise ValueError("daily break start and end cannot be identical")
        clean_breaks.append({"start_minute_utc": start, "end_minute_utc": end})
    normalized["daily_breaks_utc"] = clean_breaks

    closed = normalized["closed_dates_utc"]
    if not isinstance(closed, list):
        raise ValueError("closed_dates_utc must be a list; use [] only when the broker confirms no closures")
    clean_dates = []
    for item in closed:
        try:
            parsed = date.fromisoformat(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("closed_dates_utc entries must be YYYY-MM-DD") from exc
        clean_dates.append(parsed)
    normalized["closed_dates_utc"] = set(clean_dates)
    return normalized


def _weekly_open(value, config):
    current = _minute_of_week(value)
    opening = config["weekly_open_weekday"] * 1440 + config["weekly_open_minute_utc"]
    closing = config["weekly_close_weekday"] * 1440 + config["weekly_close_minute_utc"]
    if opening < closing:
        return opening <= current < closing
    return current >= opening or current < closing


def _overlaps_daily_break(start, end, config):
    day = start.date()
    last_day = (end - timedelta(microseconds=1)).date()
    while day <= last_day:
        for item in config["daily_breaks_utc"]:
            break_start = datetime.combine(day, time.min, tzinfo=timezone.utc) + timedelta(
                minutes=item["start_minute_utc"]
            )
            break_end = datetime.combine(day, time.min, tzinfo=timezone.utc) + timedelta(
                minutes=item["end_minute_utc"]
            )
            if item["end_minute_utc"] <= item["start_minute_utc"]:
                break_end += timedelta(days=1)
            if start < break_end and end > break_start:
                return True
        day += timedelta(days=1)
    return False


def _crosses_weekly_boundary(start, end, config):
    day = start.date() - timedelta(days=1)
    last_day = end.date() + timedelta(days=1)
    while day <= last_day:
        if day.weekday() == config["weekly_open_weekday"]:
            boundary = datetime.combine(day, time.min, tzinfo=timezone.utc) + timedelta(
                minutes=config["weekly_open_minute_utc"]
            )
            if start < boundary < end:
                return True
        if day.weekday() == config["weekly_close_weekday"]:
            boundary = datetime.combine(day, time.min, tzinfo=timezone.utc) + timedelta(
                minutes=config["weekly_close_minute_utc"]
            )
            if start < boundary < end:
                return True
        day += timedelta(days=1)
    return False


def _validate_bar_session(start, end, config):
    if _crosses_weekly_boundary(start, end, config):
        raise ValueError("bar crosses a configured weekly session boundary")
    if not _weekly_open(start, config):
        raise ValueError("bar starts outside the configured broker weekly session")
    if not _weekly_open(end - timedelta(microseconds=1), config):
        raise ValueError("bar ends outside the configured broker weekly session")
    day = start.date()
    last_day = (end - timedelta(microseconds=1)).date()
    while day <= last_day:
        if day in config["closed_dates_utc"]:
            raise ValueError("bar overlaps a broker-declared closed date")
        day += timedelta(days=1)
    if _overlaps_daily_break(start, end, config):
        raise ValueError("bar overlaps a configured daily rollover/break window")


def parse_xauusd_bid_ask_csv(csv_text, *, expected_timeframe_minutes, session_config, source_id):
    """Parse broker-exported CSV; timestamps denote UTC bar starts.

    Required columns: symbol, timeframe_minutes, timestamp_utc, bid_open/high/low/close,
    ask_open/high/low/close. Session calendar and source identifier are mandatory.
    Missing candles are never imputed and out-of-session rows are never silently dropped.
    """
    if isinstance(csv_text, bytes):
        raw_bytes = csv_text
        try:
            csv_text = csv_text.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("broker CSV must be UTF-8") from exc
    elif isinstance(csv_text, str):
        raw_bytes = csv_text.encode("utf-8")
    else:
        raise ValueError("csv_text must be str or bytes")

    if isinstance(expected_timeframe_minutes, bool) or not isinstance(expected_timeframe_minutes, int) or expected_timeframe_minutes <= 0:
        raise ValueError("expected_timeframe_minutes must be a positive integer")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id must identify the broker/export source")
    session = _validate_session_config(session_config)

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("broker CSV has no header")
    missing = _REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError("broker CSV missing columns: " + ", ".join(sorted(missing)))

    bars = []
    previous_ms = None
    observed_gaps = []
    open_spreads, close_spreads = [], []
    timeframe_ms = expected_timeframe_minutes * 60_000

    for line_number, row in enumerate(reader, start=2):
        symbol = (row.get("symbol") or "").strip().upper().replace("/", "")
        if symbol != "XAUUSD":
            raise ValueError(f"line {line_number}: expected XAUUSD spot/CFD, received {symbol or 'blank'}")
        try:
            row_timeframe = int(row.get("timeframe_minutes"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"line {line_number}: invalid timeframe_minutes") from exc
        if row_timeframe != expected_timeframe_minutes:
            raise ValueError(f"line {line_number}: timeframe does not match the requested interval")

        stamp = _parse_utc_timestamp(row.get("timestamp_utc"))
        timestamp_ms = int(stamp.timestamp() * 1000)
        if previous_ms is not None:
            if timestamp_ms <= previous_ms:
                raise ValueError("broker bar timestamps must be strictly increasing and unique")
            delta = timestamp_ms - previous_ms
            if delta > timeframe_ms:
                observed_gaps.append({
                    "after_timestamp_ms": previous_ms,
                    "before_timestamp_ms": timestamp_ms,
                    "gap_minutes": delta // 60_000 - expected_timeframe_minutes,
                })
        previous_ms = timestamp_ms

        prices = {}
        for side in ("bid", "ask"):
            values = {}
            for field in _PRICE_FIELDS:
                key = f"{side}_{field}"
                values[field] = _finite_number(row.get(key), f"line {line_number} {key}", positive=True)
            if values["high"] < max(values["open"], values["low"], values["close"]):
                raise ValueError(f"line {line_number}: impossible {side} high")
            if values["low"] > min(values["open"], values["high"], values["close"]):
                raise ValueError(f"line {line_number}: impossible {side} low")
            prices[side] = values

        spreads = {}
        for field in _PRICE_FIELDS:
            bid = prices["bid"][field]
            ask = prices["ask"][field]
            if ask < bid:
                raise ValueError(f"line {line_number}: ask {field} is below bid")
            mid = (ask + bid) / 2.0
            spreads[field] = (ask - bid) / mid * 10_000.0

        bar_end = stamp + timedelta(minutes=expected_timeframe_minutes)
        _validate_bar_session(stamp, bar_end, session)
        mid_open = (prices["ask"]["open"] + prices["bid"]["open"]) / 2.0
        mid_close = (prices["ask"]["close"] + prices["bid"]["close"]) / 2.0
        bars.append({
            "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
            "timestamp_ms": timestamp_ms,
            **{f"bid_{k}": v for k, v in prices["bid"].items()},
            **{f"ask_{k}": v for k, v in prices["ask"].items()},
            "mid_open": mid_open,
            "mid_close": mid_close,
            "spread_open_bps": spreads["open"],
            "spread_close_bps": spreads["close"],
            "spread_max_bps": max(spreads.values()),
        })
        open_spreads.append(spreads["open"])
        close_spreads.append(spreads["close"])

    if not bars:
        raise ValueError("broker CSV contains no data rows")
    all_spreads = sorted(open_spreads + close_spreads)
    middle = len(all_spreads) // 2
    median_spread = all_spreads[middle] if len(all_spreads) % 2 else (
        all_spreads[middle - 1] + all_spreads[middle]
    ) / 2.0
    return {
        "symbol": "XAUUSD",
        "asset_type": "broker_spot_or_cfd_bid_ask",
        "source_id": source_id.strip(),
        "timeframe_minutes": expected_timeframe_minutes,
        "timestamp_semantics": "UTC bar-open timestamp; each bar must fit wholly inside configured broker session",
        "session_calendar_assumption": "Static UTC schedule applies only to one broker/DST regime; split exports at DST transitions and validate each segment with its own explicit UTC schedule.",
        "dataset_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "bar_count": len(bars),
        "first_timestamp_utc": bars[0]["timestamp_utc"],
        "last_timestamp_utc": bars[-1]["timestamp_utc"],
        "observed_timestamp_gap_count_including_scheduled_closures": len(observed_gaps),
        "observed_timestamp_gaps": observed_gaps,
        "imputed_bar_count": 0,
        "spread_summary_bps": {
            "median_open_and_close": median_spread,
            "maximum_open_or_close": max(all_spreads),
        },
        "session_config": {
            **{k: v for k, v in session.items() if k != "closed_dates_utc"},
            "closed_dates_utc": sorted(d.isoformat() for d in session["closed_dates_utc"]),
        },
        "bars": bars,
        "research_only": True,
        "live_orders": False,
    }


def load_xauusd_bid_ask_csv(path, *, expected_timeframe_minutes, session_config, source_id):
    """Read original broker-export bytes and preserve their SHA-256 provenance."""
    raw = Path(path).read_bytes()
    return parse_xauusd_bid_ask_csv(
        raw,
        expected_timeframe_minutes=expected_timeframe_minutes,
        session_config=session_config,
        source_id=source_id,
    )


def validate_xauusd_cost_model(model):
    """Require broker-supplied contract, commission, slippage, and swap terms."""
    if not isinstance(model, dict):
        raise ValueError("an explicit broker cost_model is required")
    missing = _COST_FIELDS - set(model)
    if missing:
        raise ValueError("cost_model missing: " + ", ".join(sorted(missing)))
    clean = dict(model)
    clean["contract_size_oz_per_lot"] = _finite_number(
        model["contract_size_oz_per_lot"], "contract_size_oz_per_lot", positive=True
    )
    clean["commission_usd_per_lot_per_side"] = _finite_number(
        model["commission_usd_per_lot_per_side"], "commission_usd_per_lot_per_side", nonnegative=True
    )
    clean["slippage_bps_per_side"] = _finite_number(
        model["slippage_bps_per_side"], "slippage_bps_per_side", nonnegative=True
    )
    clean["swap_long_usd_per_oz_per_rollover"] = _finite_number(
        model["swap_long_usd_per_oz_per_rollover"], "swap_long_usd_per_oz_per_rollover"
    )
    clean["swap_short_usd_per_oz_per_rollover"] = _finite_number(
        model["swap_short_usd_per_oz_per_rollover"], "swap_short_usd_per_oz_per_rollover"
    )
    weekday = model["triple_swap_weekday"]
    if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise ValueError("triple_swap_weekday must be an integer weekday in [0, 6]")
    if model["quote_currency"] != "USD":
        raise ValueError("this research cost model currently requires USD-quoted XAUUSD")
    return clean


def estimate_xauusd_round_trip(
    *, side, lots, entry_bid, entry_ask, exit_bid, exit_ask,
    rollover_dates, cost_model,
):
    """Estimate one closed XAUUSD position; accounting only, not execution.

    Bid/ask spread is embedded in executable entry/exit prices and reported
    separately for diagnostics; do not subtract spread_cost_usd a second time.
    Swap rates are signed broker-provided USD/oz/rollover values; triple rollover
    is applied on the broker-declared weekday.
    """
    if side not in ("long", "short"):
        raise ValueError("side must be 'long' or 'short'")
    lots = _finite_number(lots, "lots", positive=True)
    prices = {
        "entry_bid": _finite_number(entry_bid, "entry_bid", positive=True),
        "entry_ask": _finite_number(entry_ask, "entry_ask", positive=True),
        "exit_bid": _finite_number(exit_bid, "exit_bid", positive=True),
        "exit_ask": _finite_number(exit_ask, "exit_ask", positive=True),
    }
    if prices["entry_ask"] < prices["entry_bid"] or prices["exit_ask"] < prices["exit_bid"]:
        raise ValueError("ask prices must be greater than or equal to bid prices")
    model = validate_xauusd_cost_model(cost_model)
    if not isinstance(rollover_dates, (list, tuple)):
        raise ValueError("rollover_dates must be an ordered list of YYYY-MM-DD dates")
    dates = []
    for value in rollover_dates:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("rollover_dates entries must be YYYY-MM-DD") from exc
        if dates and parsed <= dates[-1]:
            raise ValueError("rollover_dates must be strictly increasing and unique")
        dates.append(parsed)

    quantity_oz = lots * model["contract_size_oz_per_lot"]
    direction = 1.0 if side == "long" else -1.0
    mid_entry = (prices["entry_bid"] + prices["entry_ask"]) / 2.0
    mid_exit = (prices["exit_bid"] + prices["exit_ask"]) / 2.0
    executable_entry = prices["entry_ask"] if side == "long" else prices["entry_bid"]
    executable_exit = prices["exit_bid"] if side == "long" else prices["exit_ask"]
    mid_pnl = (mid_exit - mid_entry) * quantity_oz * direction
    spread_adjusted_pnl = (executable_exit - executable_entry) * quantity_oz * direction
    spread_cost = mid_pnl - spread_adjusted_pnl

    slip = model["slippage_bps_per_side"] / 10_000.0
    if side == "long":
        entry_fill = executable_entry * (1.0 + slip)
        exit_fill = executable_exit * (1.0 - slip)
    else:
        entry_fill = executable_entry * (1.0 - slip)
        exit_fill = executable_exit * (1.0 + slip)
    after_slippage_pnl = (exit_fill - entry_fill) * quantity_oz * direction
    slippage_cost = spread_adjusted_pnl - after_slippage_pnl
    commission = 2.0 * model["commission_usd_per_lot_per_side"] * lots
    swap_rate = model[
        "swap_long_usd_per_oz_per_rollover" if side == "long"
        else "swap_short_usd_per_oz_per_rollover"
    ]
    swap_pnl = sum(
        swap_rate * quantity_oz * (3 if rollover.weekday() == model["triple_swap_weekday"] else 1)
        for rollover in dates
    )
    net_pnl = after_slippage_pnl - commission + swap_pnl
    return {
        "side": side,
        "lots": lots,
        "quantity_oz": quantity_oz,
        "entry_fill_price": entry_fill,
        "exit_fill_price": exit_fill,
        "mid_market_pnl_usd": mid_pnl,
        "spread_cost_usd_diagnostic_only": spread_cost,
        "pnl_after_spread_before_slippage_usd": spread_adjusted_pnl,
        "slippage_cost_usd": slippage_cost,
        "commission_cost_usd": commission,
        "swap_pnl_usd": swap_pnl,
        "rollover_count": len(dates),
        "net_pnl_usd": net_pnl,
        "cost_model": model,
        "live_orders": False,
    }
