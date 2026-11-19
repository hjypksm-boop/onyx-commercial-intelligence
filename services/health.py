"""Customer health scoring — configurable, data-driven, explainable.

Inputs come from SQL view ``v_health_inputs`` (or the same query evaluated at a historical date).
Scores are written to ``health_snapshots``; every KPI view reads the latest snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy.engine import Engine

from services import audit, db

COMPONENTS: list[tuple[str, str]] = [
    ("adoption", "Product adoption"),
    ("usage_trend", "Usage trend"),
    ("support", "Support experience"),
    ("engagement", "Renewal proximity & engagement"),
    ("sentiment", "Customer sentiment"),
]
COMPONENT_LABEL = dict(COMPONENTS)
DEFAULT_WEIGHTS = {"adoption": 30, "usage_trend": 25, "support": 15, "engagement": 15, "sentiment": 15}

HEALTHY_MIN, MONITOR_MIN = 80.0, 60.0

DEFINITIONS = {
    "adoption": "Active ÷ licensed seats × 100 (capped at 100).",
    "usage_trend": "Average MAU of the last 3 months vs the previous 3 months; score = clamp(80 + % change × 150, 0, 100). "
                   "Stable ≈ 80, growth scores higher, decline lower.",
    "support": "100 − 15×open high/critical − 8×open medium − 3×open low − 10×SLA breaches in the last 90 days (floor 0).",
    "engagement": "100 − 1.5 × days since last meaningful contact (meeting, call, email, demo); −25 if renewal ≤ 60 days "
                  "and no meeting in the last 45 days; clamp 0–100.",
    "sentiment": "Average of the last 3 recorded meeting sentiments (1–5) mapped to (s − 1) × 25.",
}


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def category(score: float | None) -> str | None:
    if score is None:
        return None
    s = round(float(score), 1)
    if s >= HEALTHY_MIN:
        return "Healthy"
    if s >= MONITOR_MIN:
        return "Monitor"
    return "At Risk"


def validate_weights(weights: dict) -> list[str]:
    errors = []
    for k, _ in COMPONENTS:
        v = weights.get(k)
        if v is None:
            errors.append(f"{COMPONENT_LABEL[k]} weight is required.")
            continue
        if not float(v).is_integer():
            errors.append(f"{COMPONENT_LABEL[k]} weight must be a whole percentage.")
        if v < 0 or v > 100:
            errors.append(f"{COMPONENT_LABEL[k]} weight must be between 0 and 100.")
    total = sum(float(weights.get(k) or 0) for k, _ in COMPONENTS)
    if abs(total - 100) > 1e-9:
        errors.append(f"Weights must total exactly 100% (currently {total:g}%).")
    return errors


def _num(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except TypeError:
        pass
    return float(v)


def component_scores(inp: dict, use_current_seats: bool = True) -> dict[str, dict]:
    """Return {component: {score|None, raw, missing_reason, phrase}} for one customer's input row."""
    out: dict[str, dict] = {}

    # Adoption
    lic = _num(inp.get("licensed_seats"))
    act = _num(inp.get("active_users") if use_current_seats else inp.get("mau_current_month"))
    if lic and act is not None:
        pct = act / lic * 100
        out["adoption"] = {"score": clamp(pct), "raw": f"{int(act)} of {int(lic)} seats active ({pct:.1f}%)",
                           "phrase": f"{pct:.0f}% seat adoption"}
    else:
        out["adoption"] = {"score": None, "raw": "—", "missing": "No licensed seat data recorded"}

    # Usage trend
    prev, last = _num(inp.get("mau_prev3_avg")), _num(inp.get("mau_last3_avg"))
    if not prev or (_num(inp.get("prev3_months_with_data")) or 0) < 1:
        out["usage_trend"] = {"score": None, "raw": "—",
                              "missing": "Less than 6 months of usage history to compare"}
    else:
        last = last or 0.0
        chg = (last - prev) / prev
        out["usage_trend"] = {
            "score": clamp(80 + chg * 150),
            "raw": f"Avg MAU {last:.1f} (last 3m) vs {prev:.1f} (prev 3m): {chg * 100:+.1f}%",
            "phrase": f"MAU {'up' if chg >= 0 else 'down'} {abs(chg) * 100:.0f}% (3m vs prior 3m)",
            "pct_change": chg,
        }

    # Support experience (no open tickets is valid data, not missing)
    h, m, lo, b = (int(_num(inp.get(k)) or 0) for k in ("open_high", "open_medium", "open_low", "sla_breaches_90d"))
    out["support"] = {
        "score": clamp(100 - 15 * h - 8 * m - 3 * lo - 10 * b),
        "raw": f"Open: {h} high/critical, {m} medium, {lo} low; {b} SLA breach(es) in 90 days",
        "phrase": (f"{h + m + lo} open ticket(s), {b} SLA breach(es) in 90d" if (h + m + lo + b)
                   else "no open support issues"),
    }

    # Renewal proximity & engagement
    days_c = _num(inp.get("days_since_contact"))
    if days_c is None:
        out["engagement"] = {"score": None, "raw": "—", "missing": "No customer contact recorded"}
    else:
        s = 100 - 1.5 * days_c
        dtr = _num(inp.get("days_to_renewal"))
        dsm = _num(inp.get("days_since_meeting"))
        penalty = dtr is not None and dtr <= 60 and (dsm is None or dsm > 45)
        if penalty:
            s -= 25
        raw = f"Last contact {int(days_c)} day(s) ago; renewal in {int(dtr) if dtr is not None else '?'} days"
        raw += "; no meeting in last 45 days (−25)" if penalty else ""
        phrase = "contacted today" if int(days_c) == 0 else f"last contact {int(days_c)} days ago"
        if penalty:
            phrase += f", renewal in {int(dtr)} days with no recent meeting"
        out["engagement"] = {"score": clamp(s), "raw": raw, "phrase": phrase}

    # Sentiment
    n = int(_num(inp.get("sentiment_n")) or 0)
    avg = _num(inp.get("sentiment_avg"))
    if not n or avg is None:
        out["sentiment"] = {"score": None, "raw": "—", "missing": "No meeting sentiment recorded"}
    else:
        out["sentiment"] = {"score": clamp((avg - 1) * 25), "raw": f"Average of last {n} meeting(s): {avg:.2f} / 5",
                            "phrase": f"meeting sentiment {avg:.1f}/5"}
    return out


