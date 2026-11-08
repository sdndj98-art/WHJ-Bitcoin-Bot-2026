"""Independent Bitstamp expanding-window ADX walk-forward validation.

Uses the same training-only threshold selector and aligned 4h/6h fold
boundaries as the primary walk-forward research, but fetches a separate
Bitstamp BTCUSD hourly history. Research only: no paper state or orders.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from adx_walk_forward import run_expanding_walk_forward
from ema_adx_cross_exchange_lab import fetch_bitstamp_hourly_candles


def main():
    candles = fetch_bitstamp_hourly_candles()
    report = run_expanding_walk_forward(candles)
    report.update({
        "validation_type": "INDEPENDENT_CROSS_EXCHANGE_EXPANDING_WALK_FORWARD",
        "data_source": "Bitstamp public spot OHLC",
        "symbol": "BTCUSD",
        "hourly_candles": len(candles),
        "first_candle_time_utc": datetime.fromtimestamp(
            candles[0]["timestamp"] / 1000, timezone.utc
        ).isoformat(),
        "last_candle_time_utc": datetime.fromtimestamp(
            candles[-1]["timestamp"] / 1000, timezone.utc
        ).isoformat(),
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "interpretation": (
            "Independent Bitstamp expanding-window walk-forward. Each fold's "
            "threshold is selected only from earlier training data using the "
            "fixed selection rule; its own test interval is never used for "
            "selection. This is historical research, not forward-paper or live "
            "performance."
        ),
    })
    Path("adx_bitstamp_walk_forward_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
