# CVD Paper-Decision Gate Validation

The forward paper monitor accepts `require_cvd_confirmation` only as a boolean. Invalid values are rejected before candle processing or any paper ledger can be seeded or updated.

When CVD confirmation is required, the paper decision gate fails closed unless the evidence is available, bullish, continuity-verified, research-only, and explicitly has execution disabled. This is a simulation/review safeguard only; it does not submit orders or enable live trading.

Regression coverage verifies that a non-boolean requirement flag raises `ValueError` and leaves the supplied paper-state directory unchanged.
