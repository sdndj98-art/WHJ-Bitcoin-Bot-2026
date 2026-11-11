"""Forward-only monitor for the four historically qualified candidate ledgers.

Historical bars warm indicators only. Existing ledgers are validated and never reset.
No exchange credentials, order endpoints, or live execution are used.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from atr_trailing_paper import (
    _load as _load_atr_state,
    seed_atr_trailing_account,
    update_atr_trailing_account,
)
from forward_paper_monitor import validate_hourly_feed
from historical_research import aggregate_candles, load_two_year_candles
from paper_account import (
    _load_state as _load_qualified_state,
    seed_forward_paper_account,
    update_paper_account,
)


DEFAULT_STATE_DIR = Path(
    "research_runs/20261111_atr_forward_validation/paper_state"
)
CANDIDATES = {
    "1d_sma_trend": {
        "file": "paper_qualified_1d_sma_trend.json",
        "hours": 24,
        "strategy": "sma_trend",
        "initial_cash": 250.0,
    },
    "6h_ema50_200_regime": {
        "file": "paper_qualified_6h_ema50_200_regime.json",
        "hours": 6,
        "strategy": "ema50_200_regime",
        "initial_cash": 250.0,
    },
    "6h_ema_pullback_trend": {
        "file": "paper_qualified_6h_ema_pullback_trend.json",
        "hours": 6,
        "strategy": "ema_pullback_trend",
        "initial_cash": 250.0,
    },
}
ATR_FILE = "paper_qualified_4h_ema20_50_daily_sma200_atr3.json"


def _native_bars(candles, hours):
    bars = aggregate_candles(candles, hours)
    return [
        {
            "timestamp": int(row["timestamp"] // 1000),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0.0)),
            "imputed": bool(row.get("imputed", False)),
            "execution_eligible": not bool(row.get("imputed", False)),
        }
        for row in bars
    ]


def _account_rows(bars):
    # The sixth field is consumed by paper_account as execution eligibility.
    return [
        [
            int(row["timestamp"]),
            0,
            0,
            0,
            str(row["close"]),
            bool(row["execution_eligible"]),
        ]
        for row in bars
    ]


def _existing_timestamp(path, strategy):
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Existing qualified ledger is unreadable; refusing to reset: {path}"
        ) from exc
    if not isinstance(state, dict) or state.get("strategy") != strategy:
        raise ValueError(f"Existing qualified ledger strategy mismatch: {path}")
    key = "last_timestamp"
    timestamp = state.get(key)
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError(f"Existing qualified ledger timestamp is invalid: {path}")
    if not math.isfinite(float(timestamp)) or int(timestamp) != timestamp:
        raise ValueError(f"Existing qualified ledger timestamp is invalid: {path}")
    return int(timestamp)


def _existing_processed_count(path):
    """Validate the ATR ledger's cumulative counter before any account is mutated."""
    if not path.exists():
        return 0
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Existing ATR ledger is unreadable; refusing to update any qualified ledger: {path}"
        ) from exc
    value = state.get("processed_new_candles") if isinstance(state, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"Existing ATR ledger processing counter is invalid; refusing partial update: {path}"
        )
    return value


