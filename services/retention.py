"""Retention workspace: recovery plans, evidence, hypotheses vs confirmed causes, GRR/NRR."""
from __future__ import annotations

import json

import pandas as pd
from sqlalchemy.engine import Engine

from services import audit, customers, db

RECOVERY_STATUSES = ["Not started", "Investigating", "Customer contacted", "Plan agreed", "Improving", "Renewed", "Churned"]
STEPS = [
    (1, "Investigate account data"),
    (2, "Identify potential root causes"),
    (3, "Contact customer"),
    (4, "Agree recovery actions"),
    (5, "Track improvements"),
    (6, "Review renewal outcome"),
]
STEP_STATUS = {1: "Investigating", 2: "Investigating", 3: "Customer contacted", 4: "Plan agreed", 5: "Improving"}
CAUSE_CATEGORIES = ["Champion change", "Product / data quality", "Onboarding gap", "Budget / commercial",
                    "Organisational change", "Seasonality", "Alternative channel (API / data feed)", "Competitor", "Other"]
ALTERNATIVE_EXPLANATIONS = [
    ("Seasonality", "Compare with the same months last year and the customer's trading calendar."),
    ("Team restructure", "Check account notes and contact changes for re-organisations or desk moves."),
    ("Champion left", "Check whether the champion or power users have left (contacts marked 'Left')."),
    ("Budget freeze", "Ask about spend reviews; check for lost opportunities citing budget."),
    ("Using data via another channel / API", "Low UI logins can hide healthy API or data-feed consumption — check API calls."),
    ("Onboarding incomplete", "Check outstanding onboarding milestones and training completion."),
]
OUTCOMES = ["Renewed", "Renewed with downsell", "Churned"]


# ------------------------------------------------------------------------------------------------ plans
def get_plan(engine: Engine, customer_id: int) -> dict | None:
    p = db.query_one(engine, "SELECT * FROM recovery_plans WHERE customer_id = :c", {"c": customer_id})
    if p:
        p["step_notes"] = json.loads(p["step_notes"] or "{}")
    return p


def ensure_plan(engine: Engine, user: str, customer_id: int, owner_id: int | None) -> dict:
    p = get_plan(engine, customer_id)
    if p:
        return p
    as_of = db.as_of(engine)
    with engine.begin() as conn:
        pid = db.insert_returning_id(conn, """INSERT INTO recovery_plans (customer_id, status, current_step, owner_id,
                step_notes, updated_on) VALUES (:c, 'Not started', 1, :o, '{}', :d) RETURNING plan_id""",
                                     {"c": customer_id, "o": owner_id, "d": as_of})
        audit.log(conn, user, "recovery_plan", pid, "create", "Recovery plan opened", customer_id)
    return get_plan(engine, customer_id)


def update_plan(engine: Engine, user: str, customer_id: int, *, status: str | None = None,
                current_step: int | None = None, note_step: int | None = None, note: str | None = None,
                outcome: str | None = None, outcome_reason: str | None = None, owner_id: int | None = None) -> None:
    p = get_plan(engine, customer_id)
    if not p:
        raise ValueError("No recovery plan for this customer.")
    as_of = db.as_of(engine)
    new = {"status": status or p["status"], "current_step": current_step or p["current_step"],
           "owner_id": owner_id if owner_id is not None else p["owner_id"], "outcome": outcome or p["outcome"],
           "outcome_reason": outcome_reason if outcome_reason is not None else p["outcome_reason"]}
    if new["status"] not in RECOVERY_STATUSES:
        raise ValueError("Invalid recovery status.")
    if not 1 <= int(new["current_step"]) <= 6:
        raise ValueError("Invalid step.")
    if new["outcome"] and new["outcome"] not in OUTCOMES:
        raise ValueError("Invalid outcome.")
    if outcome == "Churned" and not (outcome_reason or "").strip():
        raise ValueError("A churn reason is required.")
    notes = dict(p["step_notes"])
    if note_step is not None and note is not None:
        notes[str(note_step)] = note
    started_on, base_mau, base_score = p["started_on"], p["baseline_mau"], p["baseline_score"]
    if not started_on and new["status"] != "Not started":
        started_on = as_of
        k = db.query_one(engine, "SELECT active_users, health_score FROM v_customer_kpis WHERE customer_id = :c",
                         {"c": customer_id}) or {}
        base_mau, base_score = k.get("active_users"), k.get("health_score")
    old_cmp = {k: p[k] for k in new} | {"notes": p["step_notes"]}
    changes = audit.diff(old_cmp, new | {"notes": notes})
    if not changes:
        return
    with engine.begin() as conn:
        db.execute(conn, """UPDATE recovery_plans SET status=:status, current_step=:current_step, owner_id=:owner_id,
                            outcome=:outcome, outcome_reason=:outcome_reason, step_notes=:notes, started_on=:so,
                            baseline_mau=:bm, baseline_score=:bs, updated_on=:d WHERE customer_id=:c""",
                   {**new, "notes": json.dumps(notes), "so": started_on, "bm": base_mau, "bs": base_score, "d": as_of,
                    "c": customer_id})
        audit.log(conn, user, "recovery_plan", p["plan_id"], "update", f"Recovery plan updated ({new['status']})",
                  customer_id, changes={k: v for k, v in changes.items() if k != "notes"} or {"notes": ["…", "updated"]})