def combine(comps: dict[str, dict], weights: dict) -> tuple[float | None, int, dict[str, float]]:
    """Weighted score with missing components excluded and remaining weights re-normalised."""
    avail = [k for k, _ in COMPONENTS if comps.get(k, {}).get("score") is not None]
    if not avail:
        return None, 0, {}
    total_w = sum(float(weights[k]) for k in avail)
    if total_w <= 0:  # all available components have zero weight → equal weighting
        eff = {k: 1 / len(avail) for k in avail}
    else:
        eff = {k: float(weights[k]) / total_w for k in avail}
    score = sum(comps[k]["score"] * eff[k] for k in avail)
    return round(score, 1), len(avail), eff


def reason_sentence(comps: dict[str, dict], score: float, cat: str, available: int) -> str:
    scored = [(k, c["score"]) for k, c in comps.items() if c.get("score") is not None]
    scored.sort(key=lambda kv: kv[1])
    if cat == "Healthy":
        strengths = [comps[k]["phrase"] for k, _ in reversed(scored[-2:])]
        s = f"Healthy ({score:.0f}/100) — strengths: {'; '.join(strengths)}."
        watch = [comps[k]["phrase"] for k, sc in scored if sc < 70]
        if watch:
            s += f" Watch: {watch[0]}."
    else:
        weak = [comps[k]["phrase"] for k, _ in scored[:2]]
        s = f"{cat} ({score:.0f}/100) — driven by {'; '.join(weak)}."
    if available < len(COMPONENTS):
        missing = [COMPONENT_LABEL[k] for k, c in comps.items() if c.get("score") is None]
        s += f" Partial score — {available} of {len(COMPONENTS)} components (missing: {', '.join(missing)})."
    return s


@dataclass
class HealthResult:
    customer_id: int
    customer_name: str
    score: float | None
    category: str | None
    available: int
    components: dict
    effective_weights: dict
    reason: str


def evaluate_row(inp: dict, weights: dict, use_current_seats: bool = True) -> HealthResult:
    comps = component_scores(inp, use_current_seats)
    score, available, eff = combine(comps, weights)
    cat = category(score)
    reason = reason_sentence(comps, score, cat, available) if score is not None else "No health data available."
    return HealthResult(int(inp["customer_id"]), inp.get("customer_name", ""), score, cat, available, comps, eff, reason)


