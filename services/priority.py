"""Commercial priority score (0–100). All constants live here."""
from __future__ import annotations

import pandas as pd

WEIGHTS = {"revenue": 0.35, "risk": 0.25, "renewal": 0.20, "expansion": 0.20}
RENEWAL_FULL_DAYS = 30     # ≤ 30 days → 100
RENEWAL_ZERO_DAYS = 180    # ≥ 180 days → 0

EXPLANATION = (
    "Commercial priority (0–100) = 35% revenue exposure (ARR ÷ largest ARR in the portfolio) "
    "+ 25% risk (100 − health score) + 20% renewal urgency (100 at ≤30 days, falling linearly to 0 at 180+ days) "
    "+ 20% expansion potential (probability-weighted open expansion ÷ portfolio maximum)."
)


def renewal_urgency(days) -> float:
    if days is None or pd.isna(days):
        return 0.0
    days = float(days)
    if days <= RENEWAL_FULL_DAYS:
        return 100.0
    if days >= RENEWAL_ZERO_DAYS:
        return 0.0
    return 100.0 * (RENEWAL_ZERO_DAYS - days) / (RENEWAL_ZERO_DAYS - RENEWAL_FULL_DAYS)


def add_priority(df: pd.DataFrame) -> pd.DataFrame:
    """Add priority components + score. Normalisation uses the maxima of the frame passed in (the full portfolio)."""
    out = df.copy()
    if out.empty:
        out["priority_score"] = []
        return out
    max_arr = float(out["arr_pence"].astype(float).max() or 0)
    max_exp = float(out["weighted_expansion_pence"].astype(float).max() or 0)
    out["p_revenue"] = out["arr_pence"].astype(float) / max_arr * 100 if max_arr else 0.0
    out["p_risk"] = 100 - out["health_score"].astype(float).fillna(100)
    out["p_renewal"] = out["days_to_renewal"].apply(renewal_urgency)
    out["p_expansion"] = out["weighted_expansion_pence"].astype(float) / max_exp * 100 if max_exp else 0.0
    out["priority_score"] = (WEIGHTS["revenue"] * out["p_revenue"] + WEIGHTS["risk"] * out["p_risk"]
                             + WEIGHTS["renewal"] * out["p_renewal"] + WEIGHTS["expansion"] * out["p_expansion"]).round(1)
    return out