def progress(engine: Engine, customer_id: int) -> dict | None:
    p = get_plan(engine, customer_id)
    if not p or not p["started_on"]:
        return None
    k = db.query_one(engine, "SELECT active_users, health_score FROM v_customer_kpis WHERE customer_id = :c",
                     {"c": customer_id})
    meetings = db.scalar(engine, """SELECT COUNT(*) FROM activities WHERE customer_id = :c AND activity_date >= :s
                                    AND activity_type IN ('Meeting', 'Call', 'Email', 'Demo')""",
                         {"c": customer_id, "s": p["started_on"]})
    tasks_done = db.scalar(engine, """SELECT COUNT(*) FROM tasks WHERE customer_id = :c AND status = 'Done'
                                      AND completed_on >= :s""", {"c": customer_id, "s": p["started_on"]})
    return {"started_on": p["started_on"], "baseline_mau": p["baseline_mau"], "current_mau": k["active_users"],
            "baseline_score": p["baseline_score"], "current_score": k["health_score"],
            "contacts_since": meetings, "tasks_done_since": tasks_done}


# ------------------------------------------------------------------------------------------------ evidence
def evidence(engine: Engine, customer_id: int) -> list[dict]:
    """Auto-surfaced evidence from stored records. Each item: area, finding, signal (red/amber/teal)."""
    as_of = db.as_of(engine)
    out: list[dict] = []
    dec = customers.mau_decline(engine, customer_id)
    if dec:
        sig = "red" if dec["change"] <= -0.25 else "amber" if dec["change"] < 0 else "teal"
        out.append({"area": "Usage trend", "signal": sig,
                    "finding": f"MAU {dec['from_mau']} → {dec['to_mau']} from {dec['from_month']} to {dec['to_month']} "
                               f"({dec['change'] * 100:+.0f}%). Monthly: {', '.join(map(str, dec['series']))}."})
    api = db.query_df(engine, """SELECT month, api_calls, logins FROM v_monthly_usage WHERE customer_id = :c
                                 ORDER BY month DESC LIMIT 6""", {"c": customer_id})
    if not api.empty and api["api_calls"].sum() > 0:
        recent, older = api.head(3)["api_calls"].sum(), api.tail(3)["api_calls"].sum()
        chg = (recent - older) / older if older else 0
        out.append({"area": "API / data channel", "signal": "teal" if chg >= 0 else "amber",
                    "finding": f"API calls last 3 months {int(recent):,} vs prior 3 months {int(older):,} ({chg * 100:+.0f}%)."})
    t = db.query_df(engine, """SELECT subject, severity, status, opened_date, sla_breached, escalated FROM support_tickets
                               WHERE customer_id = :c AND status NOT IN ('Resolved', 'Closed') ORDER BY opened_date""",
                    {"c": customer_id})
    br = db.scalar(engine, """SELECT COUNT(*) FROM support_tickets WHERE customer_id = :c AND sla_breached = 1
                              AND opened_date > :d""", {"c": customer_id, "d": _add_days(as_of, -90)})
    if not t.empty or br:
        out.append({"area": "Support history", "signal": "red" if (t["severity"].isin(["High", "Critical"]).any()) else "amber",
                    "finding": f"{len(t)} open ticket(s){': ' + '; '.join(t['severity'] + ' — ' + t['subject']) if len(t) else ''}. "
                               f"{br} SLA breach(es) in the last 90 days."})
    inc = db.query_df(engine, """SELECT dataset, incident_date, impact FROM data_incidents WHERE customer_id = :c
                                 AND incident_date > :d ORDER BY incident_date DESC""",
                      {"c": customer_id, "d": _add_days(as_of, -90)})
    if not inc.empty:
        out.append({"area": "Data availability", "signal": "red" if len(inc) >= 2 else "amber",
                    "finding": f"{len(inc)} data incident(s) in 90 days: " + "; ".join(inc["dataset"] + " (" + inc["impact"] + ")")})
    left = db.query_df(engine, """SELECT name, title, left_date, is_champion FROM contacts WHERE customer_id = :c
                                  AND status = 'Left'""", {"c": customer_id})
    for r in left.to_dict("records"):
        out.append({"area": "Champion / contact change", "signal": "red" if r["is_champion"] else "amber",
                    "finding": f"{r['name']} ({r['title']}{', champion' if r['is_champion'] else ''}) left on "
                               f"{r['left_date']}."})
    ob = db.query_df(engine, """SELECT milestone, target_date FROM onboarding_milestones WHERE customer_id = :c
                                AND completed_date IS NULL ORDER BY seq""", {"c": customer_id})
    if not ob.empty:
        out.append({"area": "Onboarding gaps", "signal": "amber",
                    "finding": "Incomplete milestones: " + "; ".join(ob["milestone"] + " (due " + ob["target_date"] + ")")})
    hi = db.query_one(engine, "SELECT * FROM v_health_inputs WHERE customer_id = :c", {"c": customer_id}) or {}
    if hi.get("days_since_contact") is not None:
        dsm = hi.get("days_since_meeting")
        sig = "red" if (hi["days_since_contact"] > 20 or (dsm or 999) > 45) else "teal"
        out.append({"area": "Contact gaps", "signal": sig,
                    "finding": f"Last contact {hi['days_since_contact']} days ago; last meeting "
                               f"{dsm if dsm is not None else 'never'} days ago; renewal in {hi['days_to_renewal']} days."})
    if hi.get("sentiment_avg") is not None:
        out.append({"area": "Sentiment", "signal": "red" if hi["sentiment_avg"] < 3 else "teal",
                    "finding": f"Average of last {hi['sentiment_n']} meeting sentiment scores: {hi['sentiment_avg']:.1f}/5."})
    else:
        out.append({"area": "Sentiment", "signal": "amber", "finding": "No meeting sentiment recorded (missing data)."})
    notes = db.query_df(engine, """SELECT note_date, body FROM account_notes WHERE customer_id = :c
                                   ORDER BY note_date DESC LIMIT 2""", {"c": customer_id})
    for r in notes.to_dict("records"):
        out.append({"area": "Account notes", "signal": "amber", "finding": f"{r['note_date']}: {r['body']}"})
    return out