def get_weights(engine: Engine) -> dict:
    row = db.query_one(engine, "SELECT adoption, usage_trend, support, engagement, sentiment, effective_from, changed_by "
                               "FROM health_weights ORDER BY weights_id DESC LIMIT 1")
    if not row:
        return dict(DEFAULT_WEIGHTS)
    return {k: int(row[k]) for k, _ in COMPONENTS}


def load_inputs(engine: Engine, as_of: str | None = None) -> pd.DataFrame:
    if as_of is None:
        return db.query_df(engine, "SELECT * FROM v_health_inputs ORDER BY customer_id")
    sql = db.load_query(engine, "health_inputs", param_as_of=True)
    return db.query_df(engine, sql + " ORDER BY c.customer_id", {"as_of": as_of})


def compute(engine: Engine, weights: dict | None = None, as_of: str | None = None) -> list[HealthResult]:
    weights = weights or get_weights(engine)
    current = as_of is None or as_of == db.as_of(engine)
    df = load_inputs(engine, as_of)
    return [evaluate_row(r, weights, use_current_seats=current) for r in df.to_dict("records")]


def results_frame(results: list[HealthResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        row = {"customer_id": r.customer_id, "customer_name": r.customer_name, "score": r.score,
               "category": r.category, "components_available": r.available, "reason": r.reason}
        for k, _ in COMPONENTS:
            row[f"{k}_score"] = r.components[k]["score"]
        rows.append(row)
    return pd.DataFrame(rows)


def breakdown(result: HealthResult, weights: dict) -> pd.DataFrame:
    rows = []
    for k, label in COMPONENTS:
        c = result.components[k]
        eff = result.effective_weights.get(k)
        rows.append({
            "Component": label,
            "Raw input": c["raw"] if c.get("score") is not None else f"Missing — {c.get('missing')}",
            "Component score": None if c.get("score") is None else round(c["score"], 1),
            "Weight": f"{weights[k]}%" + (f" → {eff * 100:.1f}%" if eff is not None and abs(eff * 100 - weights[k]) > 0.05 else ""),
            "Weighted contribution": None if eff is None else round(c["score"] * eff, 1),
        })
    return pd.DataFrame(rows)


def _write_snapshots(conn, results: list[HealthResult], snapshot_date: str) -> None:
    for r in results:
        if r.score is None:
            continue
        db.execute(conn, "DELETE FROM health_snapshots WHERE customer_id = :c AND snapshot_date = :d",
                   {"c": r.customer_id, "d": snapshot_date})
        sc = {k: (None if r.components[k]["score"] is None else round(r.components[k]["score"], 1)) for k, _ in COMPONENTS}
        db.execute(conn, """INSERT INTO health_snapshots (customer_id, snapshot_date, score, category, adoption_score,
                     usage_trend_score, support_score, engagement_score, sentiment_score, components_available)
                     VALUES (:c, :d, :s, :cat, :a, :u, :sp, :e, :se, :n)""",
                   {"c": r.customer_id, "d": snapshot_date, "s": r.score, "cat": r.category, "a": sc["adoption"],
                    "u": sc["usage_trend"], "sp": sc["support"], "e": sc["engagement"], "se": sc["sentiment"],
                    "n": r.available})


def refresh_snapshots(engine: Engine) -> list[HealthResult]:
    """Recalculate health at the demo clock date and upsert today's snapshot."""
    results = compute(engine)
    with engine.begin() as conn:
        _write_snapshots(conn, results, db.as_of(engine))
    return results


def write_history(engine: Engine, dates: list[str]) -> None:
    weights = get_weights(engine)
    for d in dates:
        results = compute(engine, weights, as_of=d)
        with engine.begin() as conn:
            _write_snapshots(conn, results, d)


def save_weights(engine: Engine, weights: dict, user_email: str) -> None:
    errors = validate_weights(weights)
    if errors:
        raise ValueError(" ".join(errors))
    old = get_weights(engine)
    with engine.begin() as conn:
        new_id = db.insert_returning_id(
            conn,
            """INSERT INTO health_weights (adoption, usage_trend, support, engagement, sentiment, effective_from, changed_by)
               VALUES (:adoption, :usage_trend, :support, :engagement, :sentiment, :ts, :u) RETURNING weights_id""",
            {**{k: int(weights[k]) for k, _ in COMPONENTS}, "ts": audit.now_ts(), "u": user_email},
        )
        audit.log(conn, user_email, "health_weights", new_id, "update", "Health score weights changed",
                  changes=audit.diff(old, {k: int(weights[k]) for k, _ in COMPONENTS}))
    refresh_snapshots(engine)
