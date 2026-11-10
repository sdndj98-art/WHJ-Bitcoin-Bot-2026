"""Fail-closed decision gate for research scanner candidates and paper sizing.

This module evaluates a candidate against an existing paper-account risk snapshot.
It never mutates an account, submits an order, or enables live execution.
"""
import math


REQUIRED_SCANNER_CHECKS = (
    "market_data_quality_pass",
    "volume_spike",
    "close_above_prior_high",
    "breakout_quality_confirmed",
    "trend_alignment",
    "rsi_momentum_healthy",
    "adx_trend_strength",
    "bullish_close_confirmation",
)


def _finite_positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def _fraction(value, name, maximum):
    result = _finite_positive(value, name)
    if result > maximum:
        raise ValueError(f"{name} exceeds its safety cap")
    return result


def evaluate_paper_decision(scanner_result, guard_account, sizing=None, cvd_confirmation=None, require_cvd_confirmation=False):
    """Return a paper-only decision; fail closed on any missing/invalid evidence.

    The scanner must supply its complete eight-check candidate and a hypothetical
    long risk map. The guard input must be a current PERSISTENT_PAPER_ONLY account
    snapshot with no active pause and no existing position. Sizing is capped by
    both an allocation ceiling and a maximum equity-risk budget.
    """
    sizing = {} if sizing is None else sizing
    if not isinstance(require_cvd_confirmation, bool):
        return {"status": "BLOCKED", "reasons": ["invalid_cvd_requirement_flag"], "paper_only": True, "execution_enabled": False, "order_placed": False}
    if not isinstance(sizing, dict):
        return {"status": "BLOCKED", "reasons": ["invalid_sizing_configuration"],
                "paper_only": True, "execution_enabled": False, "order_placed": False}

    reasons = []
    if not isinstance(scanner_result, dict):
        reasons.append("scanner_result_missing_or_invalid")
    if not isinstance(guard_account, dict):
        reasons.append("guard_account_missing_or_invalid")
    if reasons:
        return {"status": "BLOCKED", "reasons": reasons, "paper_only": True,
                "execution_enabled": False, "order_placed": False}

    if require_cvd_confirmation:
        if not isinstance(cvd_confirmation, dict):
            reasons.append("required_cvd_confirmation_missing")
        elif (cvd_confirmation.get("status") != "OK"
              or cvd_confirmation.get("available") is not True
              or cvd_confirmation.get("direction") != "BULLISH"
              or cvd_confirmation.get("continuity_verified") is not True
              or cvd_confirmation.get("research_only") is not True
              or cvd_confirmation.get("execution_enabled") is not False):
            reasons.append("required_cvd_confirmation_not_bullish_and_verified")
    if scanner_result.get("status") != "PAPER_CANDIDATE":
        reasons.append("scanner_candidate_not_approved")
    if scanner_result.get("paper_candidate_only") is not True:
        reasons.append("scanner_not_explicitly_paper_only")
    if scanner_result.get("live_orders_placed") is not False:
        reasons.append("scanner_live_execution_state_invalid")
    checks = scanner_result.get("checks")
    if not isinstance(checks, dict):
        reasons.append("scanner_checks_missing")
    else:
        if checks.get("ohlcv_valid") is not True:
            reasons.append("scanner_check_failed:ohlcv_valid")
        for check in REQUIRED_SCANNER_CHECKS:
            if checks.get(check) is not True:
                reasons.append(f"scanner_check_failed:{check}")
        if checks.get("paper_only") is not True:
            reasons.append("scanner_paper_only_flag_missing")
        if checks.get("live_execution_enabled") is not False:
            reasons.append("scanner_live_execution_flag_invalid")

    score = scanner_result.get("confluence_score")
    total = scanner_result.get("confluence_total")
    if (isinstance(score, bool) or not isinstance(score, int)
            or isinstance(total, bool) or not isinstance(total, int)
            or total != len(REQUIRED_SCANNER_CHECKS) or score != total):
        reasons.append("scanner_confluence_incomplete")

    if guard_account.get("mode") != "PERSISTENT_PAPER_ONLY":
        reasons.append("guard_account_mode_unverified")
    pause_reasons = guard_account.get("risk_pause_reasons")
    if not isinstance(pause_reasons, list):
        reasons.append("guard_pause_state_missing")
    elif pause_reasons:
        reasons.append("guard_risk_pause_active")
    for key in ("paused_for_drawdown", "daily_loss_paused",
                "paused_for_loss_streak", "paused_for_strategy_health"):
        if guard_account.get(key) is not False:
            reasons.append(f"guard_pause_flag_not_clear:{key}")
    if guard_account.get("open_position") is not False:
        reasons.append("guard_position_already_open")

    try:
        price = _finite_positive(scanner_result.get("current_close"), "scanner current_close")
        cash = _finite_positive(guard_account.get("cash_usd"), "guard cash")
        equity = _finite_positive(
            guard_account.get("equity_after_estimated_exit_costs_usd"), "guard equity"
        )
        risk_map = scanner_result.get("hypothetical_risk_map")
        if not isinstance(risk_map, dict) or risk_map.get("research_only") is not True:
            raise ValueError("hypothetical risk map is missing or not research-only")
        if risk_map.get("execution_enabled") is not False:
            raise ValueError("hypothetical risk map execution flag is invalid")
        reference = _finite_positive(risk_map.get("reference_price"), "risk map reference price")
        stop = _finite_positive(risk_map.get("stop_level"), "risk map stop")
        target = _finite_positive(risk_map.get("target_level"), "risk map target")
        if not math.isclose(reference, price, rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError("risk map reference price does not match scanner price")
        if not stop < price < target:
            raise ValueError("risk map levels do not define a valid long-side risk range")
        stop_distance = price - stop
    except (TypeError, ValueError, OverflowError) as exc:
        reasons.append(f"invalid_market_or_account_data:{exc}")
        price = cash = equity = stop_distance = 0.0

    try:
        allocation_fraction = _fraction(
            sizing.get("allocation_fraction", 0.10), "allocation_fraction", 0.10
        )
        risk_fraction = _fraction(
            sizing.get("risk_fraction", 0.01), "risk_fraction", 0.01
        )
    except (TypeError, ValueError, OverflowError) as exc:
        reasons.append(f"invalid_sizing_configuration:{exc}")
        allocation_fraction = risk_fraction = 0.0

    if reasons:
        return {"status": "BLOCKED", "reasons": reasons, "paper_only": True,
                "execution_enabled": False, "order_placed": False}

    allocation_cap = min(cash, equity * allocation_fraction, equity * 0.10)
    risk_budget = equity * risk_fraction
    risk_limited_notional = risk_budget * price / stop_distance
    notional = min(allocation_cap, risk_limited_notional)
    if not math.isfinite(notional) or notional <= 0:
        return {"status": "BLOCKED", "reasons": ["calculated_notional_invalid"],
                "paper_only": True, "execution_enabled": False, "order_placed": False}

    units = notional / price
    estimated_stop_risk = units * stop_distance
    if (not math.isfinite(units) or units <= 0
            or estimated_stop_risk > risk_budget * (1.0 + 1e-12)
            or notional > cash + 1e-12
            or notional > equity * 0.10 + 1e-12):
        return {"status": "BLOCKED", "reasons": ["sizing_safety_invariant_failed"],
                "paper_only": True, "execution_enabled": False, "order_placed": False}

    return {
        "status": "APPROVED_FOR_PAPER_SIMULATION_REVIEW_ONLY",
        "side": "LONG",
        "reference_price": round(price, 8),
        "notional_usd": round(notional, 8),
        "units": round(units, 12),
        "allocation_cap_usd": round(allocation_cap, 8),
        "risk_budget_usd": round(risk_budget, 8),
        "estimated_stop_risk_usd": round(estimated_stop_risk, 8),
        "stop_level": round(price - stop_distance, 8),
        "target_level": round(float(risk_map["target_level"]), 8),
        "paper_only": True,
        "research_only": True,
        "execution_enabled": False,
        "order_placed": False,
        "cvd_confirmation": cvd_confirmation if require_cvd_confirmation else None,
        "cvd_requirement_enabled": require_cvd_confirmation,
        "limitations": [
            "This is a decision and sizing preview only; it does not call the paper account.",
            "The existing paper-account engine remains responsible for its own entry, exit, fees and risk pauses.",
            "The hypothetical scanner stop is not installed as an account stop-loss.",
        ],
    }