def _write_json_atomically(payload, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            import os
            os.fsync(handle.fileno())
        import os
        os.replace(temporary, target)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def process_qualified_forward_candidates(
    candles, state_dir=DEFAULT_STATE_DIR, now_timestamp=None
):
    """Update all four qualified ledgers once, using completed native-timeframe bars."""
    quality = validate_hourly_feed(candles, now_timestamp)
    directory = Path(state_dir)

    # Preflight every required timeframe before mutating any account.
    try:
        bars = {
            4: _native_bars(candles, 4),
            6: _native_bars(candles, 6),
            24: _native_bars(candles, 24),
        }
    except ValueError as exc:
        if "Not enough complete" in str(exc):
            raise ValueError(
                "Insufficient native timeframe history; no qualified ledger was changed: "
                + str(exc)
            ) from exc
        raise
    insufficient = [
        f"{hours}h={len(rows)} (need {201 if hours == 4 else 200})"
        for hours, rows in bars.items()
        if len(rows) < (201 if hours == 4 else 200)
    ]
    if insufficient:
        raise ValueError(
            "Insufficient native timeframe history; no qualified ledger was changed: "
            + ", ".join(insufficient)
        )

    # Check every existing checkpoint before the first write. This catches a
    # stale or mismatched feed before any subset of the portfolio is advanced.
    for name, config in CANDIDATES.items():
        path = directory / config["file"]
        last = _existing_timestamp(path, config["strategy"])
        if path.exists():
            _load_qualified_state(
                path, config["initial_cash"], config["strategy"]
            )
        latest = bars[config["hours"]][-1]["timestamp"]
        if last is not None and latest < last:
            raise ValueError(
                f"Feed is older than saved {name} checkpoint; refusing rollback"
            )
    atr_path = directory / ATR_FILE
    atr_last = _existing_timestamp(
        atr_path, "ema20_50_daily_sma200_atr3_trailing"
    )
    if atr_last is not None and bars[4][-1]["timestamp"] < atr_last:
        raise ValueError("Feed is older than saved ATR checkpoint; refusing rollback")
    # Validate every ATR field read later before the first of the four ledgers
    # is updated. This prevents a corrupt ATR counter from causing a partial cycle.
    atr_processed_before = _existing_processed_count(atr_path)
    if atr_path.exists():
        _load_atr_state(atr_path, 250.0)

    results = {}
    for name, config in CANDIDATES.items():
        native = bars[config["hours"]]
        rows = _account_rows(native)
        path = directory / config["file"]
        seed = seed_forward_paper_account(
            rows,
            state_path=str(path),
            initial_cash=config["initial_cash"],
            strategy=config["strategy"],
        )
        account = update_paper_account(
            rows,
            state_path=str(path),
            initial_cash=config["initial_cash"],
            allocation_fraction=0.10,
            max_drawdown_fraction=0.10,
            daily_loss_fraction=0.03,
            max_consecutive_losses=5,
            strategy=config["strategy"],
            strategy_health_pause=True,
            strategy_health_drawdown_fraction=0.08,
        )
        results[name] = {
            "seed": seed,
            "account": account,
            "native_timeframe_hours": config["hours"],
            "last_processed_timestamp": account["last_processed_timestamp"],
        }

    four_hour = bars[4]
    daily = bars[24]
    atr_seed = seed_atr_trailing_account(
        four_hour,
        daily,
        str(atr_path),
        initial_cash=250.0,
    )
    atr_account = update_atr_trailing_account(
        four_hour,
        daily,
        str(atr_path),
        initial_cash=250.0,
        allocation_fraction=0.10,
        max_drawdown_fraction=0.10,
        daily_loss_fraction=0.03,
        max_consecutive_losses=5,
    )
    results["4h_ema20_50_daily_sma200_atr3"] = {
        "seed": atr_seed,
        "account": atr_account,
        "native_timeframe_hours": 4,
        "last_processed_timestamp": atr_account["last_timestamp"],
        "processed_this_cycle": max(
            0, int(atr_account["processed_new_candles"]) - atr_processed_before
        ),
    }

    for name, item in results.items():
        if "processed_this_cycle" not in item:
            item["processed_this_cycle"] = int(
                item["account"]["processed_new_candles"]
            )

    processed = sum(int(item["processed_this_cycle"]) for item in results.values())
    paused = any(
        bool(item["account"].get("paused"))
        or bool(item["account"].get("risk_pause_reasons"))
        for item in results.values()
    )
    summary = {}
    for name, item in results.items():
        account = item["account"]
        if "equity_after_estimated_exit_costs_usd" in account:
            equity = float(account["equity_after_estimated_exit_costs_usd"])
            initial = float(account["initial_cash_usd"])
            trades = int(account["completed_trades"])
            fees = float(account["fees_paid_usd"])
            drawdown = float(account["max_drawdown_pct"])
            open_position = bool(account["open_position"])
            cash = float(account["cash_usd"])
            risk_pauses = list(account["risk_pause_reasons"])
            processed_count = int(item["processed_this_cycle"])
            last_timestamp = account["last_processed_timestamp"]
        else:
            equity = float(account["equity_usd"])
            initial = float(account["initial_cash_usd"])
            trades = int(account["completed_trades"])
            fees = float(account["fees_paid_usd"])
            drawdown = float(account["max_drawdown_pct"])
            open_position = bool(account["open_position"])
            cash = float(account["cash_usd"])
            risk_pauses = [account["pause_reason"]] if account["paused"] else []
            processed_count = int(item["processed_this_cycle"])
            last_timestamp = account["last_timestamp"]
        summary[name] = {
            "timeframe_hours": item["native_timeframe_hours"],
            "initial_cash_usd": round(initial, 2),
            "equity_usd": round(equity, 4),
            "return_pct": round((equity / initial - 1.0) * 100.0, 4),
            "cash_usd": round(cash, 4),
            "completed_trades": trades,
            "fees_paid_usd": round(fees, 4),
            "max_drawdown_pct": round(drawdown, 4),
            "open_position": open_position,
            "processed_new_candles": processed_count,
            "last_processed_timestamp": last_timestamp,
            "risk_pause_reasons": risk_pauses,
            "mode": account.get("mode", "FORWARD_ONLY_PAPER"),
        }

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "FOUR_QUALIFIED_CANDIDATES_FORWARD_ONLY_PAPER",
        "status": "RISK_PAUSED" if paused else "PAPER_MONITORING",
        "cycle_status": (
            "PROCESSED_NEW_CANDLES"
            if processed else "WAITING_FOR_NEW_CLOSED_CANDLES"
        ),
        "total_processed_new_candles": processed,
        "market": "BTC/USD",
        "data_quality": quality,
        "initial_cash_usd": round(sum(x["initial_cash_usd"] for x in summary.values()), 2),
        "equity_usd": round(sum(x["equity_usd"] for x in summary.values()), 4),
        "return_pct": round(
            (
                sum(x["equity_usd"] for x in summary.values())
                / sum(x["initial_cash_usd"] for x in summary.values())
                - 1.0
            ) * 100.0,
            4,
        ),
        "completed_trades": sum(x["completed_trades"] for x in summary.values()),
        "fees_paid_usd": round(sum(x["fees_paid_usd"] for x in summary.values()), 4),
        "candidates": summary,
        "live_trading_eligible": False,
        "warning": (
            "Paper simulation only. Historical bars warm indicators and never "
            "create trades or PnL. Only newer completed native-timeframe bars "
            "are processed; synthetic aggregate bars cannot execute."
        ),
    }
    return report


def main():
    # 400 days supplies >200 completed daily bars without downloading the
    # entire multi-year research dataset on every scheduled monitor cycle.
    candles = load_two_year_candles(days=400)
    report = process_qualified_forward_candidates(candles)
    _write_json_atomically(report, "qualified_forward_paper_report.json")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("QUALIFIED FORWARD PAPER MONITOR ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