def _add_days(iso: str, n: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


# ------------------------------------------------------------------------------------------------ hypotheses
def list_hypotheses(engine: Engine, customer_id: int) -> pd.DataFrame:
    return db.query_df(engine, """SELECT h.*, a.activity_date AS confirmed_on, a.subject AS confirmed_in
                                  FROM risk_hypotheses h LEFT JOIN activities a ON a.activity_id = h.confirmed_activity_id
                                  WHERE h.customer_id = :c ORDER BY CASE h.status WHEN 'Confirmed' THEN 0
                                  WHEN 'Hypothesis' THEN 1 ELSE 2 END, h.hypothesis_id""", {"c": customer_id})


def add_hypothesis(engine: Engine, user: str, customer_id: int, cause: str, category: str, evidence: str = "",
                   source: str = "Manual") -> int:
    """All new causes start as 'Hypothesis' — including AI suggestions."""
    if not (cause or "").strip():
        raise ValueError("Describe the potential root cause.")
    if category not in CAUSE_CATEGORIES:
        category = "Other"
    if source not in ("Manual", "AI", "System"):
        raise ValueError("Invalid source.")
    as_of = db.as_of(engine)
    with engine.begin() as conn:
        hid = db.insert_returning_id(conn, """INSERT INTO risk_hypotheses (customer_id, cause, category, status, evidence,
                source, created_by, created_on, updated_on) VALUES (:c, :cause, :cat, 'Hypothesis', :e, :s, :u, :d, :d)
                RETURNING hypothesis_id""", {"c": customer_id, "cause": cause.strip(), "cat": category,
                                             "e": (evidence or "").strip() or None, "s": source, "u": user, "d": as_of})
        audit.log(conn, user, "risk_hypothesis", hid, "create", f"Hypothesis logged ({source}): {cause.strip()[:80]}",
                  customer_id)
    return hid


def confirm_hypothesis(engine: Engine, user: str, hypothesis_id: int, activity_id: int, evidence: str) -> None:
    if not activity_id:
        raise ValueError("Select the customer conversation that confirmed this cause.")
    if not (evidence or "").strip():
        raise ValueError("Evidence is required to confirm a cause.")
    h = db.query_one(engine, "SELECT * FROM risk_hypotheses WHERE hypothesis_id = :id", {"id": hypothesis_id})
    if not h:
        raise ValueError("Hypothesis not found.")
    act = db.query_one(engine, "SELECT customer_id FROM activities WHERE activity_id = :a", {"a": activity_id})
    if not act or act["customer_id"] != h["customer_id"]:
        raise ValueError("The confirming conversation must belong to the same customer.")
    as_of = db.as_of(engine)
    with engine.begin() as conn:
        db.execute(conn, """UPDATE risk_hypotheses SET status = 'Confirmed', evidence = :e, confirmed_by = :u,
                            confirmed_activity_id = :a, updated_on = :d WHERE hypothesis_id = :id""",
                   {"e": evidence.strip(), "u": user, "a": activity_id, "d": as_of, "id": hypothesis_id})
        audit.log(conn, user, "risk_hypothesis", hypothesis_id, "update", f"Root cause confirmed: {h['cause'][:80]}",
                  h["customer_id"], changes={"status": [h["status"], "Confirmed"]})


def set_hypothesis_status(engine: Engine, user: str, hypothesis_id: int, status: str) -> None:
    if status not in ("Hypothesis", "Rejected"):
        raise ValueError("Use confirm_hypothesis to confirm a cause.")
    h = db.query_one(engine, "SELECT * FROM risk_hypotheses WHERE hypothesis_id = :id", {"id": hypothesis_id})
    with engine.begin() as conn:
        db.execute(conn, """UPDATE risk_hypotheses SET status = :s, confirmed_by = NULL, confirmed_activity_id = NULL,
                            updated_on = :d WHERE hypothesis_id = :id""",
                   {"s": status, "d": db.as_of(engine), "id": hypothesis_id})
        audit.log(conn, user, "risk_hypothesis", hypothesis_id, "update", f"Hypothesis marked {status}",
                  h["customer_id"], changes={"status": [h["status"], status]})


# ------------------------------------------------------------------------------------------------ metrics
def retention_metrics(engine: Engine) -> dict:
    rows = db.query_df(engine, db.load_query(engine, "retention_cohort"))
    start = float(rows["start_arr_pence"].sum()) if not rows.empty else 0.0
    current = float(rows["current_arr_pence"].sum()) if not rows.empty else 0.0
    lost = float((rows["start_arr_pence"] - rows["current_arr_pence"]).clip(lower=0).sum()) if not rows.empty else 0.0
    return {"cohort": rows, "start_arr_pence": start, "current_arr_pence": current,
            "grr": (start - lost) / start * 100 if start else None, "nrr": current / start * 100 if start else None,
            "downsell_churn_pence": lost, "expansion_pence": float((rows["current_arr_pence"] - rows["start_arr_pence"])
                                                                   .clip(lower=0).sum()) if not rows.empty else 0.0}


def renewal_forecast(engine: Engine, days: int = 90) -> pd.DataFrame:
    return db.query_df(engine, db.load_query(engine, "renewal_forecast"), {"days": days})
