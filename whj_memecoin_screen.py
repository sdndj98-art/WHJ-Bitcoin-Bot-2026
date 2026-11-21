"""WHJ memecoin screening score.

This module scores a validated token snapshot; it does not fetch chain data,
approve trades, or submit orders. Missing critical fields lower confidence.
"""
from __future__ import annotations

from typing import Any


def _num(data: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(data.get(key, default))
        return value if value == value else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_token(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic screening result for a normalized token snapshot.

    Expected keys include market_cap_usd, liquidity_usd, volume_1h_usd,
    volume_5m_usd, buys_1h, sells_1h, unique_buyers_1h, top10_holder_pct,
    top1_holder_pct, insider_pct, linked_wallet_pct, lp_locked,
    mint_authority_revoked, freeze_authority_revoked, sell_simulation_passed,
    honeypot, dev_sold_pct, tax_bps, social_unique_authors and
    social_acceleration. Values must come from a trusted data adapter.
    """
    mcap = max(0.0, _num(snapshot, "market_cap_usd"))
    liquidity = max(0.0, _num(snapshot, "liquidity_usd"))
    vol1h = max(0.0, _num(snapshot, "volume_1h_usd"))
    vol5m = max(0.0, _num(snapshot, "volume_5m_usd"))
    buys = max(0.0, _num(snapshot, "buys_1h"))
    sells = max(0.0, _num(snapshot, "sells_1h"))
    top10 = _num(snapshot, "top10_holder_pct", 100.0)
    top1 = _num(snapshot, "top1_holder_pct", 100.0)
    insiders = _num(snapshot, "insider_pct", 100.0)
    linked = _num(snapshot, "linked_wallet_pct", 100.0)
    dev_sold = _num(snapshot, "dev_sold_pct", 0.0)
    tax_bps = max(0.0, _num(snapshot, "tax_bps", 10000.0))

    hard_blocks = []
    if snapshot.get("honeypot") is True:
        hard_blocks.append("honeypot_detected")
    if snapshot.get("sell_simulation_passed") is False:
        hard_blocks.append("sell_simulation_failed")
    if snapshot.get("mint_authority_revoked") is False:
        hard_blocks.append("mint_authority_active")
    if snapshot.get("freeze_authority_revoked") is False:
        hard_blocks.append("freeze_authority_active")
    if snapshot.get("lp_locked") is False:
        hard_blocks.append("liquidity_not_locked_or_burned")
    if mcap < 20000:
        hard_blocks.append("market_cap_below_20000_usd_screen")
    if liquidity < 10000:
        hard_blocks.append("liquidity_below_10000_usd")
    if tax_bps > 1000:
        hard_blocks.append("tax_above_10_percent")

    # Contract / control (40 points)
    contract = 40.0
    if snapshot.get("mint_authority_revoked") is not True:
        contract -= 12
    if snapshot.get("freeze_authority_revoked") is not True:
        contract -= 10
    if snapshot.get("lp_locked") is not True:
        contract -= 10
    if snapshot.get("sell_simulation_passed") is not True:
        contract -= 20
    contract -= min(10.0, tax_bps / 100.0)
    contract = _clamp(contract)

    # Holder and wallet topology (20 points)
    wallet = 20.0
    wallet -= max(0.0, top10 - 20.0) * 0.35
    wallet -= max(0.0, top1 - 5.0) * 1.0
    wallet -= max(0.0, insiders - 10.0) * 0.4
    wallet -= max(0.0, linked - 10.0) * 0.5
    wallet -= min(10.0, dev_sold * 0.5)
    wallet = _clamp(wallet)

    # Liquidity / tradability (15 points)
    liq_ratio = liquidity / mcap if mcap > 0 else 0.0
    liquidity_score = _clamp((liq_ratio / 0.20) * 10.0)
    liquidity_score += 5.0 if liquidity >= 50000 else 0.0
    liquidity_score = _clamp(liquidity_score, 0.0, 15.0)

    # Market momentum (15 points)
    buy_sell_ratio = buys / max(1.0, sells)
    volume_ratio = vol5m * 12.0 / max(1.0, vol1h)
    momentum = _clamp((buy_sell_ratio - 0.8) * 12.0, 0.0, 8.0)
    momentum += _clamp((volume_ratio - 0.5) * 10.0, 0.0, 7.0)

    # Social activity (10 points); author counts alone are not proof of authenticity.
    authors = max(0.0, _num(snapshot, "social_unique_authors"))
    social_accel = max(0.0, _num(snapshot, "social_acceleration"))
    coordinated = _clamp(_num(snapshot, "coordinated_post_pct"))
    social = _clamp(min(6.0, authors / 10.0) + min(4.0, social_accel * 2.0))
    social -= coordinated * 0.08
    social = _clamp(social)

    raw_score = round(contract + wallet + liquidity_score + momentum + social, 2)
    score = 0.0 if hard_blocks else raw_score

    missing_critical = [
        key for key in (
            "sell_simulation_passed", "honeypot", "lp_locked",
            "mint_authority_revoked", "freeze_authority_revoked",
            "top10_holder_pct", "liquidity_usd", "market_cap_usd",
        ) if key not in snapshot
    ]
    confidence = "LOW" if missing_critical else ("MEDIUM" if len(snapshot) < 18 else "HIGH")
    verdict = "REJECT" if hard_blocks else (
        "SELECTED_PAPER_ONLY" if score >= 85 and confidence != "LOW"
        else "WATCH" if score >= 65 else "SKIP"
    )

    return {
        "score": score,
        "raw_score_before_hard_blocks": raw_score,
        "verdict": verdict,
        "confidence": confidence,
        "missing_critical_data": missing_critical,
        "hard_blocks": hard_blocks,
        "components": {
            "contract_control_40": round(contract, 2),
            "holder_wallet_health_20": round(wallet, 2),
            "liquidity_15": round(liquidity_score, 2),
            "momentum_15": round(momentum, 2),
            "social_10": round(social, 2),
        },
        "execution": "DISABLED",
        "note": "Screening only; verify source timestamps and simulate fills before any trade.",
    }
